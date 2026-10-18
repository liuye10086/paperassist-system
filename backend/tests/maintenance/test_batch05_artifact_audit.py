"""Read-only auditing must reject forged scope and altered version bodies."""
from app.db.database import database_connection
from app.adapters.report_store import digest
from copy import deepcopy
import pytest
from psycopg.types.json import Jsonb
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from app.domain.figure_workbench.contracts import SaveConfiguration


def test_config_audit_detects_version_body_source_and_wrong_project(client):
    from app.maintenance.figure_report_audit import audit_figure_reports
    store,project,result=source(client)
    saved=store.save(project,result['file_id'],result['id'],SaveConfiguration(
        config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}))
    vid=saved['version']['id']
    def invalid(table):
        with database_connection() as db:
            return next(c for c in audit_figure_reports(db) if c['table']==table)['invalid']
    with database_connection() as db:
        original=dict(db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone())
    assert invalid('figure_config_versions')==0
    with database_connection(write=True) as db:
        db.execute("UPDATE figure_config_versions SET config_json=jsonb_set(config_json,'{language}','\"zh-CN\"'::jsonb) WHERE id=%s",(vid,))
    assert invalid('figure_config_versions')==1
    # A self-consistent digest must not legitimize a different frozen source.
    for key in ('source','result_sha256','analysis_plan'):
        altered=deepcopy(original['source_json'])
        altered[key]='0'*64 if key=='result_sha256' else {}
        with database_connection(write=True) as db:
            db.execute('UPDATE figure_config_versions SET config_json=%s,source_json=%s,sha256=%s WHERE id=%s',
                (Jsonb(original['config_json']),Jsonb(altered),digest({'config':original['config_json'],'source':altered}),vid))
        assert invalid('figure_config_versions')==1,key
    second=client.post('/api/v1/projects',json={'name':'Other synthetic project','research_topic':'scope check','project_type':'sci'}).json()
    with database_connection(write=True) as db:
        db.execute('UPDATE figure_config_versions SET source_json=%s,sha256=%s WHERE id=%s',(Jsonb(original['source_json']),original['sha256'],vid))
        db.execute('UPDATE figure_configurations SET project_id=%s WHERE id=%s',(second['id'],saved['id']))
    assert invalid('figure_configurations')==1


def test_collection_audit_rejects_self_consistent_but_unrelated_source(client,monkeypatch):
    from tests.integration.test_batch05_collection_pipeline import complete_collection
    from app.maintenance.figure_report_audit import audit_figure_reports
    repository,_,_,state,_,_=complete_collection(client,monkeypatch)
    vid=state['current_version_id']
    with repository.store.connection(write=True) as db:
        row=dict(db.execute('SELECT * FROM report_collection_versions WHERE id=%s',(vid,)).fetchone())
        forged=deepcopy(row['source_json']);forged['dataset_sha256']='f'*64
        content=deepcopy(row['content_json']);content['sources']=[forged]
        version_hash=digest(content)
        db.execute('UPDATE report_collection_versions SET source_json=%s,content_json=%s,sha256=%s WHERE id=%s',
            (Jsonb(forged),Jsonb(content),version_hash,vid))
        for request in db.execute('SELECT * FROM report_build_requests WHERE version_id=%s',(vid,)).fetchall():
            request_hash=digest({'version_id':vid,'sha256':version_hash,'request_key':request['request_key']})
            db.execute('UPDATE report_build_requests SET request_digest=%s WHERE id=%s',(request_hash,request['id']))
    with repository.store.connection() as db:
        checks=audit_figure_reports(db)
    assert next(c for c in checks if c['table']=='report_collection_versions')['invalid']==1


@pytest.mark.parametrize('altered_part', ['sources', 'result'])
def test_collection_audit_rejects_self_consistent_forged_build_input(client,monkeypatch,altered_part):
    from tests.integration.test_batch05_collection_pipeline import complete_collection
    from app.maintenance.figure_report_audit import audit_figure_reports
    repository,_,_,state,_,_=complete_collection(client,monkeypatch)
    request_id=state['versions'][0]['requests'][0]['id']
    with repository.store.connection(write=True) as db:
        request=dict(db.execute('SELECT * FROM report_build_requests WHERE id=%s',(request_id,)).fetchone())
        snapshot=deepcopy(request['input_json'])
        if altered_part=='sources':
            snapshot['sources'][0]['dataset_sha256']='f'*64
        else:
            snapshot['items'][0]['result']['check']['valid_count']+=1
            snapshot['items'][0]['hashes']['result']=digest(snapshot['items'][0]['result'])
        input_hash=digest(snapshot)
        db.execute('UPDATE report_build_requests SET input_json=%s,input_sha256=%s WHERE id=%s',
            (Jsonb(snapshot),input_hash,request_id))
        db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s',
            (Jsonb(snapshot),input_hash,request['task_id']))
        report=dict(db.execute('SELECT * FROM collection_reports WHERE build_request_id=%s',(request_id,)).fetchone())
        metadata=deepcopy(report['report_json']);metadata['input_sha256']=input_hash
        db.execute('UPDATE collection_reports SET input_json=%s,report_json=%s WHERE id=%s',
            (Jsonb(snapshot),Jsonb(metadata),report['id']))
    with repository.store.connection() as db:
        assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
        checks=audit_figure_reports(db)
    by_table={c['table']:c for c in checks}
    assert by_table['report_collection_versions']['invalid']==0
    assert by_table['report_collection_items']['invalid']==0
    assert by_table['report_build_requests']['invalid']==1
    assert by_table['collection_reports']['invalid']==1
