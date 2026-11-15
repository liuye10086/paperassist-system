"""Versioned statistics presentation over the unchanged R1 renderer."""
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys

from app.adapters.research_report_render import renderer_identity as base_identity
from app.core.exceptions import StorageError

VERSION='statistics_reader_render_v1'


def renderer_identity():
    from .render_labels import labels
    root=Path(__file__).parent
    fixed=b''.join((root/name).read_bytes() for name in ('render.py','render_child.py','render_labels.py'))
    fixed+=json.dumps(labels(),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return dict(renderer_version=VERSION,base=base_identity(),adapter_sha256=hashlib.sha256(fixed).hexdigest())


def frozen_renderer_identity(saved):
    """A historical base snapshot is never upgraded by installing R3."""
    from app.adapters.research_report_render import renderer_identity as current_base
    return renderer_identity() if saved.get('renderer_version')==VERSION else current_base()


def execute_statistics_report(payload,output):
    if sys.platform!='linux':
        raise StorageError('research_environment_unavailable','报告安全生成需要 Linux Worker。',409)
    try:
        result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).with_name('render_child.py'))],
            input=json.dumps(dict(payload=payload,output=str(output))).encode('utf-8'),stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,timeout=305,env={},cwd='/',start_new_session=True,check=False)
        if result.returncode==-signal.SIGALRM:
            raise StorageError('research_render_timeout','报告或打包超过执行时限。',422)
        if result.returncode or len(result.stdout)>2*1024**2:raise ValueError('Invalid statistics report output')
        value=json.loads(result.stdout)
        if value.get('error')=='research_export_limit_exceeded':
            raise StorageError('research_export_limit_exceeded','报告超过容量限制，请减少选材。',422)
        if value['manifest'].get('renderer_identity')!=renderer_identity():raise ValueError('Statistics renderer changed')
        return value
    except subprocess.TimeoutExpired as exc:
        raise StorageError('research_render_timeout','报告或打包超过执行时限。',422) from exc
    except (ValueError,OSError) as exc:
        raise StorageError('research_output_invalid','报告未通过完整性检查，请核对来源。',422) from exc
