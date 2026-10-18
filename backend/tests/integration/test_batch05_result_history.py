"""History discovers confirmed inputs without changing the current analysis."""
import json
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from tests.api.test_descriptive import configured,run
from app.db.database import database_connection


def test_history_keeps_confirmed_run_after_setup_changes_and_enforces_file_scope(client):
    _,project,result=source(client)
    with database_connection(write=True) as db:
        db.execute('UPDATE analysis_setups SET revision=revision+1 WHERE file_id=%s',(result['file_id'],))
        original=db.execute('SELECT result_json FROM analysis_runs WHERE id=%s',(result['id'],)).fetchone()['result_json']
    url=f"/api/v1/projects/{project}/files/{result['file_id']}/analysis-runs"
    response=client.get(url)
    assert response.status_code==200,response.text
    assert response.json()=={'items':[result]}
    with database_connection() as db:
        assert db.execute('SELECT result_json FROM analysis_runs WHERE id=%s',(result['id'],)).fetchone()['result_json']==original
        assert db.execute('SELECT revision FROM analysis_setups WHERE file_id=%s',(result['file_id'],)).fetchone()['revision']==2
    another=client.post('/api/v1/projects',json={'name':'Unrelated project','research_topic':'Synthetic only','project_type':'sci'}).json()
    assert client.get(url.replace(project,another['id'])).status_code==404


def test_history_excludes_legacy_and_invalid_sources_but_retains_old_read_path(client):
    base,_=configured(client);legacy=run(client,base)
    assert client.get(base+'/analysis-runs').json()=={'items':[]}
    assert client.get(base+'/analysis-result').json()['result']['id']==legacy['id']
    _,project,result=source(client)
    with database_connection(write=True) as db:
        forged={**result,'source':{**result['source'],'dataset_sha256':'f'*64}}
        db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s',(json.dumps(forged),result['id']))
    response=client.get(f"/api/v1/projects/{project}/files/{result['file_id']}/analysis-runs")
    assert response.status_code==200 and response.json()=={'items':[]}
