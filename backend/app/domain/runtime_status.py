"""Operator-owned runtime files; bounded collection is separate from HTTP admission.

These observations are not a scheduler, a backup-quiescence proof or a model gate.
Only deployment-side trusted processes may write the configured control directory.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_data_dir, local_config
from app.core.errors import error_response
from app.db.database import database_connection, get_database_config

SAMPLE_SECONDS = 15
STALE_SECONDS = 45
FAILURE_WINDOW_SECONDS = 3600
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}
SESSION_WRITES = {('POST', '/api/v1/auth/login'), ('POST', '/api/v1/auth/logout')}
Count = Annotated[int, Field(ge=0, le=2**63-1)]
Identity = Annotated[str, Field(pattern=r'^[0-9a-f-]{36}$')]
Sha = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Envelope(Closed):
    schema_version: Literal[1]
    namespace: Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9_.-]{0,63}$')]
    environment: Literal['development', 'test', 'production']
    database_schema: str


class Maintenance(Envelope):
    mode: Literal['normal', 'maintenance']
    updated_at: str
    retry_after_seconds: Annotated[int, Field(ge=1, le=3600)] = 30


class Health(Closed):
    status: Literal['healthy', 'unavailable', 'unknown']
    observed_at: str | None


class Services(Closed):
    worker: Health
    dispatcher: Health
    broker: Health


class ExternalLimits(Closed):
    observed_at: str
    window_seconds: Annotated[int, Field(ge=1, le=86400)]
    observed_calls: Count
    observed_429: Count
    coverage: Literal['recorded_provider_responses']


class Observations(Envelope):
    observed_at: str
    services: Services
    worker_startup_id: Identity | None
    external_limits: ExternalLimits | None


class Startup(Envelope):
    observed_at: str
    startup_id: Identity
    concurrency: Annotated[int, Field(ge=1, le=2)]
    configuration_id: Identity | None
    configuration_sha256: Sha | None


class Queue(Closed):
    queued_count: Count
    oldest_pending_age_seconds: Annotated[float, Field(ge=0)] | None


class Failures(Closed):
    failed: Count
    denominator: Count
    ratio: Annotated[float, Field(ge=0, le=1)] | None
    window_seconds: Literal[3600]
    window_start: str
    window_end: str
    coverage: Literal['terminal_tasks_updated_in_window']


class Budgets(Closed):
    status: Literal['known', 'unknown']
    registered_user_budgets: Count
    limit_micro_usd: Count | None
    reserved_micro_usd: Count | None
    accounted_micro_usd: Count | None
    coverage: Literal['registered_user_budgets_only_not_global_balance']


class Disk(Closed):
    free_bytes: Count
    total_bytes: Count
    coverage: Literal['data_filesystem_only']


class Receipt(Envelope):
    observed_at: str
    database: Health
    services: Services
    queue: Queue | None
    failures: Failures | None
    budgets: Budgets | None
    disk: Disk | None
    external_limits: ExternalLimits | None
    worker_startup: Startup | None


def now_utc():
    return datetime.now(timezone.utc)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Observation time must include timezone.')
    return parsed.astimezone(timezone.utc)


def fresh(value, now):
    try:
        return -5 <= (now - timestamp(value)).total_seconds() <= STALE_SECONDS
    except (ValueError, TypeError, AttributeError):
        return False


def control_directory():
    value = local_config().get('PAPERASSIST_RUNTIME_CONTROL_DIR')
    return Path(value) if value else None


def binding():
    namespace = local_config().get('PAPERASSIST_RUNTIME_NAMESPACE', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,63}', namespace):
        raise ValueError('Runtime namespace must be explicitly configured.')
    config = get_database_config()
    return dict(schema_version=1, namespace=namespace, environment=config.environment, database_schema=config.schema)


def validate_binding(value):
    if any(value.get(key) != item for key, item in binding().items()):
        raise ValueError('Runtime observation binding mismatch.')


def read_file(name, model):
    directory = control_directory()
    if directory is None:
        return None
    try:
        with (directory/name).open(encoding='utf-8') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            return None
        value = model.model_validate_json(raw).model_dump()
        validate_binding(value)
        return value
    except (OSError, ValueError, TypeError):
        return None


def atomic_write(name, payload):
    directory = control_directory()
    if directory is None:
        raise ValueError('Runtime control directory is not configured.')
    # The deployment owns directory creation and permissions. No arbitrary names.
    if name not in ('status.json', 'worker-startup.json'):
        raise ValueError('Unsupported runtime receipt.')
    temporary = directory/('.'+name+'.'+uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        os.replace(temporary, directory/name)
    finally:
        if temporary.exists():
            temporary.unlink()


def maintenance_state():
    if control_directory() is None:
        return dict(mode='normal', updated_at=None, retry_after_seconds=30)
    value = read_file('maintenance.json', Maintenance)
    if value:
        try:
            timestamp(value['updated_at'])
            return value
        except ValueError:
            pass
    return dict(mode='unknown', updated_at=None, retry_after_seconds=30)


def admission_error(method, path):
    if not path.startswith('/api/') or method in SAFE_METHODS or (method, path.rstrip('/')) in SESSION_WRITES:
        return None
    state = maintenance_state()
    if state['mode'] == 'normal':
        return None
    maintenance = state['mode'] == 'maintenance'
    return error_response(503, 'service_maintenance' if maintenance else 'service_unavailable',
        '系统维护中，暂不接受新的修改或任务，请稍后重试。' if maintenance else '运行状态暂不可确认，请稍后重试。',
        headers={'Retry-After':str(state['retry_after_seconds'])})


def record_worker_startup(startup):
    if control_directory() is not None:
        payload = dict(binding(), observed_at=now_utc().isoformat(), **startup)
        atomic_write('worker-startup.json', Startup.model_validate(payload).model_dump())


def historical_timestamp(value, now):
    try:
        return value if timestamp(value) <= now else None
    except (ValueError, TypeError, AttributeError):
        return None


def observed_services(services, now):
    return {name: value if fresh(value['observed_at'], now) else dict(status='unknown', observed_at=historical_timestamp(value['observed_at'], now))
            for name, value in services.items()}


def recorded_provider_limits(db, now):
    """Counts only saved DOI/PMC HTTP responses by receipt time, not all providers."""
    start = now-timedelta(seconds=FAILURE_WINDOW_SECONDS)
    row = db.execute("""SELECT count(*) AS n,count(*) FILTER(WHERE http_status=429) AS limited
        FROM (
            SELECT CASE WHEN jsonb_typeof(snapshot_json#>'{result,http_status}')='number'
                AND snapshot_json#>>'{result,http_status}' ~ '^[0-9]{3}$'
                THEN (snapshot_json#>>'{result,http_status}')::integer END AS http_status
            FROM literature_check_receipts
            WHERE kind='doi_resolution' AND source_kind<>'synthetic_fixture'
                AND snapshot_json#>>'{result,execution_kind}'='doi_org'
                AND snapshot_json#>'{result,network_attempted}'='true'::jsonb
                AND created_at >= %s AND created_at <= %s
            UNION ALL
            SELECT CASE WHEN jsonb_typeof(response->'http_status')='number'
                AND response->>'http_status' ~ '^[0-9]{3}$'
                THEN (response->>'http_status')::integer END AS http_status
            FROM literature_pmc_receipts r
            CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(r.snapshot_json->'responses')='array'
                THEN r.snapshot_json->'responses' ELSE '[]'::jsonb END) response
            WHERE r.source_kind='pmc_oai' AND r.created_at >= %s AND r.created_at <= %s
        ) responses WHERE http_status BETWEEN 100 AND 599""", (start, now, start, now)).fetchone()
    if not row['n']:
        return None
    return dict(observed_at=now.isoformat(),window_seconds=FAILURE_WINDOW_SECONDS,
        observed_calls=row['n'],observed_429=row['limited'],coverage='recorded_provider_responses')


def collect(observation, *, now=None):
    """One bounded read pass; external probes are supplied by trusted orchestration."""
    now = now or now_utc()
    observation = Observations.model_validate(observation).model_dump()
    validate_binding(observation)
    if not fresh(observation['observed_at'], now):
        raise ValueError('Observation input is stale.')
    services = observed_services(observation['services'], now)
    limits = observation['external_limits']
    queue = failures = budgets = disk = None
    database = dict(status='unknown', observed_at=None)
    try:
        with database_connection(capture=True) as db:
            row = db.execute("SELECT count(*) AS n,min(created_at) AS oldest FROM tasks WHERE status='queued'").fetchone()
            queue = dict(queued_count=row['n'], oldest_pending_age_seconds=max(0., (now-row['oldest']).total_seconds()) if row['oldest'] else None)
            start = now-timedelta(seconds=FAILURE_WINDOW_SECONDS)
            row = db.execute("""SELECT count(*) AS n,count(*) FILTER(WHERE status='failed') AS failed
                FROM tasks WHERE status IN ('failed','succeeded') AND updated_at >= %s AND updated_at <= %s""", (start, now)).fetchone()
            failures = dict(failed=row['failed'], denominator=row['n'],ratio=row['failed']/row['n'] if row['n'] else None,
                window_seconds=FAILURE_WINDOW_SECONDS,window_start=start.isoformat(),window_end=now.isoformat(),coverage='terminal_tasks_updated_in_window')
            row = db.execute("""SELECT count(*) AS n,sum(limit_micro_usd) AS amount FROM model_budgets WHERE scope_type='user'""").fetchone()
            from app.domain.model_usage.accounting import accounting_projection
            reservations = db.execute("""SELECT c.status,c.usage_status,c.estimated_cost_micro_usd,c.policy_snapshot,
                c.actual_token_micro_usd,c.actual_tool_micro_usd,r.reserved_micro_usd,r.accounted_micro_usd,
                r.status AS reservation_status FROM budget_reservations r JOIN model_budgets b ON b.id=r.budget_id
                JOIN model_calls c ON c.id=r.call_id WHERE b.scope_type='user'""").fetchall()
            accounted = reserved = 0
            for reservation in reservations:
                call = dict(reservation)
                used, held = accounting_projection(call, {**call, 'status':call['reservation_status']})
                accounted += used
                reserved += held
            budgets = dict(status='known' if row['n'] else 'unknown',registered_user_budgets=row['n'],
                limit_micro_usd=int(row['amount']) if row['n'] else None,
                reserved_micro_usd=reserved if row['n'] else None,
                accounted_micro_usd=accounted if row['n'] else None,
                coverage='registered_user_budgets_only_not_global_balance')
            limits = recorded_provider_limits(db, now) or limits
        database = dict(status='healthy', observed_at=now.isoformat())
    except Exception:
        # No logging here: collection must not recursively invoke request telemetry.
        queue = failures = budgets = None
        database = dict(status='unavailable', observed_at=now.isoformat())
    try:
        usage = shutil.disk_usage(get_data_dir())
        disk = dict(free_bytes=usage.free, total_bytes=usage.total, coverage='data_filesystem_only')
    except OSError:
        pass
    startup = read_file('worker-startup.json', Startup)
    if (not startup or services['worker']['status'] != 'healthy'
            or startup['startup_id'] != observation['worker_startup_id']):
        startup = None
    if limits and (not fresh(limits['observed_at'], now) or limits['observed_429'] > limits['observed_calls']):
        limits = None
    receipt = dict(binding(), observed_at=now.isoformat(), database=database, services=services,
        queue=queue, failures=failures, budgets=budgets, disk=disk, external_limits=limits,worker_startup=startup)
    return Receipt.model_validate(receipt).model_dump()


def write_status(receipt):
    receipt = Receipt.model_validate(receipt).model_dump()
    validate_binding(receipt)
    atomic_write('status.json', receipt)


def current_receipt(*, include_stale=False):
    value = read_file('status.json', Receipt)
    now = now_utc()
    if not value:
        return None
    if not fresh(value['observed_at'], now):
        if not include_stale or historical_timestamp(value['observed_at'], now) is None:
            return None
        value['database'] = dict(status='unknown', observed_at=historical_timestamp(value['database']['observed_at'], now))
        value['services'] = {name:dict(status='unknown', observed_at=historical_timestamp(item['observed_at'], now))
            for name,item in value['services'].items()}
        value.update(queue=None, failures=None, budgets=None, disk=None, external_limits=None, worker_startup=None)
        return value
    if not fresh(value['database']['observed_at'], now_utc()):
        value['database'] = dict(status='unknown', observed_at=historical_timestamp(value['database']['observed_at'], now))
    if value['database']['status'] != 'healthy':
        value.update(queue=None, failures=None, budgets=None)
    if value['external_limits'] and not fresh(value['external_limits']['observed_at'], now_utc()):
        value['external_limits'] = None
    return value


def public_status():
    state = maintenance_state()
    if state['mode'] == 'unknown':
        return dict(status='service_unavailable',reason='runtime_control_unknown',observed_at=None)
    if state['mode'] == 'maintenance':
        return dict(status='maintenance',reason='operator_maintenance',observed_at=state['updated_at'])
    if control_directory() is None:
        return dict(status='normal',reason='runtime_control_not_configured',observed_at=None)
    receipt = current_receipt()
    if not receipt:
        return dict(status='service_unavailable',reason='runtime_observation_unknown',observed_at=None)
    available = (receipt['database']['status'] == 'healthy'
        and fresh(receipt['database']['observed_at'], now_utc())
        and all(v['status']=='healthy' for v in observed_services(receipt['services'],now_utc()).values()))
    return dict(status='normal' if available else 'service_unavailable',
        reason='observed_available' if available else 'service_observation_unavailable',observed_at=receipt['observed_at'])


def admin_status(db):
    from app.domain.admin_configuration.bindings import current
    from app.workers.config import concurrency_ceiling
    receipt = current_receipt(include_stale=True)
    version = current(db)
    desired = version['bundle']['basic'].get('worker_concurrency',1) if version else 1
    services = observed_services(receipt['services'],now_utc()) if receipt else {
        name:dict(status='unknown',observed_at=None) for name in ('worker','dispatcher','broker')}
    startup = receipt['worker_startup'] if receipt and services['worker']['status']=='healthy' else None
    effective = startup['concurrency'] if startup else None
    return dict(**public_status(),coverage=dict(status='observed' if receipt and fresh(receipt['observed_at'],now_utc()) else 'unknown',
        observed_at=receipt['observed_at'] if receipt else None,sample_seconds=SAMPLE_SECONDS,stale_after_seconds=STALE_SECONDS,
        historical_missing_is_zero=False),services=services,
        database=receipt['database'] if receipt else dict(status='unknown',observed_at=None),
        **{field:receipt[field] if receipt else None for field in ('queue','failures','budgets','disk','external_limits')},
        concurrency=dict(desired=desired,effective=effective,deployment_ceiling=concurrency_ceiling(),
            pending_restart=(desired!=effective or (startup['configuration_sha256'] if startup else None)!=(version['sha256'] if version else None)) if effective is not None else None,
            desired_configuration_id=version['id'] if version else None,desired_configuration_sha256=version['sha256'] if version else None,
            effective_configuration_id=startup['configuration_id'] if startup else None,
            effective_configuration_sha256=startup['configuration_sha256'] if startup else None))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Collect one safe runtime observation receipt')
    parser.add_argument('--observations', required=True)
    args = parser.parse_args(argv)
    try:
        with Path(args.observations).open(encoding='utf-8') as stream:
            raw = stream.read(65537)
        if len(raw)>65536:
            raise ValueError('Observation input exceeds limit.')
        write_status(collect(json.loads(raw)))
        return 0
    except Exception:
        print('Runtime observation collection unavailable.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
