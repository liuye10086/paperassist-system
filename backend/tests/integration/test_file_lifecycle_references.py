"""Real reference chains, independent decision inputs and immutable source views."""
from psycopg.types.json import Jsonb
from tests.api.test_projects import client  # noqa: F401
from tests.api.test_file_lifecycle import assessment
from app.db.database import database_connection
import json
import pytest


def assert_blocked_public_history(client, base, hidden_ids=()):
    value = assessment(client, base)
    assert value['deletion_status'] == 'blocked'
    assert 'integrity_unknown' in [r['code'] for r in value['reasons']]
    page = client.get(base+'/lifecycle/tasks')
    assert page.status_code == 200, page.text
    receipt = client.post(base+'/lifecycle/deletion-requests', headers={'Idempotency-Key':'damaged'},
        json={'expected_assessment_revision':value['assessment_revision'], 'reason':'保留损坏来源证据'})
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()['status'] == 'blocked'
    history = client.get(base+'/lifecycle/deletion-requests')
    assert history.status_code == 200, history.text
    assert history.json()['items'] == [receipt.json()]
    for identifier in hidden_ids:
        assert identifier not in json.dumps([value, page.json(), receipt.json(), history.json()])
    return value, page.json()


@pytest.mark.parametrize('key', ['parse_id', 'dataset_id', 'plan_id'])
@pytest.mark.parametrize('bad', [[], {}, None, '', 7], ids=['array','object','null','empty','number'])
def test_malformed_task_source_ids_are_blocked_without_http_500(client, key, bad):
    from tests.api.test_document_versions import uploaded_docx
    project, _, _, item, _ = uploaded_docx(client)
    base = f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    with database_connection(write=True) as db:
        snapshot = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (item['task']['id'],)).fetchone()['input_snapshot']
        # parse_id replaces the real producer field; other keys exercise the
        # same recursive reader in an untyped nested persisted source node.
        if key == 'parse_id':
            snapshot[key] = bad
        else:
            snapshot['nested_source'] = {key:bad}
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s', (Jsonb(snapshot), item['task']['id']))
    value, page = assert_blocked_public_history(client, base)
    assert value['counts']['parse_versions'] == 1 and value['counts']['tasks'] == 1
    assert page['items'][0]['source_status'] == 'integrity_unknown'
    assert page['items'][0]['sources'] == []
    token = assessment(client, base, 'reparse')['assessment_revision']
    response = client.post(base+'/document-versions', headers={'Idempotency-Key':'damaged-reparse'},
        json={'expected_latest_version':1, 'expected_assessment_revision':token})
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'source_conflict'


@pytest.mark.parametrize('key', ['parse_id', 'dataset_id', 'plan_id'])
@pytest.mark.parametrize('bad', [[], {}, None], ids=['array','object','null'])
def test_malformed_artifact_source_ids_use_the_same_safe_reader(client, key, bad):
    from tests.integration.test_dataset_artifact_chain import new_result, confirmed_task
    base, file, result = new_result(client)
    task, _ = confirmed_task(client, base, file, result, 'boxplot')
    result['nested_source'] = {key:bad}
    with database_connection(write=True) as db:
        db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s', (json.dumps(result), result['id']))
    value, page = assert_blocked_public_history(client, base, [result['id']])
    assert value['counts']['analysis_runs'] == 1
    item = next(i for i in page['items'] if i['id'] == task['id'])
    assert item['source_status'] == 'integrity_unknown'


