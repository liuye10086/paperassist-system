from tests.helpers.statistics import statistics_post
from tests.api.test_analysis import client, add_file, selection
from tests.api.test_datasets import generate, structure_parser
from app.domain.tasks.dataset_execution import run_dataset_task
from app.adapters.storage import ProjectStore
from app.db.database import database_connection
import pytest


def version(client, base, latest=0):
    view = generate(client, base, latest, 'v'+str(latest+1))
    assert run_dataset_task(view['task']['id'], 1, parser=structure_parser)['status'] == 'succeeded'
    return client.get(base+'/structure-versions/'+view['id']).json()['datasets'][0]


def forbid_original(*args, **kwargs):
    raise AssertionError('Dataset analysis must never read original xlsx')


def test_dataset_profile_save_run_cache_and_explicit_version_binding(client, monkeypatch):
    base, record = add_file(client, [['Value','Group']] + [[n,'A'] for n in range(1,32)])
    first = version(client, base)
    original_reader = ProjectStore.original
    monkeypatch.setattr(ProjectStore, 'original', forbid_original)
    monkeypatch.setattr('app.domain.analysis.parse_workbook', forbid_original)
    monkeypatch.setattr('openpyxl.load_workbook', forbid_original)
    params = dict(sheet='研究 & 数据', dataset_id=first['id'])
    profile = client.get(base+'/analysis-profile', params=params)
    assert profile.status_code == 200, profile.text
    assert profile.json()['row_count'] == 31
    assert 'source' not in profile.json()
    checked = client.post(base+'/analysis-check', json=selection(dataset_id=first['id']))
    assert checked.status_code == 200 and checked.json()['valid_count'] == 31, checked.text
    saved = client.put(base+'/analysis-setup', json=selection(dataset_id=first['id'], expected_revision=0))
    assert saved.status_code == 200, saved.text
    assert saved.json()['source']['dataset_id'] == first['id']
    assert 'dataset_id' not in saved.json()['selection']
    assert client.get(base+'/analysis-setup').json()['source'] == saved.json()['source']
    with monkeypatch.context() as extraction:
        extraction.setattr(ProjectStore, 'original', original_reader)
        second = version(client, base, 1)
    assert client.get(base+'/analysis-setup').json() == saved.json()
    run = statistics_post(client, base+'/analysis-runs', json={'expected_revision':1})
    assert run.status_code == 200, run.text
    assert run.json()['overall']['n'] == 31
    assert run.json()['overall']['mean'] == 16
    assert run.json()['source'] == saved.json()['source']
    assert run.json()['engine']['id'] == 'descriptive_statistics_dataset_v1'
    assert 'openpyxl_version' not in run.json()['engine']
    assert statistics_post(client, base+'/analysis-runs', json={'expected_revision':1}).json() == run.json()
    assert client.get(base+'/analysis-result').json()['is_current']
    saved2 = client.put(base+'/analysis-setup', json=selection(dataset_id=second['id'], expected_revision=1))
    assert saved2.status_code == 200 and saved2.json()['revision'] == 2
    state = client.get(base+'/analysis-result').json()
    assert not state['is_current'] and state['result'] == run.json()
    with database_connection() as db:
        row = db.execute('SELECT object_key FROM dataset_versions WHERE id=%s',(first['id'],)).fetchone()
    from app.core.config import get_data_dir
    from pathlib import Path
    # Result retrieval must validate its historical source too.
    path = Path(get_data_dir())/row['object_key']
    path.write_bytes(b'broken')
    assert client.get(base+'/analysis-result').status_code == 409


def test_dataset_request_rejects_other_file_and_sheet(client):
    base, _ = add_file(client)
    first = version(client, base)
    other, _ = add_file(client)
    assert client.get(other+'/analysis-profile',params={'sheet':'研究 & 数据','dataset_id':first['id']}).status_code == 404
    assert client.get(base+'/analysis-profile',params={'sheet':'空表','dataset_id':first['id']}).status_code == 422


def test_legacy_serialization_has_no_new_source(client):
    base,_=add_file(client)
    saved=client.put(base+'/analysis-setup',json=selection(expected_revision=0))
    assert saved.status_code == 200
    assert 'source' not in saved.json()
    run=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert run.status_code == 200
    assert 'source' not in run.json()
    assert 'parser_version' not in run.json()['engine']


