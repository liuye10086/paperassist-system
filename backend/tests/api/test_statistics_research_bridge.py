"""One migrated-schema scenario covers only the new typed statistics bridge."""
import json
from uuid import uuid4
import pytest
from psycopg.types.json import Jsonb
from sqlalchemy.exc import IntegrityError
from tests.api.test_analysis import client,add_file,selection
from tests.helpers.statistics import statistics_post
from app.db.database import database_connection

def test_statistics_completed_project_scoped_binding_full_export_and_legacy_source(client):
    base,file=add_file(client)
    project=base.split('/')[4];research=f'/api/v1/projects/{project}'
    configured=client.put(base+'/analysis-setup',json={**selection(),'expected_revision':0})
    assert configured.status_code==200,configured.text
    response=statistics_post(client,base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==200,response.text
    result=response.json();source=dict(source_kind='analysis_run',source_id=result['id'],locator=dict(kind='object'))
    listed=client.get(research+'/research-results/sources',params={'source_kind':'analysis_run'}).json()
    assert any(r['source_id']==result['id'] for r in listed['items'])
    preview=client.post(research+'/research-results/preview',json={'sources':[source]})
    assert preview.status_code==200,preview.text
    catalog=preview.json()['catalogs'][0]
    assert next(f for f in catalog['facts'] if f['locator']['field_path']=='overall.n')['raw_value']==result['overall']['n']
    assert catalog['source']['content']['execution_verification']=='verified'
    source['sha256']=catalog['source']['sha256']
    finding=client.post(research+'/research-findings',headers={'Idempotency-Key':'statistics-finding'},json=dict(title='Saved statistical results',sources=[source]))
    assert finding.status_code in (200,201),finding.text
    found=finding.json()
    with database_connection() as db:
        binding=dict(db.execute('SELECT * FROM research_source_bindings WHERE finding_version_id=%s',(found['id'],)).fetchone())
    assert binding['analysis_run_id']==result['id']
    # Reuse the formal table collector, not the bounded fact catalog.
    from app.domain.research_results.report_tables import collect_tables
    from app.domain.research_results.sources import ResearchSourceReader
    from app.adapters.task_store import DatasetTaskAssets
    from app.core.config import get_data_dir
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
        reader=ResearchSourceReader(DatasetTaskAssets(owner,db.config,get_data_dir()))
        tables,raws=collect_tables(reader,db,project,found['content']['sources'])
    assert tables and any(b'mean' in raw for raw in raws)
    # Existing original_file sources remain supported, with their external identity.
    original=client.post(research+'/research-results/preview',json={'sources':[dict(source_kind='original_file',source_id=file['id'])]})
    assert original.status_code==200,original.text
    other_base,other=add_file(client);other_project=other_base.split('/')[4]
    denied=client.post(f'/api/v1/projects/{other_project}/research-results/preview',json={'sources':[source]})
    assert denied.status_code==404
    # Direct malformed FK and project insert checks use separate rolled-back transactions.
    for bad,code in [('missing-run','23503')]:
        with pytest.raises(IntegrityError):
            with database_connection(write=True) as db:
                values={**binding,'id':str(uuid4()),'source_id':bad,'analysis_run_id':bad}
                db.execute('INSERT INTO research_source_bindings('+','.join(values)+') VALUES('+','.join(['%s']*len(values))+')',tuple(Jsonb(v) if isinstance(v,dict) else v for v in values.values()))
    incomplete=str(uuid4());pending={**result,'id':incomplete,'setup_revision':99,'completed_at':''}
    with database_connection(write=True) as db:
        db.execute('INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES(%s,%s,99,%s,\'\',%s)',(incomplete,file['id'],result['engine']['id'],json.dumps(pending)))
    incomplete_response=client.post(research+'/research-results/preview',json={'sources':[dict(source_kind='analysis_run',source_id=incomplete)]})
    assert incomplete_response.status_code==422
    changed=client.post(research+'/research-results/source-changes',json={'sources':[source]})
    assert changed.status_code==200,changed.text
    assert changed.json()['items'][0]['fixed_source_unchanged'] is True
    assert changed.json()['items'][0]['newer_version_id'] is None
    # Typed FK protects a referenced run even through low-level deletion attempts.
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:db.execute('DELETE FROM analysis_runs WHERE id=%s',(result['id'],))
