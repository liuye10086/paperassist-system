from contextlib import contextmanager
from contextvars import ContextVar
from app.adapters.task_store import source_conflict
from app.adapters.storage import _storage_connection
from app.domain.statistics_execution.service import digest

_VERIFY = ContextVar('statistics_independent_verification', default=False)
_COMPUTE = ContextVar('statistics_worker_compute', default=False)


@contextmanager
def verification_scope():
    token = _VERIFY.set(True)
    try:
        yield
    finally:
        _VERIFY.reset(token)


def should_recompute():
    return _VERIFY.get()


@contextmanager
def computation_scope():
    token = _COMPUTE.set(True)
    try:
        with verification_scope():
            yield
    finally:
        _COMPUTE.reset(token)


def require_worker():
    if not _COMPUTE.get():
        raise source_conflict()


def require_receipt(assets, project_id, file_id, result, *, allow_legacy=True):
    """Validate the persisted result binding without spawning a child."""
    with _storage_connection(config=assets.db_config) as db:
        row = db.execute('''SELECT t.* FROM tasks t
            JOIN projects p ON p.id=t.project_id JOIN users u ON u.id=t.user_id
            WHERE t.task_type='statistics_compute' AND t.status='succeeded'
            AND t.result_analysis_run_id=%s AND t.project_id=%s AND p.owner_id=t.user_id AND u.active
            ORDER BY t.updated_at DESC,t.id DESC LIMIT 1''', (result['id'], project_id)).fetchone()
    if row is None:
        if allow_legacy and result.get('engine',{}).get('execution_contract')!='fixed_statistics_v2':
            return False
        raise source_conflict()
    from app.domain.statistics_execution.service import require_snapshot
    snapshot = require_snapshot(row)
    if (snapshot['setup']['revision']!=result['setup_revision'] or snapshot['setup']['selection']!=result['selection']
            or snapshot['setup'].get('analysis_plan')!=result.get('analysis_plan')):
        raise source_conflict()
    receipt = row['execution_receipt']
    validate_statistics_receipt(receipt)
    if (not receipt or receipt.get('status') != 'succeeded' or receipt.get('result_sha256') != digest(result)
            or row['input_snapshot']['file']['id'] != file_id
            or row['input_snapshot']['setup'].get('source') != result.get('source')):
        raise source_conflict()
    return True


def local_numeric_node(function):
    """Bound one local business node; nested substeps share its earliest deadline."""
    from functools import wraps
    @wraps(function)
    def execute(*args, **kwargs):
        from app.domain.fixed_statistics_runtime import numeric_execution_scope
        with numeric_execution_scope(timeout_seconds=60), verification_scope():
            return function(*args, **kwargs)
    return execute

def validate_statistics_receipt(receipt):
    """Measured fields are nullable on failures/cache hits, never invented on success."""
    import math
    import re
    from app.domain.statistics_execution.service import RESOURCE_CONTRACT
    def number(value):
        return type(value) in (int,float) and math.isfinite(value) and value >= 0
    if (not isinstance(receipt,dict) or type(receipt.get('schema_version')) is not int or receipt['schema_version'] != 1
            or receipt.get('status') not in ('succeeded','failed') or not isinstance(receipt.get('nodes'),list)):
        raise source_conflict()
    succeeded = receipt['status']=='succeeded'
    if succeeded and (not receipt['nodes'] or receipt.get('resource_contract') != RESOURCE_CONTRACT
            or not re.fullmatch(r'[0-9a-f]{64}',receipt.get('result_sha256',''))):
        raise source_conflict()
    for node in receipt['nodes']:
        if (not isinstance(node,dict) or node.get('contract_version')!='fixed_statistics_v2'
                or node.get('sandbox_version')!=RESOURCE_CONTRACT['sandbox_version']
                or type(node.get('cache_hit')) is not bool
                or node.get('isolation')!='linux_landlock_seccomp'
                or node.get('memory_hard_limit')!=1073741824 or node.get('cpu_hard_limit_seconds')!=30
                or node.get('cpu_affinity_count')!=1 or node.get('output_policy')!='bounded_pipe'
                or node.get('stdout_policy')!='bounded_protocol' or node.get('stderr_policy')!='discard'
                or node.get('input_policy')!='frozen_projection' or not number(node.get('elapsed_seconds'))
                or not number(node.get('timeout_seconds')) or not 0 < node['timeout_seconds'] <= 30):
            raise source_conflict()
        if succeeded and (node.get('input_bytes') is None or node.get('output_bytes') is None):
            raise source_conflict()
        if succeeded and node.get('error_code') is not None:
            raise source_conflict()
        for key in ('child_cpu_seconds','child_peak_rss_bytes','input_bytes','output_bytes'):
            value=node.get(key)
            if value is not None and not number(value): raise source_conflict()
        if node['cache_hit']:
            if node.get('child_cpu_seconds') is not None or node.get('child_peak_rss_bytes') is not None:
                raise source_conflict()
        elif succeeded and (node.get('child_cpu_seconds') is None or node.get('child_peak_rss_bytes') is None):
            raise source_conflict()
    return receipt
