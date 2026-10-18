from tests.helpers.legacy_plans import seed_legacy_plan
from io import BytesIO
from openpyxl import Workbook
from tests.api.test_analysis import client,selection
from tests.helpers.analysis_plan import prepared_sample,run_plan,review_plan,decide_plan
from tests.integration.test_research_plan import research
from tests.test_batch09_research_flow import decision
from tests.api.test_file_lifecycle import assessment


def multifile_requirement(client):
    base,file,prepared=prepared_sample(client)
    project=base.split('/')[4];project_base='/api/v1/projects/'+project
    book=Workbook();book.active.append(['external material']);content=BytesIO();book.save(content);book.close()
    other=client.post(project_base+'/files',files={'file':('external.xlsx',content.getvalue())}).json()['file']
    evidence=client.post(project_base+'/external-evidence',json=dict(file_id=other['id'],source_kind='original',
        title='External material',intended_use='background',original_data='unknown'),headers={'Idempotency-Key':'external'}).json()
    body=dict(schema_version=4,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,
        selection=selection(numeric_column='D',group_column='C',unit='mg'),research_request=research(),evidence_version_ids=[evidence['id']])
    response=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'multi'})
    assert response.status_code==202,response.text
    return base,project_base+'/files/'+other['id'],response.json(),evidence


def test_multifile_v4_has_strict_local_dependencies_on_both_files(client):
    base,other,task,evidence=multifile_requirement(client)
    assert run_plan(task)['status']=='waiting_confirmation'
    view=review_plan(client,task)
    approved=decide_plan(client,task,decision(view),'approve').json()
    assert run_plan(approved)['status']=='succeeded'
    for path in (base,other):
        value=assessment(client,path)
        assert 'integrity_unknown' not in [r['code'] for r in value['reasons']],value
        page=client.get(path+'/lifecycle/tasks')
        assert page.status_code==200,page.text
        item=next(x for x in page.json()['items'] if x['id']==task['id'])
        assert item['source_status']=='frozen_source'
    details=client.get(other+'/details').json()
    assert details['references']['external_evidence_versions']==1
    assert details['references']['tasks']>=1


def test_tampered_material_reference_blocks_multifile_history(client):
    from app.db.database import database_connection
    from psycopg.types.json import Jsonb
    base,other,task,evidence=multifile_requirement(client)
    with database_connection(write=True) as db:
        snapshot=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
        snapshot['evidence_versions'][0]['source']['source_sha256']='0'*64
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s',(Jsonb(snapshot),task['id']))
    for path in (base,other):
        value=assessment(client,path)
        assert 'integrity_unknown' in [r['code'] for r in value['reasons']]
        page=client.get(path+'/lifecycle/tasks').json()
        item=next(x for x in page['items'] if x['id']==task['id'])
        assert item['source_status']=='integrity_unknown' and item['sources']==[]
