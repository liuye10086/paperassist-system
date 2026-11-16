"""Resolve exact frozen report identities for execution and recovery."""

from functools import partial
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory

from app.adapters.research_results_store import invalid
from app.core.exceptions import StorageError


# Keep the seven hashed files from 3932384 together. Its renderer hashed raw
# checkout bytes, so already-frozen tasks can carry either line ending digest.
_LEGACY_ROOT = Path(__file__).parents[2] / 'adapters/research_report_legacy_3932384'
_LEGACY_FILES = tuple(f'app/adapters/{name}.py' for name in (
    'research_report_render', 'research_report_child', 'research_report_docx',
    'research_results_xlsx', 'research_report_images', 'research_method_text',
)) + ('app/domain/research_results/report_package.py',)
_LEGACY_LINE_ENDINGS = {
    '95be3a1cab17f7cacc22761ec38212caf772c32e93a0ad715d2ceaa20a9fcfa2': b'\n',
    '9b2e8022d84d8532925b898af0f6e1f4f26eaa10df55b4c1c03a29f8952b3091': b'\r\n',
}


def is_legacy_renderer(saved):
    return (isinstance(saved, dict) and saved.get('renderer_version') == 'research_report_v1'
            and isinstance(saved.get('code_digest'), str) and saved['code_digest'] in _LEGACY_LINE_ENDINGS)


def frozen_report_renderer(saved):
    from app.adapters.research_report_render import execute_research_report
    from app.domain.statistics_reader_reports.render import VERSION, execute_statistics_report, frozen_renderer_identity

    if is_legacy_renderer(saved):
        code_digest = saved['code_digest']
        expected = dict(renderer_version='research_report_v1', code_digest=code_digest,
                        dependencies={name: version(name) for name in ('python-docx', 'openpyxl', 'Pillow', 'pdfplumber')},
                        limits=dict(render_seconds=120, package_seconds=180, subprocess_memory_bytes=2 * 1024**3))
        if saved != expected:
            raise invalid()
        eol = _LEGACY_LINE_ENDINGS[code_digest]
        try:
            sources = {name: (_LEGACY_ROOT / name).read_bytes().replace(b'\r\n', b'\n').replace(b'\n', eol)
                       for name in _LEGACY_FILES}
        except OSError as exc:
            raise invalid() from exc
        if hashlib.sha256(b''.join(sources.values())).hexdigest() != code_digest:
            raise invalid()
        return partial(_execute_legacy_report, saved, sources)
    if not isinstance(saved, dict) or saved != frozen_renderer_identity(saved):
        raise invalid()
    return execute_statistics_report if saved['renderer_version'] == VERSION else execute_research_report


def _execute_legacy_report(saved, sources, payload, output):
    if sys.platform != 'linux':
        raise StorageError('research_environment_unavailable', '报告安全生成需要 Linux Worker。', 409)
    try:
        with TemporaryDirectory(dir=Path(output).parent, prefix='report-renderer-') as directory:
            root = Path(directory)
            for name, raw in sources.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            # Ensure the child imports this historical package tree even when
            # the current app is installed in the worker's Python environment.
            for name in ('app', 'app/adapters', 'app/domain', 'app/domain/research_results'):
                (root / name / '__init__.py').touch()
            result = subprocess.run(
                [sys.executable, '-I', '-B', str(root / 'app/adapters/research_report_child.py')],
                input=json.dumps(dict(payload=payload, output=str(output))).encode('utf-8'),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=305, env={}, cwd='/',
                start_new_session=True, check=False,
            )
        if result.returncode == -signal.SIGALRM:
            raise StorageError('research_render_timeout', '报告或打包超过执行时限。', 422)
        if result.returncode or len(result.stdout) > 2 * 1024**2:
            raise ValueError('Invalid report output')
        value = json.loads(result.stdout)
        if value.get('error') == 'research_export_limit_exceeded':
            raise StorageError('research_export_limit_exceeded', '报告超过单元格、文件数或容量限制，请减少选定结果或拆分报告。', 422)
        if value['manifest']['renderer_identity'] != saved:
            raise ValueError('Legacy report renderer changed')
        return value
    except subprocess.TimeoutExpired as exc:
        raise StorageError('research_render_timeout', '报告或打包超过执行时限。', 422) from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StorageError('research_output_invalid', '报告未通过完整性检查，请减少数据范围或核对来源。', 422) from exc