def test_cached_run_rejects_modified_frozen_source(client):
    import json
    base,_=add_file(client)
    first=version(client,base)
    saved=client.put(base+'/analysis-setup',json=selection(dataset_id=first['id'],expected_revision=0)).json()
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==200
    with database_connection(write=True) as db:
        row=db.execute('SELECT setup_json FROM analysis_setups').fetchone()
        changed=json.loads(row['setup_json'])
        changed['source']['dataset_version']=2
        db.execute('UPDATE analysis_setups SET setup_json=%s',(json.dumps(changed),))
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==409 and response.json()['detail']['code']=='source_conflict'


def test_run_publication_rejects_same_revision_source_swap(client,monkeypatch):
    import json
    from app.domain import descriptive
    base,_=add_file(client)
    first=version(client,base)
    client.put(base+'/analysis-setup',json=selection(dataset_id=first['id'],expected_revision=0))
    original=ProjectStore.save_analysis_run
    def swap_then_save(store, project_id,file_id,result):
        with database_connection(write=True) as db:
            row=db.execute('SELECT setup_json FROM analysis_setups').fetchone()
            changed=json.loads(row['setup_json'])
            changed['source']['dataset_version']=2
            db.execute('UPDATE analysis_setups SET setup_json=%s',(json.dumps(changed),))
        return original(store,project_id,file_id,result)
    monkeypatch.setattr(ProjectStore,'save_analysis_run',swap_then_save)
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==409, response.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n']==0


def test_save_keeps_first_scanned_source_when_dataset_metadata_changes(client,monkeypatch):
    from app.domain import dataset_analysis
    base,_=add_file(client)
    first=version(client,base)
    original=dataset_analysis.scan_dataset
    def scan_then_swap(*args,**kwargs):
        value=original(*args,**kwargs)
        with database_connection(write=True) as db:
            db.execute("UPDATE file_structure_versions SET parser_version='changed' WHERE id=%s",(first['structure_id'],))
        return value
    monkeypatch.setattr(dataset_analysis,'scan_dataset',scan_then_swap)
    response=client.put(base+'/analysis-setup',json=selection(dataset_id=first['id'],expected_revision=0))
    assert response.status_code==409
    assert client.get(base+'/analysis-setup').json() is None


@pytest.mark.parametrize('damage',['missing','corrupt','manifest','version','parser','owner','summary'])
def test_dataset_damage_is_rejected_even_on_cache_hit(client,monkeypatch,damage):
    import json
    from psycopg.types.json import Jsonb
    from app.core.config import get_data_dir
    base,_=add_file(client)
    first=version(client,base)
    saved=client.put(base+'/analysis-setup',json=selection(dataset_id=first['id'],expected_revision=0))
    assert saved.status_code==200
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==200
    with database_connection() as db:
        row=dict(db.execute('SELECT * FROM dataset_versions WHERE id=%s',(first['id'],)).fetchone())
    if damage=='missing':
        (get_data_dir()/row['object_key']).unlink()
    elif damage=='corrupt':
        (get_data_dir()/row['object_key']).write_bytes(b'corrupt')
    else:
        if damage=='owner':
            from app.auth.service import create_user
            other_owner=create_user('damage-owner@paperassist.local','isolated-damage-password-2026')['id']
        with database_connection(write=True) as db:
            if damage=='manifest':
                db.execute('UPDATE file_structure_versions SET manifest_json=%s WHERE id=%s',
                    (Jsonb({'schema_version':1,'epoch':'1900','filename':'data.xlsx','dataset_ids':[]}),first['structure_id']))
            elif damage=='version':
                setup=json.loads(db.execute('SELECT setup_json FROM analysis_setups').fetchone()['setup_json'])
                setup['source']['dataset_version']=2
                db.execute('UPDATE analysis_setups SET setup_json=%s',(json.dumps(setup),))
            elif damage=='parser':
                db.execute("UPDATE file_structure_versions SET parser_version='changed' WHERE id=%s",(first['structure_id'],))
            elif damage=='owner':
                db.execute('UPDATE file_structure_versions SET created_by=%s WHERE id=%s',(other_owner,first['structure_id']))
            elif damage=='summary':
                summary={**row['summary_json'],'row_count':999}
                db.execute('UPDATE dataset_versions SET summary_json=%s WHERE id=%s',(Jsonb(summary),first['id']))
    monkeypatch.setattr(ProjectStore,'original',forbid_original)
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code in (404,409,410),response.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n']==1