@pytest.mark.parametrize('damage', ['foreign_parent','row_owner','producer_owner','ancestor_owner'])
def test_prepared_public_sources_require_owner_producer_and_parent_chain(client, damage):
    from tests.helpers.analysis_plan import confirmed_sample
    from tests.integration.test_dataset_preparation import create_preparation
    from tests.integration.test_project_ownership import account_client
    base, _, prepared, _ = confirmed_sample(client)
    before = assessment(client, base)
    hidden = [prepared['id']]
    with database_connection(write=True) as db:
        producer = db.execute('SELECT task_id FROM prepared_dataset_versions WHERE id=%s', (prepared['id'],)).fetchone()['task_id']
    if damage == 'foreign_parent':
        _, _, foreign, _, _ = create_preparation(client)
        hidden.append(foreign['id'])
        sql, args = 'UPDATE prepared_dataset_versions SET parent_dataset_id=%s WHERE id=%s', (foreign['id'], prepared['id'])
    else:
        other, user = account_client('prepared-damage@example.test'); other.close()
        hidden.append(user['id'])
        if damage == 'row_owner':
            sql, args = 'UPDATE prepared_dataset_versions SET created_by=%s WHERE id=%s', (user['id'], prepared['id'])
        else:
            if damage == 'ancestor_owner':
                with database_connection() as db:
                    parent = db.execute('SELECT s.task_id FROM dataset_versions d JOIN file_structure_versions s ON s.id=d.structure_id WHERE d.id=%s', (prepared['parent_dataset_id'],)).fetchone()
                producer = parent['task_id']
                hidden.append(prepared['parent_dataset_id'])
            sql, args = 'UPDATE tasks SET user_id=%s WHERE id=%s', (user['id'], producer)
    with database_connection(write=True) as db:
        db.execute(sql, args)
    value, page = assert_blocked_public_history(client, base, hidden)
    assert value['counts']['prepared_dataset_versions'] == before['counts']['prepared_dataset_versions']
    assert value['counts']['tasks'] == before['counts']['tasks']
    assert value['latest_versions']['prepared_dataset_versions'] == []
    assert value['assessment_revision'] != before['assessment_revision']
    assert any(i['source_status'] == 'integrity_unknown' for i in page['items'])
    # Internal immutable receipt facts retain every damaged dependency.
    with database_connection() as db:
        facts = db.execute('SELECT assessment_json FROM file_deletion_requests').fetchone()['assessment_json']['references']
    assert facts['prepared_dataset_versions'][0]['id'] == prepared['id']


def published_ocr_review(client):
    from tests.integration.test_ocr_review import setup_review, execute, decide
    _, base, parent, task, _ = setup_review(client)
    execute(task)
    url = '/api/v1/tasks/'+task['id']+'/ocr-review'
    revised = decide(client, client.get(url).json(), 'revise', 'save',
        [dict(block_id='text-1', action='accept_original')])
    execute(revised.json())
    approved = decide(client, client.get(url).json(), 'approve', 'approve')
    assert execute(approved.json())['status'] == 'succeeded'
    return base, parent, client.get(url).json()['result']


@pytest.mark.parametrize('damage', ['foreign_parent','row_owner','producer_owner','ancestor_owner'])
def test_ocr_public_sources_require_owner_producer_and_parent_chain(client, damage):
    from tests.integration.test_project_ownership import account_client
    from tests.integration.test_ocr_review import setup_review
    base, parent, reviewed = published_ocr_review(client)
    before = assessment(client, base)
    hidden = [reviewed['id']]
    if damage == 'foreign_parent':
        _, _, foreign, _, _ = setup_review(client)
        hidden.append(foreign['id'])
        sql, args = 'UPDATE ocr_review_versions SET parent_parse_id=%s WHERE id=%s', (foreign['id'], reviewed['id'])
    else:
        other, user = account_client('ocr-damage@example.test'); other.close()
        hidden.append(user['id'])
        if damage == 'row_owner':
            sql, args = 'UPDATE ocr_review_versions SET created_by=%s WHERE id=%s', (user['id'], reviewed['id'])
        else:
            producer = reviewed['task_id'] if damage == 'producer_owner' else parent['task_id']
            if damage == 'ancestor_owner': hidden.append(parent['id'])
            sql, args = 'UPDATE tasks SET user_id=%s WHERE id=%s', (user['id'], producer)
    with database_connection(write=True) as db:
        db.execute(sql, args)
    value, page = assert_blocked_public_history(client, base, hidden)
    assert value['counts']['ocr_review_versions'] == before['counts']['ocr_review_versions']
    assert value['counts']['tasks'] == before['counts']['tasks']
    assert value['latest_versions']['ocr_review_versions'] == []
    assert value['assessment_revision'] != before['assessment_revision']


