"""Local-only, bounded DOCX conversion. This container has no research credentials."""
from base64 import b64encode
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

MAX_INPUT = 50 * 1024 * 1024
MAX_UNPACKED = 200 * 1024 * 1024
MAX_OUTPUT = 80 * 1024 * 1024
TIMEOUT = 90
FONT_DIR = Path('/usr/local/share/fonts/paperassist')
LOCK_PATH = Path(__file__).with_name('renderer-lock.json')
SLOTS = threading.BoundedSemaphore(2)
PROFILE = '''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
</oor:items>'''


class RenderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_docx(content):
    """Only passive OOXML; never extract archive paths into the filesystem."""
    if not content or len(content) > MAX_INPUT:
        raise RenderError('pdf_input_invalid')
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if (len(names) > 2000 or len(set(names)) != len(names)
                    or not {'[Content_Types].xml', 'word/document.xml'}.issubset(names)
                    or sum(i.file_size for i in infos) > MAX_UNPACKED):
                raise ValueError('archive limit')
            for item in infos:
                name = item.filename.lower()
                if (PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                        or '\\' in name or ':' in name or item.flag_bits & 1
                        or any(p in name for p in ('vbaproject', 'activex', '/embeddings/'))):
                    raise ValueError('active object')
                if not name.endswith(('.xml', '.rels')):
                    continue
                raw = archive.read(item)
                # UTF-16 encodings cannot hide a DTD behind NUL bytes.
                if b'<!DOCTYPE' in raw.upper().replace(b'\x00', b'') or b'<!ENTITY' in raw.upper().replace(b'\x00', b''):
                    raise ValueError('entity declaration')
                root = ET.fromstring(raw)
                fields = []
                for node in root.iter():
                    local = node.tag.rsplit('}', 1)[-1]
                    if local in ('object', 'altChunk', 'oleObject', 'control'):
                        raise ValueError('active element')
                    if local == 'Relationship' and node.get('TargetMode', '').lower() == 'external':
                        if not node.get('Type', '').endswith('/hyperlink'):
                            raise ValueError('external load')
                    if local == 'instrText':
                        fields.append(node.text or '')
                    if local == 'fldSimple':
                        fields.extend(v for k, v in node.attrib.items() if k.rsplit('}', 1)[-1] == 'instr')
                    if local == 'Override' and 'macroenabled' in node.get('ContentType', '').lower():
                        raise ValueError('macro-enabled type')
                if re.search(r'\b(DDEAUTO|DDE|INCLUDETEXT|INCLUDEPICTURE|LINK|DATABASE)\b', ''.join(fields), re.I):
                    raise ValueError('active field')
    except (BadZipFile, ValueError, ET.ParseError, KeyError, OSError, RuntimeError) as exc:
        raise RenderError('pdf_input_invalid') from exc


def verify_fonts(fonts, directory=FONT_DIR):
    for name, expected in fonts.items():
        try:
            actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        except OSError:
            raise RenderError('pdf_renderer_mismatch') from None
        if actual != expected:
            raise RenderError('pdf_renderer_mismatch')


def run_process(command, timeout):
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True, env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp', 'HOME': '/tmp'})
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise RenderError('pdf_conversion_timeout') from None
    if code:
        raise RenderError('pdf_conversion_failed')


def convert(content, directory=None, *, process=run_process):
    validate_docx(content)
    with tempfile.TemporaryDirectory(prefix='pdf-', dir=directory) as temporary:
        folder = Path(temporary)
        source = folder / 'input.docx'
        source.write_bytes(content)
        source.chmod(0o444)
        profile = folder / 'profile'
        (profile / 'user').mkdir(parents=True)
        (profile / 'user/registrymodifications.xcu').write_text(PROFILE, encoding='utf-8')
        output = folder / 'output'
        output.mkdir()
        # Retain the existing passive conversion path for legacy documents. Layout
        # documents require actual field/index update in the same office session.
        with ZipFile(BytesIO(content)) as package:
            has_layout = 'customXml/paperassist-layout.xml' in package.namelist()
        if has_layout:
            process(['/usr/bin/python3', str(Path(__file__).with_name('update_fields.py')),
                     '--source', str(source), '--profile', str(profile),
                     '--pdf', str(output / 'input.pdf')], TIMEOUT)
        else:
            process(['soffice', '-env:UserInstallation=' + profile.as_uri(), '--headless', '--nologo',
                     '--nodefault', '--nofirststartwizard', '--norestore', '--convert-to',
                     'pdf:writer_pdf_Export:{"UseLosslessCompression":{"type":"boolean","value":"true"},"ExportBookmarks":{"type":"boolean","value":"true"}}',
                     '--outdir', str(output), str(source)], TIMEOUT)
        target = output / 'input.pdf'
        try:
            if target.stat().st_size > MAX_OUTPUT:
                raise RenderError('pdf_conversion_failed')
            data = target.read_bytes()
        except OSError:
            raise RenderError('pdf_conversion_failed') from None
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:]:
            raise RenderError('pdf_conversion_failed')
        return data


