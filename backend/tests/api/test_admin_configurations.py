"""Real isolated PostgreSQL configuration lifecycle; no live transports."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from sqlalchemy.exc import DBAPIError

from app.db.database import database_connection, migration_connection
from app.main import app
from tests.api.test_admin_operations import accounts, admin, login, seed_task

ROOT = '/api/v1/admin/configurations'


def test_journal_catalog_verification_is_nullable_and_does_not_change_saved_bundle(admin):
    original = baseline(admin)
    directory = admin.get(ROOT+'/catalog').json()['installed']['journal_sources']
    assert {item['id'] for item in directory} == {'official_local', 'open_local', 'user_provided', 'synthetic'}
    for item in directory:
        assert item['verified_on'] is None
        assert item['verification_scope'] == ('synthetic_material_only' if item['id'] == 'synthetic' else 'local_source_record_only')
        assert item['official_verification'] == 'not_established'
    after = admin.get(ROOT+'/'+original['id']).json()
    copied = admin.post(ROOT+'/'+original['id']+'/copy', json={}).json()
    assert after['bundle'] == copied['bundle'] == original['bundle']
    assert after['sha256'] == copied['sha256'] == original['sha256']


def baseline(client):
    response = client.post(ROOT+'/baseline', json={})
    assert response.status_code == 201, response.text
    return response.json()


def saved(client, parent, domain='journals', field='default_count', value=2):
    bundle = deepcopy(parent['bundle'])
    bundle[domain][field] = value
    response = client.post(ROOT+'/'+parent['id']+'/save', json={'bundle': bundle})
    assert response.status_code == 201, response.text
    return response.json()


def validated(client, version):
    response = client.post(ROOT+'/'+version['id']+'/validate', json={})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'passed', response.text
    return response.json()


def switch(client, version, revision, key, operation='activate'):
    return client.post(ROOT+'/'+version['id']+'/'+operation,
        json={'expected_revision': revision, 'reason': 'Synthetic configuration validation', 'request_key': key})


def test_baseline_is_explicit_draft_and_current_requires_validation(admin):
    assert admin.get(ROOT+'/current').json() == {'revision': 0, 'version': None}
    version = baseline(admin)
    assert version['bundle']['ncbi']['enabled'] is False
    assert version['bundle']['models']['real_calls_enabled'] is False
    assert version['bundle']['basic']['worker_concurrency'] == 1
    assert admin.get(ROOT+'/current').json()['version'] is None
    assert switch(admin, version, 0, 'missing-validation').status_code == 409
    validation = validated(admin, version)
    assert validation['sha256'] == version['sha256']
    assert validation['real_connectivity'] == 'not_tested'
    result = switch(admin, version, 0, 'first')
    assert result.status_code == 200, result.text
    assert result.json()['revision'] == 1


def test_revisions_sha_validation_invalidation_idempotency_and_rollback(admin):
    one = baseline(admin); validated(admin, one)
    assert switch(admin, one, 0, 'first').status_code == 200
    copied = admin.post(ROOT+'/'+one['id']+'/copy', json={}).json()
    assert copied['id'] != one['id'] and copied['sha256'] == one['sha256']
    two = saved(admin, copied)
    assert two['sha256'] != one['sha256']
    assert switch(admin, two, 1, 'unvalidated').status_code == 409
    validation = validated(admin, two)
    assert validation['domains']['journals']['mode'] == 'validated'
    assert validation['domains']['basic']['mode'] == 'reused'
    first = switch(admin, two, 1, 'second')
    assert first.status_code == 200, first.text
    assert switch(admin, two, 1, 'second').json() == first.json()
    assert switch(admin, one, 1, 'second').status_code == 409
    assert switch(admin, two, 2, 'noop').status_code == 409
    assert switch(admin, copied, 2, 'never-active', 'rollback').status_code == 409
    result = switch(admin, one, 2, 'rollback', 'rollback')
    assert result.status_code == 200 and result.json()['revision'] == 3
    events = admin.get(ROOT+'/events').json()['items']
    assert [e['operation'] for e in events] == ['rollback', 'activate', 'activate']
    assert admin.get(ROOT+'/'+one['id']).json()['bundle'] == one['bundle']


def test_incompatible_legal_shape_has_visible_failure_and_unknown_secret_is_rejected(admin):
    one = baseline(admin)
    invalid = saved(admin, one, 'journals', 'default_count', 5)
    invalid = saved(admin, invalid, 'journals', 'max_count', 2)
    result = admin.post(ROOT+'/'+invalid['id']+'/validate', json={})
    assert result.status_code == 200 and result.json()['status'] == 'failed'
    assert result.json()['domains']['journals']['errors'] == ['default_count_exceeds_max_count']
    assert switch(admin, invalid, 0, 'bad').status_code == 409
    for field, value in [('api_key', 'sk-PRIVATE-SECRET'), ('endpoint','https://private.invalid'), ('regex','.*')]:
        bundle = deepcopy(one['bundle']); bundle['ncbi'][field] = value
        response = admin.post(ROOT+'/'+one['id']+'/save', json={'bundle': bundle})
        assert response.status_code == 422
        assert value not in response.text


def test_all_configuration_reads_and_writes_require_active_admin(admin, accounts):
    one = baseline(admin)
    with TestClient(app) as ordinary:
        login(ordinary, accounts[2])
        for route in ['', '/current','/catalog','/events','/'+one['id'],'/'+one['id']+'/diff']:
            assert ordinary.get(ROOT+route).status_code == 403
        for route in ['/baseline','/'+one['id']+'/copy','/'+one['id']+'/validate']:
            assert ordinary.post(ROOT+route,json={}).status_code == 403
    from app.domain.admin_configuration.service import Configurations
    service = Configurations(accounts[0]['id'])
    with database_connection(write=True) as db:
        db.execute("UPDATE users SET role='user' WHERE id=%s", (accounts[0]['id'],))
    with pytest.raises(Exception) as exc:
        service.copy(one['id'])
    assert exc.value.code == 'permission_denied'


def test_concurrent_cas_has_one_winner_and_retry_is_exact(admin, accounts):
    from app.domain.admin_configuration.service import Configurations
    one = baseline(admin); validated(admin, one)
    two = saved(admin, one); validated(admin, two)
    def attempt(pair):
        actor, version, key = pair
        try:
            return Configurations(actor).switch(version['id'], expected_revision=0,
                reason='Concurrent synthetic validation', request_key=key)
        except Exception as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [(accounts[0]['id'],one,'a'),(accounts[1]['id'],two,'b')]))
    assert sum(isinstance(r,dict) for r in results) == 1
    assert 'configuration_revision_conflict' in results
    assert len(admin.get(ROOT+'/events').json()['items']) == 1


def test_immutable_history_at_runtime_and_database_trigger(admin):
    one = baseline(admin); validated(admin, one); switch(admin, one, 0, 'first')
    for table in ['admin_configuration_versions','admin_configuration_validations','admin_configuration_events']:
        with pytest.raises(DBAPIError):
            with database_connection(write=True) as db:
                db.execute('DELETE FROM '+table)
        with pytest.raises(DBAPIError):
            with migration_connection(write=True) as db:
                db.execute('DELETE FROM '+table)


def test_task_binding_transaction_inheritance_does_not_change_snapshot(admin, accounts):
    from app.domain.admin_configuration.bindings import bind, current, projection, resolve
    one = baseline(admin); validated(admin, one); switch(admin, one, 0, 'first')
    _, task = seed_task(accounts[0]['id'])
    with database_connection() as db:
        old = dict(db.execute('SELECT input_snapshot,input_digest FROM tasks WHERE id=%s',(task,)).fetchone())
    with pytest.raises(RuntimeError):
        with database_connection(write=True) as db:
            bind(db, kind='task', object_id=task, version=current(db))
            raise RuntimeError('rollback')
    with database_connection() as db:
        assert projection(db,'task',task)['status'] == 'legacy_unbound'
    with database_connection(write=True) as db:
        bind(db, kind='review_round', object_id='synthetic-round', version=current(db))
    two=saved(admin,one); validated(admin,two); switch(admin,two,1,'second')
    with database_connection(write=True) as db:
        inherited=resolve(db,inherit_kind='review_round',inherit_id='synthetic-round')
        assert inherited['id']==one['id']
        bound=bind(db,kind='task',object_id=task,version=inherited)
        assert bound['version_id']==one['id']
        assert resolve(db,kind='task',object_id='unknown') is None
        assert resolve(db,inherit_kind='review_round',inherit_id='legacy-round') is None
        assert dict(db.execute('SELECT input_snapshot,input_digest FROM tasks WHERE id=%s',(task,)).fetchone())==old
    with pytest.raises(Exception) as exc:
        with database_connection(write=True) as db:bind(db,kind='task',object_id=task,version=current(db))
    assert exc.value.code=='configuration_binding_conflict'


def test_legacy_protection_only_blocks_affected_unfrozen_inflight(admin, accounts):
    one=baseline(admin);validated(admin,one);switch(admin,one,0,'first')
    _,task=seed_task(accounts[0]['id'])
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET task_type='parse_file',status='waiting_input' WHERE id=%s",(task,))
    journals=saved(admin,one);validated(admin,journals)
    assert switch(admin,journals,1,'unrelated').status_code==200
    basic=saved(admin,journals,'basic','max_rows',50000);validated(admin,basic)
    response=switch(admin,basic,2,'affected')
    assert response.status_code==409 and response.json()['detail']['code']=='configuration_legacy_inflight'
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='succeeded' WHERE id=%s",(task,))
    assert switch(admin,basic,2,'now-safe').status_code==200


def test_installed_literature_policy_and_model_compatibility_are_explicit(admin):
    one=baseline(admin)
    literature=one['bundle']['models']['literature']
    assert literature is not None
    assert literature['execution']['policy']['model']=='gpt-6.1-sol'
    assert literature['execution']['policy']['prompt_version']=='literature_assistance_v1'
    bundle=deepcopy(one['bundle'])
    bundle['models']['writing']['execution']['policy']['model']='unsupported-model'
    bad=admin.post(ROOT+'/'+one['id']+'/save',json={'bundle':bundle}).json()
    result=admin.post(ROOT+'/'+bad['id']+'/validate',json={}).json()
    assert result['status']=='failed'
    assert 'writing_model_not_installed' in result['domains']['models']['errors']
    assert 'writing_incompatible_policy' in result['domains']['models']['errors']
    bundle=deepcopy(one['bundle'])
    bundle['models']['literature']['execution']['policy']['model']='gpt-5.6-sol'
    bundle['models']['literature']['execution']['policy']['price']['model']='gpt-5.6-sol'
    bad=admin.post(ROOT+'/'+one['id']+'/save',json={'bundle':bundle}).json()
    result=admin.post(ROOT+'/'+bad['id']+'/validate',json={}).json()
    assert 'literature_incompatible_policy' in result['domains']['models']['errors']


def test_validation_capability_change_requires_new_evidence(admin, monkeypatch):
    from app.domain.admin_configuration import catalog
    one=baseline(admin);validated(admin,one)
    monkeypatch.setattr(catalog,'capability_version',lambda:'f'*64)
    response=switch(admin,one,0,'stale-capability')
    assert response.status_code==409
    assert response.json()['detail']['code']=='configuration_validation_required'


def test_actual_literature_baseline_change_invalidates_evidence_and_domain_reuse(admin,monkeypatch):
    from app.domain.admin_configuration import catalog
    from app.domain.literature_live import batch06
    one=baseline(admin);first=validated(admin,one)
    narrower=deepcopy(batch06.MODEL_POLICY)
    narrower['max_output_tokens']=1500
    monkeypatch.setattr(batch06,'MODEL_POLICY',narrower)
    response=switch(admin,one,0,'changed-literature-baseline')
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='configuration_validation_required'
    assert catalog.capability_version()!=first['capability_version']
    refreshed=admin.post(ROOT+'/'+one['id']+'/validate',json={}).json()
    assert refreshed['status']=='failed'
    assert refreshed['domains']['models']['mode']=='validated'
    assert refreshed['domains']['models']['reused_validation_id'] is None
    assert 'literature_output_exceeds_deployment' in refreshed['domains']['models']['errors']
    capability=catalog.capabilities()
    assert capability['model_baseline']==catalog.defaults()[0]['models']
    assert {'domain/literature_live/batch06.py','domain/admin_configuration/catalog.py'}<=set(capability['installed_sources'])


def test_legacy_complete_policy_snapshot_survives_model_change_and_incomplete_does_not(admin,accounts):
    from app.domain.admin_configuration.legacy import _affected
    from tests.domain.test_explanation_policy import execution_policy
    # Existing tasks use explanation_policy, not a new invented snapshot field.
    frozen=execution_policy()
    complete=dict(task_type='explanation',input_snapshot={'explanation_policy':frozen})
    incomplete=dict(task_type='explanation',input_snapshot={'explanation_policy':{'policy':{}}})
    assert _affected(complete,['models.explanation.execution.policy.timeout_seconds']) is False
    assert _affected(incomplete,['models.explanation.execution.policy.timeout_seconds']) is True
    assert _affected(complete,['journals.default_count']) is False
    figure=deepcopy(complete);figure['task_type']='figure_explanation'
    figure['input_snapshot']['explanation_policy']['policy']['prompt_version']='figure_explanation_v1'
    assert _affected(figure,['models.explanation.execution.policy.timeout_seconds']) is False


def test_usage_summary_storage_is_append_only_and_not_a_second_balance(admin,accounts):
    with database_connection(write=True) as db:
        db.execute('''INSERT INTO admin_usage_summaries
            (id,actor_user_id,asof,filters,source_revision,result,source_manifest,sha256)
            VALUES('summary',%s,clock_timestamp(),%s,'model_usage_v1',%s,%s,%s)''',
            (accounts[0]['id'],Jsonb({'project_id':None}),Jsonb({'calls':0,'unknown_cost':0}),
             Jsonb({'call_ids':[],'usage_event_ids':[]}), 'a'*64))
    with pytest.raises(DBAPIError):
        with migration_connection(write=True) as db:db.execute("UPDATE admin_usage_summaries SET source_revision='changed'")


def test_audit_insert_failure_rolls_back_effective_pointer(admin):
    one=baseline(admin);validated(admin,one)
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_config_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$")
        db.execute('CREATE TRIGGER reject_config_audit BEFORE INSERT ON admin_configuration_events FOR EACH ROW EXECUTE FUNCTION reject_config_audit()')
    response=switch(admin,one,0,'audit-must-commit')
    assert response.status_code==500
    assert admin.get(ROOT+'/current').json()=={'revision':0,'version':None}


def test_new_task_binding_and_outbox_share_creation_transaction(admin,accounts):
    from app.domain.admin_configuration.bindings import bind,current
    from uuid import uuid4
    one=baseline(admin);validated(admin,one);switch(admin,one,0,'first')
    project,_=seed_task(accounts[0]['id'])
    task=str(uuid4())
    with pytest.raises(RuntimeError):
        with database_connection(write=True) as db:
            frozen=current(db)
            db.execute('''INSERT INTO tasks(id,project_id,user_id,task_type,idempotency_key,input_digest,
                input_snapshot,workflow_version,status,phase,revision,current_attempt,created_at,updated_at)
                VALUES(%s,%s,%s,'boxplot','new-atomic',%s,%s,'test','queued','compute',1,0,clock_timestamp(),clock_timestamp())''',
                (task,project,accounts[0]['id'],'a'*64,Jsonb({'exact':'old-contract'})))
            bind(db,kind='task',object_id=task,version=frozen)
            db.execute('''INSERT INTO task_outbox(id,task_id,task_revision,event_type,available_at,created_at,publish_attempts)
                VALUES(%s,%s,1,'task_ready',clock_timestamp(),clock_timestamp(),0)''',(str(uuid4()),task))
            raise RuntimeError('roll back full acceptance')
    with database_connection() as db:
        assert not db.execute('SELECT 1 FROM tasks WHERE id=%s',(task,)).fetchone()
        assert not db.execute('SELECT 1 FROM admin_configuration_bindings WHERE object_id=%s',(task,)).fetchone()
        assert not db.execute('SELECT 1 FROM task_outbox WHERE task_id=%s',(task,)).fetchone()


def test_secret_tokens_are_not_persisted_inside_otherwise_legal_fields(admin):
    one=baseline(admin);bundle=deepcopy(one['bundle'])
    bundle['models']['writing']['execution']['policy']['price']['version']='sk-PRIVATE-SECRET'
    response=admin.post(ROOT+'/'+one['id']+'/save',json={'bundle':bundle})
    assert response.status_code==422
    assert 'sk-PRIVATE-SECRET' not in response.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM admin_configuration_versions').fetchone()['n']==1


def test_permanently_failed_unbound_task_does_not_block_new_configuration(admin,accounts):
    one=baseline(admin);validated(admin,one);switch(admin,one,0,'first')
    _,task=seed_task(accounts[0]['id'])
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET task_type='parse_file' WHERE id=%s",(task,))
    basic=saved(admin,one,'basic','max_rows',50000);validated(admin,basic)
    assert switch(admin,basic,1,'past-failed-task').status_code==200