@pytest.mark.parametrize('kind', ['prepared', 'ocr'])
@pytest.mark.parametrize('bad', [[], None, '[]', 'null', '7', '"bad"'],
    ids=['array','null','encoded-array','encoded-null','encoded-number','encoded-string'])
def test_malformed_producer_source_container_is_blocked(client, kind, bad):
    from app.domain.file_lifecycle.contracts import digest
    if kind == 'prepared':
        from tests.helpers.analysis_plan import prepared_sample
        base, _, result = prepared_sample(client)
        group, route = 'prepared_dataset_versions', '/structure-versions'
    else:
        base, _, result = published_ocr_review(client)
        group, route = 'ocr_review_versions', '/document-versions/ocr'
    before = assessment(client, base)
    original = client.get(base+'/download').content
    with database_connection(write=True) as db:
        snapshot = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',
            (result['task_id'],)).fetchone()['input_snapshot']
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{source}',%s) WHERE id=%s",
            (Jsonb(bad), result['task_id']))
    value, page = assert_blocked_public_history(client, base, [result['id']])
    assert value['counts'] == before['counts']
    assert value['latest_versions'][group] == []
    item = next(i for i in page['items'] if i['id'] == result['task_id'])
    assert item['source_status'] == 'integrity_unknown' and item['sources'] == []
    token = assessment(client, base, 'reparse')['assessment_revision']
    body = dict(expected_assessment_revision=token, expected_latest_version=
        before['latest_versions']['structure_versions' if kind == 'prepared' else 'parse_versions'])
    if kind == 'ocr': body['page_numbers'] = [1]
    rejected = client.post(base+route, headers={'Idempotency-Key':'damaged-reparse'}, json=body)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()['detail']['code'] == 'source_conflict'
    frozen = client.get(base+'/lifecycle/deletion-requests').json()
    with database_connection() as db:
        facts = db.execute('SELECT assessment_json FROM file_deletion_requests').fetchone()['assessment_json']['references']
        assert next(r for r in facts[group] if r['id'] == result['id'])['task_id'] == result['task_id']
        task_facts = next(t for t in facts['tasks'] if t['id'] == result['task_id'])
        assert task_facts['input_snapshot_digest'] == digest({**snapshot, 'source':bad})
    # Restoring fixture damage changes live assessment, never the frozen receipt.
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s', (Jsonb(snapshot), result['task_id']))
    assert assessment(client, base) == before
    assert client.get(base+'/lifecycle/deletion-requests').json() == frozen
    replay = client.post(base+'/lifecycle/deletion-requests', headers={'Idempotency-Key':'damaged'},
        json={'expected_assessment_revision':value['assessment_revision'], 'reason':'保留损坏来源证据'})
    assert replay.status_code == 200 and replay.json() == frozen['items'][0]
    assert client.get(base+'/download').content == original


@pytest.mark.parametrize('damage', ['producer_owner','producer_project'])
def test_artifact_public_sources_verify_result_fk_producer_scope(client, monkeypatch, damage):
    from tests.integration.test_dataset_artifact_chain import complete_chain
    from tests.integration.test_project_ownership import account_client
    from tests.api.test_projects import create_project
    with monkeypatch.context() as local:
        result = complete_chain(client, local)
    base = result['base']
    before = assessment(client, base)
    hidden = [result['figure']['id'], result['explanation']['id'], result['word_task']['result_report_id']]
    if damage == 'producer_owner':
        other, user = account_client('artifact-damage@example.test'); other.close()
        column, foreign = 'user_id', user['id']
    else:
        column, foreign = 'project_id', create_project(client)['id']
    hidden.append(foreign)
    with database_connection(write=True) as db:
        task = db.execute('SELECT id FROM tasks WHERE result_figure_id=%s', (result['figure']['id'],)).fetchone()
        db.execute(f'UPDATE tasks SET {column}=%s WHERE id=%s', (foreign, task['id']))
    value, page = assert_blocked_public_history(client, base, hidden)
    for kind in ('figures','explanations','reports'):
        assert value['counts'][kind] == before['counts'][kind]
    assert value['assessment_revision'] != before['assessment_revision']
    assert any(i['source_status'] == 'integrity_unknown' for i in page['items'])


