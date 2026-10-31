"""Explicit B04 synthetic-only quota fault/recovery engineering experiment.

Default is offline preparation; no service lifecycle actions. Run creation must
precede quota=0 because its execution snapshot also uses quota accounting. A
race or a failure at the wrong stage is retained as an incomplete experiment,
never relabelled as a successful fault/recovery test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'script/dev'), str(ROOT / 'backend')]
from cr_b04_downstream import Ledger, digest, literal_rows

GSE_PROJECT = 'e8ba52c6-0e85-42ac-8205-dd70f1851f03'
ACTIVE = ('queued', 'running', 'waiting_input', 'waiting_confirmation')


def eligible_target(project_id, name):
    normalized = name.casefold()
    return project_id != GSE_PROJECT and ('synthetic' in normalized or '合成' in name) and 'gse' not in normalized and '262082' not in normalized


def require_quiet(tasks, own_task=None):
    if any(t['status'] in ACTIVE and t['id'] != own_task for t in tasks):
        raise ValueError('An unrelated task is active in this project; no quota fault is permitted')


def restore_decision(before, current, applied_revision):
    """Never overwrite a foreign policy revision, even if it looks similar."""
    if current['limit_bytes'] == before['limit_bytes'] and current['mode'] == before['mode']:
        return 'already_original'
    if current['revision'] == applied_revision and current['limit_bytes'] == 0 and current['mode'] == 'enforced':
        return 'restore_owned_zero'
    raise ValueError('Policy changed outside this experiment; exact restoration needs operator reconciliation')


def require_admission_failure(task, checkpoint):
    if task['status'] != 'failed' or task['error_code'] != 'storage_quota_exceeded' or task['current_attempt'] != 1:
        raise AssertionError('Attempt 1 did not fail with the intended quota refusal')
    if checkpoint['next_node'] != 'check' or 'prepared' in checkpoint['state_json']:
        raise AssertionError('Failure was not before the persisted prepared checkpoint; do not claim the expected admission failure')
    if task.get('result_bio_insight_result_version_id'):
        raise AssertionError('Failed task already has a published result')


def hash_file(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def strict_json_value(value):
    """JSON object order is immaterial; bool/int/float types are not."""
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AssertionError('Invalid non-JSON provenance value') from exc


def read_strict_provenance(raw):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AssertionError('Duplicate provenance JSON key: ' + key)
            result[key] = value
        return result
    def reject_constant(value):
        raise AssertionError('Non-finite provenance JSON constant: ' + value)
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise AssertionError('Provenance must be a JSON object')
    return value


def verify_recovered_table(source, recovered, original_raw, recovered_raw):
    """Compare literal source values; bind each embedded run/task to its result.

    A newly created recovery run legitimately changes only these two provenance
    identity fields. It must not change raw values, row keys, source metadata or
    the frozen plan/code/environment identity. Each download has its own SHA.
    """
    allowed = ('run_id', 'task_id')
    tables, fixed_identities = [], []
    for result, raw in ((source, original_raw), (recovered, recovered_raw)):
        if result['kind'] != 'result_import' or result['provenance'] != 'external_result' or result['inference_scope'] != 'external_result':
            raise AssertionError('Recovery result is not the same external import kind')
        member = next(m for m in result['members'] if m['key'] == 'comparison_results')
        if member['format'] != 'tsv' or len(raw) != member['size_bytes'] or hashlib.sha256(raw).hexdigest() != member['sha256']:
            raise AssertionError('External result download differs from its own published member SHA/size')
        identity = result['manifest']['identity']
        if any(strict_json_value(identity.get(k)) != strict_json_value(result[k]) for k in ('run_id', 'task_id', 'plan_version_id')) or strict_json_value(identity.get('task_id')) != strict_json_value(result['task']['id']) or strict_json_value(identity.get('project_id')) != strict_json_value(result['task']['project_id']):
            raise AssertionError('Published result and execution identity binding differ')
        fixed_identities.append(strict_json_value({k: v for k, v in identity.items() if k not in allowed}))
        columns, rows = literal_rows(raw, 'tsv')
        if 'provenance' not in columns:
            raise AssertionError('External result table has no provenance binding')
        position = columns.index('provenance')
        normalized = []
        for row in rows:
            provenance = read_strict_provenance(row[position])
            if strict_json_value(provenance.get('identity')) != strict_json_value(identity):
                raise AssertionError('Row execution identity differs from its published result')
            provenance['identity'] = {k: v for k, v in identity.items() if k not in allowed}
            normalized.append((row[:position] + row[position + 1:], strict_json_value(provenance)))
        tables.append((columns, normalized))
    if fixed_identities[0] != fixed_identities[1]:
        raise AssertionError('Frozen plan/source/code/environment identity changed')
    if tables[0] != tables[1]:
        raise AssertionError('Recovered literal values, row keys or source provenance changed')
    return dict(row_count=len(tables[0][1]), column_count=len(tables[0][0]),
        allowed_identity_fields=list(allowed), raw_cells_exact=True, source_provenance_exact=True,
        each_member_sha_verified=True, execution_identity_bound_to_each_result=True,
        json_types_preserved=True, duplicate_json_keys_rejected=True,
        comparison='literal cells and type-strict canonical provenance JSON; only bound run_id/task_id may differ')


class Experiment:
    def __init__(self, args, state, output):
        import httpx
        self.args, self.state, self.output = args, state, output
        identity = dict(schema=state['schema'], project_id=args.project_id, original_result_id=args.result_id, experiment='quota_admission_then_same_task_retry')
        self.ledger = Ledger(output / 'receipt.json', identity, args.retry_original)
        self.record = self.ledger.record
        credential = json.loads((Path(state['assets']).parent / 'credentials.json').read_text(encoding='utf-8-sig'))['review']
        self.owner = credential['id']
        self.base = '/api/v1/projects/' + args.project_id
        self.client = None
        if args.restore_only:
            if not self.record.get('original_policy') or not self.record.get('experiment_token'):
                raise ValueError('Restore-only requires the existing exact experiment receipt; no policy baseline is guessed')
        else:
            self.client = httpx.Client(base_url=state['url'], timeout=600, trust_env=False,
                headers={'Origin': state['url'], 'X-PaperAssist-Client': 'web'})
            value = self.check(self.client.post('/api/v1/auth/login', json={k: credential[k] for k in ('email', 'password')})).json()
            self.client.headers['X-CSRF-Token'] = value['csrf_token']
        self.token = self.record.setdefault('experiment_token', uuid4().hex)
        self.reason_zero = 'CR-B04 synthetic-only recovery quota=0; experiment=' + self.token
        self.reason_restore = 'CR-B04 restore exact original quota/mode; experiment=' + self.token
        self.ledger.save()

    @staticmethod
    def check(response):
        if response.status_code not in (200, 201, 202):
            try:
                detail = response.json().get('detail', {})
                code = detail.get('code', 'invalid_request') if isinstance(detail, dict) else 'invalid_request'
            except ValueError:
                code = 'unexpected_response'
            raise RuntimeError(f'HTTP {response.status_code}: {code}')
        return response

    def get(self, path):
        return self.check(self.client.get(path)).json()

    def assert_scope(self, db):
        if db.config.environment != 'test' or db.config.schema != self.state['schema'] or db.config.url.database != 'paperassist_system_test':
            raise ValueError('Refusing a non-B04-copy database')
        row = db.execute('SELECT id,name,owner_id FROM projects WHERE id=%s', (self.args.project_id,)).fetchone()
        if not row or row['owner_id'] != self.owner or not eligible_target(row['id'], row['name']):
            raise ValueError('Only the explicitly owned synthetic project is allowed; GSE and real projects are protected')
        return dict(row)

    def policy(self, db):
        row = db.execute("SELECT scope_type,scope_id,limit_bytes,mode,revision FROM storage_policies WHERE scope_type='project' AND scope_id=%s", (self.args.project_id,)).fetchone()
        if not row:
            raise ValueError('A pre-existing explicit project policy is required; do not create a policy that cannot be restored to absence')
        return dict(row)

    def tasks(self, db):
        return [dict(r) for r in db.execute('SELECT id,status,revision,task_type FROM tasks WHERE project_id=%s', (self.args.project_id,))]

    def policy_event(self, db, reason):
        rows = list(db.execute("SELECT id,revision,reason,before_limit_bytes,after_limit_bytes,before_mode,after_mode,actor_user_id FROM storage_policy_events WHERE scope_type='project' AND scope_id=%s AND reason=%s ORDER BY revision", (self.args.project_id, reason)))
        if len(rows) > 1:
            raise ValueError('Duplicate policy mutation under one experiment identity')
        return dict(rows[0]) if rows else None

    def protected_objects(self):
        from app.db.database import database_connection
        with database_connection() as db:
            self.assert_scope(db)
            rows = [dict(r) for r in db.execute("SELECT DISTINCT o.object_key,o.sha256,o.size_bytes,o.state FROM storage_objects o JOIN storage_references r ON r.object_id=o.id WHERE r.project_id=%s AND o.state<>'deleted'", (self.args.project_id,))]
            gse = db.execute("SELECT limit_bytes,mode,revision FROM storage_policies WHERE scope_type='project' AND scope_id=%s", (GSE_PROJECT,)).fetchone()
        assets = Path(self.state['assets']).resolve()
        checked = {}
        for row in rows:
            path = assets / row['object_key']
            if path.is_symlink() or not path.resolve().is_relative_to(assets) or not path.is_file():
                raise ValueError('Protected source object is not a regular in-scope file')
            if path.stat().st_size != row['size_bytes'] or hash_file(path) != row['sha256']:
                raise ValueError('Protected original object differs before the experiment')
            checked[row['object_key']] = {'sha256': row['sha256'], 'size_bytes': row['size_bytes']}
        return dict(target_project_objects=checked, gse_policy=dict(gse) if gse else None)

    def verify_protected(self):
        original = self.record['protected_before']
        actual = self.protected_objects()
        if actual['gse_policy'] != original['gse_policy']:
            raise AssertionError('GSE project policy changed; this experiment never authorizes that mutation')
        for key, value in original['target_project_objects'].items():
            if actual['target_project_objects'].get(key) != value:
                raise AssertionError('A protected target-project original changed: ' + key)
        self.record['protected_target_assets_unchanged'] = True
        self.record['gse_policy_unchanged'] = True

    def preflight(self):
        from app.db.database import database_connection
        known = self.record.get('run') or self.record['actions'].get('create-run', {}).get('response')
        pending = self.record['actions'].get('create-run')
        if not known and pending:
            response = self.client.get(self.base + '/bio-insight-requests/' + pending['key'], params={'kind': 'run'})
            if response.status_code != 404:
                known = self.check(response).json()
        if known:
            self.record['run'] = known
            self.ledger.save()
        with database_connection() as db:
            project = self.assert_scope(db)
            require_quiet(self.tasks(db), known['task_id'] if known else None)
            current = self.policy(db)
            if 'original_policy' not in self.record and current['mode'] == 'enforced' and current['limit_bytes'] == 0:
                raise ValueError('Original quota is already zero; this is not a controlled new fault')
        source = self.get(self.base + '/bio-insight-results/' + self.args.result_id)
        if source['kind'] != 'result_import' or source['provenance'] != 'external_result' or source['task']['status'] != 'succeeded':
            raise ValueError('Use the actual successful synthetic-external-a import result, not a comparison or real-data result')
        source_run = self.get(self.base + '/bio-insight-runs/' + source['run_id'])
        plan = self.get(self.base + '/bio-insight-plans/' + source_run['plan_id'] + '/versions/' + source['plan_version_id'])
        if plan['kind'] != 'result_import' or plan['decision'] != 'confirmed' or 'synthetic-external-a' not in plan['name'].casefold():
            raise ValueError('Only the explicitly confirmed synthetic-external-a result plan is allowed')
        # Check the real public resume model before temporarily changing quota.
        from app.domain.tasks.wait_contracts import ResumeRequest
        ResumeRequest.model_validate(dict(operation='retry', wait_id=None, expected_task_revision=1, input_version=source['task']['input_version']))
        self.record.setdefault('original_policy', current)
        self.record.setdefault('source_identity', dict(result_id=source['id'], manifest_sha256=source['manifest_sha256'],
            plan_id=plan['plan_id'], plan_version_id=plan['id'], source_digest=plan['source_digest'], project_name=project['name']))
        if self.record['source_identity']['manifest_sha256'] != source['manifest_sha256'] or self.record['source_identity']['plan_version_id'] != plan['id']:
            raise ValueError('Original synthetic result/plan changed')
        if 'protected_before' not in self.record:
            self.record['protected_before'] = self.protected_objects()
        self.ledger.save()
        return source, plan

    def create_run(self, plan):
        old = self.record['actions'].get('create-run')
        body = old['body'] if old else dict(plan_version_id=plan['id'], expected_plan_revision=plan['current_revision'], source_digest=plan['source_digest'])
        path = self.base + '/bio-insight-runs'
        def recover(entry):
            response = self.client.get(self.base + '/bio-insight-requests/' + entry['key'], params={'kind': 'run'})
            return None if response.status_code == 404 else self.check(response).json()
        value = self.ledger.post('create-run', path, body,
            lambda e: self.check(self.client.post(path, json=e['body'], headers={'Idempotency-Key': e['key']})).json(), recover)
        self.record['run'] = value
        self.ledger.save()
        return value

    def set_zero(self, task_id):
        from app.db.database import database_connection
        from app.domain.storage_governance.service import set_policy
        self.record['zero_policy_intent'] = dict(reason=self.reason_zero, limit_bytes=0, mode='enforced', expected_revision=self.record['original_policy']['revision'])
        self.ledger.save()
        with database_connection(write=True) as db:
            self.assert_scope(db)
            require_quiet(self.tasks(db), task_id)
            event = self.policy_event(db, self.reason_zero)
            if event:
                raise ValueError('Quota fault already applied once; do not re-inject it')
            task = db.execute('SELECT status,current_attempt FROM tasks WHERE id=%s AND project_id=%s', (task_id, self.args.project_id)).fetchone()
            if not task or task['status'] not in ('queued', 'running') or task['current_attempt'] > 1:
                raise RuntimeError('Run completed or moved before quota injection; race retained, no fabricated fault')
            # Trusted local CLI audit actor is NULL; never impersonate an admin.
            value = set_policy(db, 'project', self.args.project_id, 0, 'enforced',
                expected_revision=self.record['original_policy']['revision'], actor_user_id=None, reason=self.reason_zero)
        self.record['zero_policy'] = value
        self.ledger.save()

    def restore(self):
        if 'original_policy' not in self.record:
            return
        from app.db.database import database_connection
        from app.domain.storage_governance.service import set_policy
        before = self.record['original_policy']
        last_error = None
        for _ in range(3):
            try:
                with database_connection(write=True) as db:
                    self.assert_scope(db)
                    current, event = self.policy(db), self.policy_event(db, self.reason_zero)
                    restored = self.policy_event(db, self.reason_restore)
                    if not event:
                        if current['limit_bytes'] != before['limit_bytes'] or current['mode'] != before['mode'] or current['revision'] != before['revision']:
                            raise ValueError('No owned zero event but original policy differs; no blind policy overwrite')
                        value = current
                        status = 'fault_not_applied_original_unchanged'
                    else:
                        decision = restore_decision(before, current, event['revision'])
                        if decision == 'restore_owned_zero':
                            value = set_policy(db, 'project', self.args.project_id, before['limit_bytes'], before['mode'],
                                expected_revision=current['revision'], actor_user_id=None, reason=self.reason_restore)
                            status = 'restored_exact_original'
                        else:
                            value, status = current, self.record.get('restoration', {}).get('status', 'already_original')
                        if restored and (restored['after_limit_bytes'] != before['limit_bytes'] or restored['after_mode'] != before['mode']):
                            raise ValueError('Restoration audit differs')
                    audits = dict(apply=self.policy_event(db, self.reason_zero), restore=self.policy_event(db, self.reason_restore))
                self.record['restoration'] = dict(status=status, policy=value, original_limit_bytes=before['limit_bytes'], original_mode=before['mode'])
                self.record['policy_audit_events'] = audits
                self.ledger.save()
                return
            except Exception as exc:
                last_error = exc
                time.sleep(1)
        self.record['restoration'] = dict(status='requires_exact_operator_reconciliation', error_type=type(last_error).__name__)
        self.ledger.save()
        raise RuntimeError('Could not verify exact original quota restoration; stop and inspect this receipt') from last_error

    def wait_terminal(self, task_id):
        from app.db.database import database_connection
        started, prior = time.monotonic(), None
        while time.monotonic() - started < self.args.wait_seconds:
            with database_connection() as db:
                self.assert_scope(db)
                require_quiet(self.tasks(db), task_id)
            task = self.get('/api/v1/tasks/' + task_id)
            if task['status'] != prior:
                print(json.dumps(dict(task_id=task_id, status=task['status'], attempt=task['current_attempt'])), flush=True)
                prior = task['status']
            if task['status'] in ('failed', 'succeeded'):
                return task
            if task['status'] not in ('queued', 'running'):
                raise RuntimeError('Unexpected waiting state; no task transition attempted')
            time.sleep(3)
        raise RuntimeError('Bounded observation timed out; original task and quota restoration evidence retained')

    def attempts_and_checkpoint(self, task_id):
        from app.db.database import database_connection
        with database_connection() as db:
            self.assert_scope(db)
            attempts = [dict(r) for r in db.execute('SELECT attempt_no,status,reason_code,error_code,error_category,retry_reason,started_at,finished_at FROM task_attempts WHERE task_id=%s ORDER BY attempt_no', (task_id,))]
            checkpoint = db.execute('SELECT id,next_node,state_json FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1', (task_id,)).fetchone()
            events = [dict(r) for r in db.execute('SELECT seq,event_type,task_revision,status,error_code,retry_reason FROM task_events WHERE task_id=%s ORDER BY seq', (task_id,))]
        return dict(attempts=attempts, checkpoint=dict(checkpoint), events=events)

    def capture_failed_staging(self, task_id):
        root = (Path(self.state['staging']) / task_id).resolve()
        for _ in range(20):
            directories = list(root.glob('1-*')) if root.is_dir() else []
            if len(directories) == 1:
                receipt = directories[0] / 'receipt.json'
                if receipt.is_file() and 'failed' in json.loads(receipt.read_text(encoding='utf-8'))['status']:
                    files = {}
                    for path in directories[0].rglob('*'):
                        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                            raise ValueError('Attempt staging must not contain links')
                        if path.is_file():
                            files[path.relative_to(root).as_posix()] = dict(size_bytes=path.stat().st_size, sha256=hash_file(path))
                    if not files or not any('/output/' in key for key in files):
                        raise AssertionError('No real computed output was retained for failed attempt 1')
                    return files
            time.sleep(1)
        raise RuntimeError('Worker failure receipt is not yet durable; do not claim retained attempt material')

    def retry_public(self, failed):
        task_id = failed['id']
        from app.db.database import database_connection
        with database_connection() as db:
            self.assert_scope(db)
            require_quiet(self.tasks(db), task_id)
        path = '/api/v1/tasks/' + task_id + '/resume'
        existing = self.record['actions'].get('retry-task')
        body = existing['body'] if existing else dict(operation='retry', wait_id=None,
            expected_task_revision=failed['revision'], input_version=failed['input_version'])
        def recover(entry):
            # Required public read first, then exact durable key lookup; no
            # guessing acceptance from a different actor's higher revision.
            current = self.get('/api/v1/tasks/' + task_id)
            from app.db.database import database_connection
            with database_connection() as db:
                self.assert_scope(db)
                row = db.execute('SELECT response_json FROM task_resume_requests WHERE task_id=%s AND user_id=%s AND idempotency_key=%s', (task_id, self.owner, entry['key'])).fetchone()
            if row:
                return row['response_json']
            if current['revision'] != entry['body']['expected_task_revision'] or current['status'] != 'failed':
                raise RuntimeError('Task changed without this retry key; no blind replay')
            return None
        return self.ledger.post('retry-task', path, body,
            lambda e: self.check(self.client.post(path, json=e['body'], headers={'Idempotency-Key': e['key']})).json(), recover)

    def run(self):
        if self.args.restore_only:
            self.restore()
            return
        source, plan = self.preflight()
        if self.record.get('status') == 'controlled_recovery_passed':
            self.restore()
            self.verify_protected()
            self.ledger.save()
            return
        run = self.create_run(plan)
        task_id = run['task_id']
        failure = self.record.get('attempt1_failure')
        if not failure:
            try:
                # Never apply a second fault after an interrupted observation.
                if self.record.get('zero_policy_intent'):
                    observed = self.get('/api/v1/tasks/' + task_id)
                else:
                    self.set_zero(task_id)
                    observed = self.wait_terminal(task_id)
                proof = self.attempts_and_checkpoint(task_id)
                require_admission_failure(observed, proof['checkpoint'])
                if len(proof['attempts']) != 1 or proof['attempts'][0]['status'] != 'failed':
                    raise AssertionError('Expected exactly one real failed attempt before retry')
                files = self.capture_failed_staging(task_id)
                self.record.update(attempt1_failure=observed, attempt1_proof=proof, attempt1_staging_files=files,
                    recovery_boundary='quota admission refused before prepared checkpoint; public retry may recompute and no no-recomputation claim is made')
                self.ledger.save()
                failure = observed
            finally:
                self.restore()
        else:
            self.restore()
        workspace = self.get('/api/v1/tasks/' + task_id + '/workspace')
        if not self.record['actions'].get('retry-task') and 'retry' not in workspace['allowed_actions']:
            raise RuntimeError('Public task does not allow retry after restoration; keep original task and investigate')
        self.retry_public(failure)
        completed = self.wait_terminal(task_id)
        if completed['id'] != task_id or completed['status'] != 'succeeded' or completed['current_attempt'] != 2:
            raise AssertionError('Expected the same task to succeed on exactly attempt 2')
        final_run = self.get(self.base + '/bio-insight-runs/' + run['id'])
        if final_run['id'] != run['id'] or final_run['task_id'] != task_id or not final_run['result_version_id']:
            raise AssertionError('Recovery created a different run/task or no formal result')
        result = self.get(self.base + '/bio-insight-results/' + final_run['result_version_id'])
        original_table = next(m for m in source['members'] if m['key'] == 'comparison_results')
        recovered_table = next(m for m in result['members'] if m['key'] == 'comparison_results')
        original_raw = self.check(self.client.get(original_table['download_url'])).content
        recovered_raw = self.check(self.client.get(recovered_table['download_url'])).content
        equivalence = verify_recovered_table(source, result, original_raw, recovered_raw)
        final_proof = self.attempts_and_checkpoint(task_id)
        if [a['status'] for a in final_proof['attempts']] != ['failed', 'succeeded'] or digest(final_proof['attempts'][0]) != digest(self.record['attempt1_proof']['attempts'][0]):
            raise AssertionError('Attempt history changed or was not preserved')
        root = Path(self.state['staging']) / task_id
        for key, expected in self.record['attempt1_staging_files'].items():
            path = root / key
            if not path.is_file() or path.stat().st_size != expected['size_bytes'] or hash_file(path) != expected['sha256']:
                raise AssertionError('Retained failed-attempt bytes changed')
        self.verify_protected()
        self.record.update(status='controlled_recovery_passed', completed_task=completed, final_run=final_run,
            recovered_result_id=result['id'], recovered_manifest_sha256=result['manifest_sha256'],
            original_table_sha256=original_table['sha256'], recovered_table_sha256=recovered_table['sha256'],
            table_equivalence=equivalence,
            attempt1_materials_preserved=True, final_attempt_proof=final_proof, real_model_calls=0,
            scope='B04 synthetic external import engineering only; no GSE quota change, no real donor/biological/user acceptance')
        self.ledger.save()


def self_test():
    assert eligible_target('synthetic-project', 'CR-B04 synthetic external acceptance')
    assert not eligible_target(GSE_PROJECT, 'CR-B04 synthetic label')
    assert not eligible_target('other', 'GSE262082 research')
    assert not eligible_target('other', 'customer research')
    try:
        require_quiet([dict(id='foreign', status='queued')])
        raise AssertionError('An active foreign task was allowed')
    except ValueError:
        pass
    require_quiet([dict(id='own', status='running')], 'own')
    before = dict(limit_bytes=8192, mode='observe_only', revision=3)
    assert restore_decision(before, dict(limit_bytes=0, mode='enforced', revision=4), 4) == 'restore_owned_zero'
    assert restore_decision(before, dict(limit_bytes=8192, mode='observe_only', revision=5), 4) == 'already_original'
    try:
        restore_decision(before, dict(limit_bytes=100, mode='enforced', revision=5), 4)
        raise AssertionError('Foreign policy revision was overwritten')
    except ValueError:
        pass
    # Exercise the actual orchestration's finally path, rather than merely
    # demonstrating Python's try/finally with an unrelated local variable.
    from types import SimpleNamespace
    state = {'quota': 8192, 'restores': 0}
    fake = object.__new__(Experiment)
    fake.args = SimpleNamespace(restore_only=False)
    fake.record = {'actions': {}}
    fake.preflight = lambda: ({}, {})
    fake.create_run = lambda plan: {'id': 'isolated-run', 'task_id': 'isolated-task'}
    fake.set_zero = lambda task_id: state.update(quota=0)
    def fail_wait(task_id):
        assert state['quota'] == 0
        raise RuntimeError('synthetic observation failure')
    def restore_fake():
        state.update(quota=8192, restores=state['restores'] + 1)
    fake.wait_terminal, fake.restore = fail_wait, restore_fake
    try:
        fake.run()
        raise AssertionError('Observation failure was swallowed')
    except RuntimeError as exc:
        assert str(exc) == 'synthetic observation failure'
    assert state == {'quota': 8192, 'restores': 1}
    assert 'attempt1_failure' not in fake.record
    task = dict(status='failed', error_code='storage_quota_exceeded', current_attempt=1)
    require_admission_failure(task, dict(next_node='check', state_json={}))
    try:
        require_admission_failure(task, dict(next_node='publish', state_json={'prepared': {}}))
        raise AssertionError('A prepared-stage failure was mislabelled admission')
    except AssertionError as exc:
        assert 'not before' in str(exc)
    # Current real public request model, without API/DB/service execution.
    from app.domain.tasks.wait_contracts import ResumeRequest
    ResumeRequest.model_validate(dict(operation='retry', wait_id=None, expected_task_revision=2,
        input_version=dict(kind='bio_result_import', schema_version=1, workflow_version='bio_result_import_v1',
            source_sha256='a' * 64, source_digest='b' * 64, output_language='en', real_model_calls=False, real_network_calls=False)))
    print(json.dumps(dict(offline_self_test='passed', checks=['synthetic_only_GSE_refusal', 'no_active_foreign_tasks',
        'exact_revision_restore', 'finally_restore_on_exception', 'before_prepared_stage_only', 'actual_public_ResumeRequest']), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--project-id')
    parser.add_argument('--result-id', help='Actual successful synthetic-external-a result; never a guessed ID')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--restore-only', action='store_true')
    parser.add_argument('--retry-original', action='append', default=[], metavar='ACTION_LABEL')
    parser.add_argument('--wait-seconds', type=int, default=1200)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.state or not args.project_id or not args.result_id:
        parser.error('Explicit --state, --project-id and --result-id are required')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', v) for v in (args.project_id, args.result_id)) or args.project_id == GSE_PROJECT:
        parser.error('Invalid scope or forbidden GSE target')
    if args.restore_only and not args.execute or not 30 <= args.wait_seconds <= 14400:
        parser.error('Restore requires --execute; observation must be bounded to 30–14400 seconds')
    import cr_b04_runner as control
    control.STATE = args.state.resolve()
    state = control.read_state()
    if state['clone_status'] != 'verified':
        raise ValueError('Only the verified isolated B04 copy is allowed')
    token = digest(dict(project_id=args.project_id, result_id=args.result_id))[:12]
    output = (args.output or (control.RUNTIME / 'recovery' / token)).resolve()
    if not output.is_relative_to((control.RUNTIME / 'recovery').resolve()) or output == (control.RUNTIME / 'recovery').resolve():
        raise ValueError('Use a dedicated B04 recovery evidence subdirectory')
    if not args.execute:
        print(json.dumps(dict(status='prepared_not_executed', schema=state['schema'], project_id=args.project_id,
            result_id=args.result_id, output=str(output),
            sequence=['check synthetic fixed import plan and quiet project', 'new run with original quota',
                      'audited project-only quota zero', 'actual worker quota refusal before prepared',
                      'finally restore exact original limit/mode', 'public same-task/current-revision retry',
                      'attempt1 preserved and attempt2 success, same run'],
            GSE_quota='never modified', business_execution='requires --execute', no_recomputation_claim=False), ensure_ascii=False, indent=2))
        return
    control.configure(state)
    experiment = Experiment(args, state, output)
    try:
        experiment.run()
        print(json.dumps(dict(status=experiment.record.get('status'), receipt=str(experiment.ledger.path),
            restoration=experiment.record.get('restoration'), run_id=experiment.record.get('run', {}).get('id'),
            task_id=experiment.record.get('run', {}).get('task_id'), recovered_result_id=experiment.record.get('recovered_result_id')), ensure_ascii=False))
    finally:
        # Also cover exceptions during preflight or post-failure retry setup.
        try:
            experiment.restore()
        finally:
            if experiment.client is not None:
                experiment.client.close()


if __name__ == '__main__':
    main()