def test_cross_account_cannot_read_or_save_dataset_analysis(client):
    from app.auth.service import create_user
    base,_=add_file(client)
    first=version(client,base)
    client.put(base+'/analysis-setup',json=selection(dataset_id=first['id'],expected_revision=0))
    create_user('other-analysis@paperassist.local','isolated-other-password-2026')
    login=client.post('/api/v1/auth/login',json={'email':'other-analysis@paperassist.local','password':'isolated-other-password-2026'})
    client.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert client.get(base+'/analysis-profile',params={'sheet':'研究 & 数据','dataset_id':first['id']}).status_code==404
    assert client.get(base+'/analysis-setup').status_code==404
    assert client.put(base+'/analysis-setup',json=selection(dataset_id=first['id'],expected_revision=1)).status_code==404
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==404


def test_figure_state_compares_complete_frozen_source(client):
    import json
    from app.core.config import get_data_dir
    base,record=add_file(client)
    first=version(client,base)
    client.put(base+'/analysis-setup',json=selection(dataset_id=first['id'],expected_revision=0))
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    with database_connection() as db:
        project=db.execute('SELECT owner_id,project_id FROM files JOIN projects ON projects.id=files.project_id WHERE files.id=%s',(record['id'],)).fetchone()
    store=ProjectStore(get_data_dir(),owner_id=project['owner_id'])
    assert store.figure_state(result,'renderer',result['engine']['id'])['is_current']
    with database_connection(write=True) as db:
        saved=json.loads(db.execute('SELECT setup_json FROM analysis_setups').fetchone()['setup_json'])
        saved['source']['dataset_version']=2
        db.execute('UPDATE analysis_setups SET setup_json=%s',(json.dumps(saved),))
    assert not store.figure_state(result,'renderer',result['engine']['id'])['is_current']
    with database_connection(write=True) as db:
        figure={'source':{**result['source'],'dataset_version':2}}
        db.execute('INSERT INTO figures(id,analysis_run_id,renderer_version,figure_json) VALUES (%s,%s,%s,%s)',
            ('f-test',result['id'],'renderer',json.dumps(figure)))
    with pytest.raises(Exception,match='来源'):
        store.figure_state(result,'renderer',result['engine']['id'])


def test_dataset_task_must_belong_to_same_project_even_for_same_account(client):
    from psycopg.types.json import Jsonb
    base,_=add_file(client)
    first=version(client,base)
    other,_=add_file(client)
    other_project=other.split('/')[4]
    with database_connection(write=True) as db:
        task=db.execute('SELECT t.id,t.input_snapshot FROM tasks t JOIN file_structure_versions s ON s.task_id=t.id WHERE s.id=%s',(first['structure_id'],)).fetchone()
        snapshot={**task['input_snapshot'],'project':{'id':other_project}}
        db.execute('UPDATE tasks SET project_id=%s,input_snapshot=%s WHERE id=%s',(other_project,Jsonb(snapshot),task['id']))
    response=client.get(base+'/analysis-profile',params={'sheet':'研究 & 数据','dataset_id':first['id']})
    assert response.status_code==409,response.text


def test_cached_result_cannot_claim_another_file_with_same_source(client):
    import json
    base,_=add_file(client)
    first=version(client,base)
    client.put(base+'/analysis-setup',json=selection(dataset_id=first['id'],expected_revision=0))
    statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    with database_connection(write=True) as db:
        cached=json.loads(db.execute('SELECT result_json FROM analysis_runs').fetchone()['result_json'])
        cached['file_id']='another-file'
        db.execute('UPDATE analysis_runs SET result_json=%s',(json.dumps(cached),))
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==409,response.text