def test_prepared_plan_history_counts_candidates_and_task_pagination(client):
    from tests.helpers.analysis_plan import confirmed_sample
    base, file, prepared, review = confirmed_sample(client)
    value = assessment(client,base)
    assert value['deletion_status']=='retained',value['reasons']
    for key in ('structure_versions','dataset_versions','prepared_dataset_versions','confirmed_plans','analysis_setups'):
        assert value['counts'][key]>=1, (key,value)
    assert value['counts']['registered_candidates']>=1
    assert value['latest_versions']['prepared_dataset_versions']==[dict(id=prepared['id'],version=prepared['version'],parent_dataset_id=prepared['parent_dataset_id'])]
    pages=[client.get(base+'/lifecycle/tasks',params={'page':p,'page_size':1}).json() for p in range(1,value['counts']['tasks']+1)]
    assert all(p['counts']==value['counts'] and len(p['items'])==1 for p in pages)
    assert len({p['items'][0]['id'] for p in pages})==value['counts']['tasks']
    assert all(p['items'][0]['source_status']=='frozen_source' for p in pages)
    serialized=str(pages)
    assert 'object_key' not in serialized and 'input_snapshot' not in serialized
    with database_connection() as db:
        t=db.execute("SELECT id,revision FROM tasks WHERE task_type='prepare_dataset'").fetchone()
    before=value['assessment_revision']
    with database_connection(write=True) as db:
        db.execute("UPDATE task_checkpoints SET state_json=jsonb_set(state_json,'{candidate,sha256}',to_jsonb(%s::text)) WHERE task_id=%s AND state_json ? 'candidate'",('b'*64,t['id']))
    assert assessment(client,base)['assessment_revision']!=before
    with database_connection() as db:
        assert db.execute('SELECT revision FROM tasks WHERE id=%s',(t['id'],)).fetchone()['revision']==t['revision']


def test_full_artifact_lineage_and_independent_call_reservation_outbox_states(client,monkeypatch):
    from tests.integration import test_dataset_artifact_chain as chain
    from tests.integration.test_prepared_artifact_chain import prepared_result
    monkeypatch.setattr(chain,'new_result',prepared_result)
    with monkeypatch.context() as local:
        result=chain.complete_chain(client,local)
    base=result['base']
    value=assessment(client,base)
    # Synthetic plot's tool charge remains unreconciled after publication.
    assert value['deletion_status']=='blocked'
    assert [r['code'] for r in value['reasons']]==['internal_testing_retention','budget_reservations_held']
    for key in ('analysis_runs','figures','explanations','reports','model_calls','budget_reservations','usage_events'):
        assert value['counts'][key]>0, (key,value)
    from tests.integration.test_project_ownership import account_client
    from tests.integration.test_file_lifecycle_permissions import assert_private_reads,task_urls
    run_url=base+'/analysis-runs/'+result['result']['id']
    with account_client('prepared-artifact-matrix@example.test')[0] as other:
        urls=[base+'/analysis-result',run_url+'/figures/'+result['figure']['id']+'/download',
              run_url+'/explanation',result['report_url']]
        with database_connection() as db:
            artifacts=db.execute("SELECT id FROM tasks WHERE task_type IN ('boxplot','explanation','word_report')").fetchall()
        for artifact in artifacts:
            urls.extend(task_urls(artifact['id']))
        assert_private_reads(client,other,urls)
    with database_connection() as db:
        call=db.execute('SELECT id,task_id FROM model_calls ORDER BY id LIMIT 1').fetchone()
        task_revision=db.execute('SELECT revision FROM tasks WHERE id=%s',(call['task_id'],)).fetchone()['revision']
    previous=value['assessment_revision']
    for sql,params,reason in [
        ("UPDATE model_calls SET status='submission_unknown' WHERE id=%s",(call['id'],),'external_work_unresolved'),
        ("UPDATE budget_reservations SET status='held',reserved_micro_usd=reserved_micro_usd+1 WHERE call_id=%s",(call['id'],),'budget_reservations_held'),
        ("UPDATE task_outbox SET published_at=clock_timestamp() WHERE task_id=%s",(call['task_id'],),None),
        ("UPDATE tasks SET figure_candidate=%s WHERE id=%s",(Jsonb({'figure':{'id':'registered','sha256':'a'*64},'path':'candidate'}),call['task_id']),None),
    ]:
        with database_connection(write=True) as db:
            db.execute(sql,params)
        next_value=assessment(client,base)
        assert next_value['assessment_revision']!=previous
        if reason:
            assert reason in [r['code'] for r in next_value['reasons']]
        previous=next_value['assessment_revision']
    with database_connection() as db:
        assert db.execute('SELECT revision FROM tasks WHERE id=%s',(call['task_id'],)).fetchone()['revision']==task_revision
    assert client.get(result['report_url']).status_code==200
    import json
    with database_connection(write=True) as db:
        artifact={**result['figure'],'source':{**result['figure']['source'],'file_id':'foreign-file-marker'}}
        db.execute('UPDATE figures SET figure_json=%s WHERE id=%s',(json.dumps(artifact),result['figure']['id']))
    damaged=assessment(client,base)
    assert 'integrity_unknown' in [r['code'] for r in damaged['reasons']]
    assert 'foreign-file-marker' not in str(damaged)


