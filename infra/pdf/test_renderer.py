"""Conversion-boundary tests require no database, Docker, or external service."""
import importlib.util
from io import BytesIO
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest


def runtime():
    spec = importlib.util.spec_from_file_location('pdf_runtime', Path(__file__).with_name('renderer.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def docx(extra=None):
    stream = BytesIO()
    with ZipFile(stream, 'w') as archive:
        parts = {'[Content_Types].xml': '<Types/>', 'word/document.xml': '<document/>'} | (extra or {})
        for name, value in parts.items():
            archive.writestr(name, value)
    return stream.getvalue()


def test_accepts_plain_docx_and_hyperlinks_without_extracting_files():
    mod = runtime()
    mod.validate_docx(docx({'word/_rels/document.xml.rels': '<Relationships><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" TargetMode="External" Target="https://example.invalid"/></Relationships>'}))


@pytest.mark.parametrize('extra', [
    {'word/vbaProject.bin': 'macro'},
    {'word/embeddings/object.bin': 'object'},
    {'../escape': 'outside'},
    {'word/_rels/document.xml.rels': '<Relationships><Relationship Type="image" TargetMode="External" Target="file:///etc/passwd"/></Relationships>'},
    {'word/document.xml': '<document><instrText>DDEAUTO evil</instrText></document>'},
    {'word/document.xml': '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><document/>'},
])
def test_rejects_active_or_external_loads(extra):
    mod = runtime()
    with pytest.raises(mod.RenderError) as error:
        mod.validate_docx(docx(extra))
    assert error.value.code == 'pdf_input_invalid'


def test_input_size_and_inflated_size_are_bounded(monkeypatch):
    mod = runtime()
    monkeypatch.setattr(mod, 'MAX_INPUT', 10)
    with pytest.raises(mod.RenderError):
        mod.validate_docx(docx())
    monkeypatch.setattr(mod, 'MAX_INPUT', 100000)
    monkeypatch.setattr(mod, 'MAX_UNPACKED', 10)
    with pytest.raises(mod.RenderError):
        mod.validate_docx(docx())


def test_each_conversion_has_readonly_input_separate_profile_and_cleanup(tmp_path):
    mod = runtime()
    seen = []
    def process(command, timeout):
        profile = next(v for v in command if v.startswith('-env:UserInstallation='))
        source = Path(command[-1])
        out = Path(command[command.index('--outdir') + 1])
        seen.append((profile, source))
        assert source.read_bytes() == docx()
        assert source.stat().st_mode & 0o222 == 0
        settings = (source.parent / 'profile/user/registrymodifications.xcu').read_text()
        assert 'MacroSecurityLevel' in settings and '<value>3</value>' in settings
        assert '--headless' in command and '--norestore' in command
        (out / 'input.pdf').write_bytes(b'%PDF-1.7\nsynthetic\n%%EOF\n')
    for _ in range(2):
        assert mod.convert(docx(), tmp_path, process=process).startswith(b'%PDF-')
    assert seen[0][0] != seen[1][0]
    assert not list(tmp_path.iterdir())


def test_timeout_and_invalid_output_cleanup(tmp_path):
    mod = runtime()
    def timeout(command, limit):
        raise mod.RenderError('pdf_conversion_timeout')
    with pytest.raises(mod.RenderError, match='pdf_conversion_timeout'):
        mod.convert(docx(), tmp_path, process=timeout)
    assert not list(tmp_path.iterdir())
    with pytest.raises(mod.RenderError, match='pdf_conversion_failed'):
        mod.convert(docx(), tmp_path, process=lambda *_: None)
    assert not list(tmp_path.iterdir())


def test_font_hash_mismatch_is_not_silently_substituted(tmp_path):
    mod = runtime()
    (tmp_path / 'arial.ttf').write_bytes(b'changed font')
    with pytest.raises(mod.RenderError, match='pdf_renderer_mismatch'):
        mod.verify_fonts({'arial.ttf': 'a' * 64}, tmp_path)


def test_layout_field_cache_uses_isolated_uno_and_validates_response(tmp_path):
    mod = runtime()
    seen = []
    def process(command, timeout):
        seen.append(command)
        source = Path(command[command.index('--source') + 1])
        target = Path(command[command.index('--cache') + 1])
        assert source.stat().st_mode & 0o222 == 0
        target.write_text('{"fields":{"PAF000000":"1"},"toc_lines":["Methods\\t1"]}')
    result = mod.layout_cache(docx(), tmp_path, process=process)
    assert result['fields']['PAF000000'] == '1'
    assert '--profile' in seen[0]
    assert not list(tmp_path.iterdir())