def layout_cache(content, directory=None, *, process=run_process):
    validate_docx(content)
    with tempfile.TemporaryDirectory(prefix='layout-', dir=directory) as temporary:
        folder = Path(temporary)
        source = folder / 'input.docx'
        source.write_bytes(content)
        source.chmod(0o444)
        profile = folder / 'profile'
        (profile / 'user').mkdir(parents=True)
        (profile / 'user/registrymodifications.xcu').write_text(PROFILE, encoding='utf-8')
        target = folder / 'fields.json'
        process(['/usr/bin/python3', str(Path(__file__).with_name('update_fields.py')),
                 '--source', str(source), '--profile', str(profile), '--cache', str(target)], TIMEOUT)
        try:
            if target.stat().st_size > 2 * 1024 * 1024:
                raise ValueError()
            result = json.loads(target.read_text(encoding='utf-8'))
            if not isinstance(result, dict) or not isinstance(result.get('fields'), dict) or not isinstance(result.get('toc_lines'), list):
                raise ValueError()
        except (OSError, ValueError):
            raise RenderError('pdf_conversion_failed') from None
        result['source_sha256'] = hashlib.sha256(content).hexdigest()
        return result


def verify_environment():
    manifest = json.loads(LOCK_PATH.read_text(encoding='utf-8'))
    package = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'libreoffice-writer'], text=True)
    if package != manifest['libreoffice_package']:
        raise RenderError('pdf_renderer_mismatch')
    uno_package = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'python3-uno'], text=True)
    if uno_package != manifest['uno_package']:
        raise RenderError('pdf_renderer_mismatch')
    math_package = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'libreoffice-math'], text=True)
    if math_package != manifest['math_package']:
        raise RenderError('pdf_renderer_mismatch')
    verify_fonts(manifest['fonts'])
    verify_fonts(manifest['system_fonts'], Path('/'))
    # The image is immutable at runtime. The package list binds indirect rendering libraries too.
    packages = subprocess.check_output(['dpkg-query', '-W', '-f=${Package}=${Version}\n'])
    if hashlib.sha256(packages).hexdigest() != manifest['system_packages_sha256']:
        raise RenderError('pdf_renderer_mismatch')
    return manifest


class Handler(BaseHTTPRequestHandler):
    server_version = 'PaperAssistPDF/1'
    def log_message(self, *_):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def respond(self, status, body, media='application/json', manifest=None):
        self.send_response(status)
        self.send_header('Content-Type', media)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        if manifest:
            self.send_header('X-Renderer-Manifest', b64encode(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).decode())
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        if self.path != '/health':
            return self.respond(404, b'{}')
        self.respond(200, json.dumps(self.server.manifest).encode())

    def do_POST(self):
        if self.path not in ('/convert', '/layout-cache'):
            return self.respond(404, b'{}')
        if not SLOTS.acquire(blocking=False):
            return self.respond(429, b'{"code":"pdf_renderer_busy"}')
        try:
            length = self.headers.get('Content-Length', '')
            if self.headers.get('Transfer-Encoding') or not length.isdigit() or not 0 < int(length) <= MAX_INPUT:
                raise RenderError('pdf_input_invalid')
            content = self.rfile.read(int(length))
            if len(content) != int(length):
                raise RenderError('pdf_input_invalid')
            verify_fonts(self.server.manifest['fonts'])
            verify_fonts(self.server.manifest['system_fonts'], Path('/'))
            if self.path == '/layout-cache':
                data = json.dumps(layout_cache(content), ensure_ascii=False).encode('utf-8')
                self.respond(200, data, 'application/json', self.server.manifest)
            else:
                data = convert(content)
                self.respond(200, data, 'application/pdf', self.server.manifest)
        except RenderError as exc:
            self.respond(422 if exc.code == 'pdf_input_invalid' else 503, json.dumps({'code': exc.code}).encode())
        except (OSError, ValueError):
            self.respond(503, b'{"code":"pdf_conversion_failed"}')
        finally:
            SLOTS.release()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8


if __name__ == '__main__':
    manifest = verify_environment()
    server = Server(('0.0.0.0', 8080), Handler)
    server.manifest = manifest
    server.serve_forever()
