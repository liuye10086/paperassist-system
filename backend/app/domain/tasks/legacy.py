"""Stable identities and safe views of original, read-only job records."""
import base64
import binascii
import json
import re

from app.core.exceptions import StorageError
from app.domain.tasks.contracts import TaskView, display_status
from app.domain.tasks.errors import safe_error_code


PREFIXES = {'plot': 'legacy-plot:', 'explanation': 'legacy-explanation:'}


def legacy_id(kind, job_id):
    return PREFIXES[kind] + base64.urlsafe_b64encode(job_id.encode('utf-8')).decode('ascii').rstrip('=')


def is_legacy_id(task_id):
    return task_id.startswith('legacy-')


def missing_task():
    return StorageError('task_not_found', '任务不存在，请刷新后重试。', 404)


def decode_legacy_id(task_id):
    for kind, prefix in PREFIXES.items():
        if task_id.startswith(prefix):
            encoded = task_id[len(prefix):]
            try:
                if not re.fullmatch(r'[A-Za-z0-9_-]+', encoded):
                    raise ValueError('Invalid identity.')
                decoded = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True).decode('utf-8')
                if not decoded or legacy_id(kind, decoded) != task_id:
                    raise ValueError('Noncanonical identity.')
                return kind, decoded
            except (ValueError, UnicodeError, binascii.Error) as exc:
                raise missing_task() from exc
    raise missing_task()


def job_data(row):
    try:
        value = json.loads(row['job_json'])
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def mapped_status(job):
    return {'submitting': 'running', 'running': 'running', 'completed': 'succeeded',
            'failed': 'failed', 'uncertain': 'waiting_confirmation'}.get(job.get('status'), 'failed')


def public_legacy_task(row, artifact=None):
    job = job_data(row)
    status = mapped_status(job)
    phase = 'compute' if row['kind'] == 'plot' else 'interpret'
    error = None
    if status == 'failed':
        error = (safe_error_code(job.get('message_code')) or 'internal_error') if job.get('status') == 'failed' else 'internal_error'
    elif status == 'waiting_confirmation':
        error = 'model_submission_unknown'
    return TaskView(id=legacy_id(row['kind'], row['id']), origin='legacy', project_id=row['project_id'],
        task_type='boxplot' if row['kind'] == 'plot' else 'explanation', status=status, phase=phase,
        display_status=display_status(status, phase), revision=None, current_attempt=None, retry_count=None,
        updated_at=None, created_at=row['created_at'], error_code=error,
        reason_code='submission_unknown' if status == 'waiting_confirmation' else 'execution_failed' if status == 'failed' else None,
        input_version={'setup_revision': row['setup_revision'], 'output_language': 'zh-CN'},
        result_figure_id=artifact['id'] if artifact and row['kind'] == 'plot' else None,
        result_explanation_id=artifact['id'] if artifact and row['kind'] == 'explanation' else None).model_dump(mode='json')


def legacy_source(row):
    return dict(file_id=row['file_id'], filename=row['filename'], analysis_run_id=row['analysis_run_id'],
                is_current=row['current_revision'] == row['setup_revision'])
