"""Real local document/OCR fixtures, no model, no business database writes."""
from tests.api.test_analysis import client
from app.db.database import database_connection
from app.maintenance.external_evidence_audit import audit_external_evidence


def material(client,project,file,kind,version=None,item_ids=(),key='evidence'):
    body=dict(file_id=file,source_kind=kind,title='External evidence',source_description='Synthetic local source',
        intended_use='reference',original_data='unavailable',item_ids=list(item_ids))
    if kind=='document_version':body['document_version_id']=version
    if kind=='ocr_review_version':body['ocr_review_version_id']=version
    result=client.post(f'/api/v1/projects/{project}/external-evidence',json=body,headers={'Idempotency-Key':key})
    assert result.status_code==201,result.text
    return result.json()


def test_selected_docx_blocks_are_frozen_and_reparse_preserves_material(client):
    from tests.api.test_document_versions import uploaded_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.adapters.docx_parser import parse_docx
    project,_,_,uploaded,content=uploaded_docx(client)
    assert run_parse_file_task(uploaded['task']['id'],1,parser=parse_docx)['status']=='succeeded'
    base=f"/api/v1/projects/{project['id']}/files/{uploaded['file_id']}"
    parent=client.get(base+'/document-versions').json()['items'][0]
    preview=client.get(base+'/external-evidence-source',params={'source_kind':'document_version','version_id':parent['id']})
    assert preview.status_code==200,preview.text
    selected=preview.json()['items'][0]
    first=material(client,project['id'],uploaded['file_id'],'document_version',parent['id'],[selected['id']])
    assert first['items']==[selected] and first['source']['review_status']=='not_reviewed'
    reparsed=client.post(base+'/document-versions',headers={'Idempotency-Key':'reparse'},json={'expected_latest_version':1})
    assert reparsed.status_code==202,reparsed.text
    assert run_parse_file_task(reparsed.json()['task_id'],1,parser=parse_docx)['status']=='succeeded'
    assert client.get(f"/api/v1/projects/{project['id']}/external-evidence/{first['id']}").json()==first
    assert client.get(base+'/download').content==content
    with database_connection() as db:
        assert all(c['invalid']==0 for c in audit_external_evidence(db))


def test_material_uses_corrected_ocr_version_and_keeps_raw_version_separate(client):
    from tests.integration.test_ocr_review import setup_review,execute,decide
    project,base,parent,task,original=setup_review(client)
    raw=client.get(base+'/external-evidence-source',params={'source_kind':'document_version','version_id':parent['id']}).json()
    raw_text=next(i for i in raw['items'] if i['kind']=='text')
    raw_material=material(client,project['id'],base.split('/')[-1],'document_version',parent['id'],[raw_text['id']],'raw')
    assert execute(task)['status']=='waiting_confirmation'
    review_url='/api/v1/tasks/'+task['id']+'/ocr-review'
    revised=decide(client,client.get(review_url).json(),'revise','correct',[dict(block_id='text-1',action='replace_text',text='CORRECTED LOCAL VALUE 9001')])
    assert execute(revised.json())['status']=='waiting_confirmation'
    approved=decide(client,client.get(review_url).json(),'approve','approve')
    assert execute(approved.json())['status']=='succeeded'
    version=client.get(review_url).json()['result']
    corrected=material(client,project['id'],base.split('/')[-1],'ocr_review_version',version['id'],['text-1'],'corrected')
    assert corrected['source']['review_status']=='human_reviewed'
    assert corrected['items'][0]['text']=='CORRECTED LOCAL VALUE 9001'
    assert corrected['items'][0]['text']!=raw_text['text']
    assert client.get(f"/api/v1/projects/{project['id']}/external-evidence/{raw_material['id']}").json()==raw_material
    assert client.get(base+'/download').content==original
    with database_connection() as db:
        assert all(c['invalid']==0 for c in audit_external_evidence(db))
        for table in ('analysis_runs','figures','explanations','reports','model_calls'):
            assert db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']==0


def test_material_access_and_preview_are_owner_scoped(client):
    from tests.integration.test_batch09_external_evidence import saved
    from tests.integration.test_project_ownership import account_client
    base,project,file,body,evidence=saved(client)
    with account_client('batch09-material-other@example.test')[0] as other:
        url=f'/api/v1/projects/{project}/external-evidence'
        assert other.get(url).status_code==404
        assert other.get(url+'/'+evidence['id']).status_code==404
        assert other.post(url,json=body,headers={'Idempotency-Key':'intruder'}).status_code==404
        assert other.get(base+'/external-evidence-source',params={'source_kind':'original'}).status_code==404


def test_evidence_readonly_audit_rejects_review_claim_for_raw_original(client):
    from tests.integration.test_batch09_external_evidence import saved
    from app.domain.dataset_preparation.service import request_digest
    from psycopg.types.json import Jsonb
    _,_,_,_,evidence=saved(client)
    forged={k:v for k,v in evidence.items() if k!='sha256'}
    forged['source']['review_status']='human_reviewed'
    with database_connection(write=True) as db:
        db.execute('UPDATE external_evidence_versions SET snapshot_json=%s,sha256=%s WHERE id=%s',
                   (Jsonb(forged),request_digest(forged),evidence['id']))
    with database_connection() as db:
        assert audit_external_evidence(db)[0]['invalid']==1