def test_structure_guard_legacy_digest_newer_attempt_and_sheet_lineage(client):
    import hashlib,json
    from tests.api.test_datasets import prepared,structure_parser
    from app.domain.tasks.dataset_execution import run_dataset_task
    _,_,_,base=prepared(client)
    token=assessment(client,base,'reparse')['assessment_revision']
    body={'expected_latest_version':0,'expected_assessment_revision':token}
    first=client.post(base+'/structure-versions',json=body,headers={'Idempotency-Key':'first'})
    assert first.status_code==202,first.text
    assert run_dataset_task(first.json()['task']['id'],1,parser=structure_parser)['status']=='succeeded'
    assert client.post(base+'/structure-versions',json=body,headers={'Idempotency-Key':'first'}).status_code==200
    assert client.post(base+'/structure-versions',json={**body,'expected_latest_version':1},headers={'Idempotency-Key':'stale'}).status_code==409
    second=client.post(base+'/structure-versions',json={'expected_latest_version':1},headers={'Idempotency-Key':'second'})
    assert second.status_code==202,second.text
    with database_connection() as db:
        row=db.execute('SELECT a.client_assessment_supplied,t.input_digest FROM file_reparse_assessments a JOIN tasks t ON t.id=a.task_id WHERE a.task_id=%s',(second.json()['task']['id'],)).fetchone()
        assert row['client_assessment_supplied'] is False
        assert row['input_digest']==hashlib.sha256(json.dumps({'expected_latest_version':1},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    items=client.get(base+'/lifecycle/tasks').json()['items']
    old=next(i for i in items if i['id']==first.json()['task']['id'])
    assert old['source_status']=='newer_attempt_available'
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{file,id}',to_jsonb(%s::text)) WHERE id=%s",('foreign-sensitive-id',second.json()['task']['id']))
    corrupted=assessment(client,base)
    assert corrupted['deletion_status']=='blocked'
    assert 'integrity_unknown' in [r['code'] for r in corrupted['reasons']]
    assert 'foreign-sensitive-id' not in str(client.get(base+'/lifecycle/tasks').json())


def test_source_identity_version_and_hash_corruption_is_not_silently_valid(client):
    from tests.helpers.analysis_plan import confirmed_sample
    base,_,_,view=confirmed_sample(client)
    assert assessment(client,base)['deletion_status']=='retained'
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{source,dataset_version}','999'::jsonb) WHERE id=%s",(view['task']['id'],))
    result=assessment(client,base)
    assert result['deletion_status']=='blocked'
    assert 'integrity_unknown' in [r['code'] for r in result['reasons']]


def test_legacy_jobs_are_retained_mapped_and_unfinished_jobs_block(client):
    import json
    from tests.integration.test_dataset_artifact_chain import new_result
    from app.domain.tasks.legacy import legacy_id
    base,_,run=new_result(client)
    with database_connection(write=True) as db:
        db.execute('INSERT INTO figure_jobs(id,analysis_run_id,renderer_version,created_at,job_json) VALUES (%s,%s,%s,%s,%s)',
            ('old-job',run['id'],'legacy','2026-10-10T00:00:00Z',json.dumps({'status':'uncertain','private_key':'never-public'})))
    value=assessment(client,base)
    assert value['counts']['legacy_jobs']==1 and value['deletion_status']=='blocked'
    rows=client.get(base+'/lifecycle/tasks').json()['items']
    legacy=next(row for row in rows if row['origin']=='legacy')
    assert legacy['id']==legacy_id('plot','old-job') and legacy['status']=='waiting_confirmation'
    assert 'never-public' not in str(rows)
    with database_connection(write=True) as db:
        db.execute('UPDATE figure_jobs SET job_json=%s WHERE id=%s',(json.dumps({'status':'completed'}),'old-job'))
    assert assessment(client,base)['deletion_status']=='retained'


def test_ocr_freshness_is_parser_and_selected_pages_specific(client):
    from tests.api.test_document_versions import uploaded_pdf
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from tests.helpers.ocr_samples import ocr_result
    from app.core.exceptions import StorageError
    project,item,_=uploaded_pdf(client)
    run_parse_file_task(item['task']['id'],1,parser=parse_pdf)
    base=f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    def failure(*args): raise StorageError('invalid_document','invalid',422)
    tasks=[]
    for latest,pages in ((1,[1]),(2,[2]),(3,[1])):
        created=client.post(base+'/document-versions/ocr',json={'expected_latest_version':latest,'page_numbers':pages},headers={'Idempotency-Key':str(latest)})
        assert created.status_code==202,created.text
        tasks.append(created.json()['task_id'])
        run_parse_file_task(tasks[-1],1,parser=failure)
    views={t['id']:t for t in client.get(base+'/lifecycle/tasks').json()['items']}
    assert views[item['task']['id']]['source_status']=='frozen_source'
    assert views[tasks[0]]['source_status']=='newer_attempt_available'
    assert views[tasks[1]]['source_status']=='frozen_source'


def test_missing_frozen_source_is_unknown_and_decision_history_is_counted(client):
    from tests.helpers.analysis_plan import confirmed_sample
    base,_,_,view=confirmed_sample(client)
    value=assessment(client,base)
    assert value['counts'].get('dataset_preparation_decisions',0)>=2
    assert value['counts'].get('analysis_plan_decisions',0)==1
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=input_snapshot #- '{source,dataset_id}' WHERE id=%s",(view['task']['id'],))
    assert assessment(client,base)['deletion_status']=='blocked'


def test_cross_user_producer_is_counted_but_not_exposed(client):
    from tests.api.test_document_versions import uploaded_docx
    from tests.integration.test_project_ownership import account_client
    project,_,_,item,_=uploaded_docx(client)
    base=f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    other,user=account_client('corrupt-producer@example.test')
    other.close()
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET user_id=%s WHERE id=%s',(user['id'],item['task']['id']))
    value=assessment(client,base)
    assert value['counts']['tasks']==1 and value['deletion_status']=='blocked'
    page=client.get(base+'/lifecycle/tasks').json()
    assert page['items']==[]
    assert item['task']['id'] not in str(page) and user['id'] not in str(page)


def test_ocr_review_selected_pages_are_validated_against_frozen_parse(client):
    from tests.integration.test_ocr_review import setup_review
    _,base,_,task,_=setup_review(client)
    assert 'integrity_unknown' not in [r['code'] for r in assessment(client,base)['reasons']]
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{source,selected_pages}','[2]'::jsonb) WHERE id=%s",(task['id'],))
    assert 'integrity_unknown' in [r['code'] for r in assessment(client,base)['reasons']]
