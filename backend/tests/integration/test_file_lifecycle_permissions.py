"""Two-account HTTP evidence for the file preparation and document routes."""
from tests.helpers.legacy_plans import seed_legacy_plan
from pathlib import Path
import hashlib
import os
import pytest
from urllib.parse import quote
from app.db.database import database_connection
from tests.api.test_projects import client, create_project, upload  # noqa: F401
from tests.integration.test_project_ownership import account_client
from tests.api.test_file_lifecycle import assessment


def fingerprint():
    with database_connection() as db:
        tables=[r['table_name'] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name NOT IN ('sessions','auth_login_attempts')")]
        rows={name:sorted((repr(dict(r)) for r in db.execute('SELECT * FROM '+name))) for name in tables}
    root=Path(os.environ['PAPERASSIST_DATA_DIR'])
    objects={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    return rows,objects


def assert_private_reads(owner,other,urls):
    before=fingerprint()
    for url in urls:
        allowed=owner.get(url)
        assert allowed.status_code==200,(url,allowed.text)
        denied=other.get(url)
        assert denied.status_code==404,(url,denied.text)
    assert fingerprint()==before


def task_urls(identifier):
    return ['/api/v1/tasks/'+identifier+suffix for suffix in ('','/events','/workspace')]


def assert_private_recovery(owner,other,identifier):
    task=owner.get('/api/v1/tasks/'+identifier).json()
    before=fingerprint()
    assert other.post('/api/v1/tasks/'+identifier+'/retry',json={'expected_revision':task['revision']}).status_code==404
    body=dict(operation='retry',wait_id=None,expected_task_revision=task['revision'],input_version=task['input_version'])
    assert other.post('/api/v1/tasks/'+identifier+'/resume',json=body,headers={'Idempotency-Key':'foreign-recovery'}).status_code==404
    assert fingerprint()==before


def test_prepared_plan_raw_evidence_and_decisions_matrix(client):
    from tests.integration.test_dataset_preparation import create_preparation,run,review,decision,decide
    from tests.helpers.analysis_plan import create_plan,run_plan,review_plan,plan_decision,decide_plan
    base,file,raw,request,task=create_preparation(client)
    run(task)
    view=review(client,task)
    body=decision(view)
    with account_client('prepared-matrix@example.test')[0] as other:
        create_project(other)
        reads=[
            base+'/download',base+'/details',base+'/structure-versions',
            base+'/dataset-versions/'+raw['id']+'/rows',base+'/dataset-versions/'+raw['id']+'/download',
            base+'/dataset-versions/'+raw['id']+'/evidence',base+'/dataset-versions/'+raw['id']+'/preparation-defaults',
            '/api/v1/tasks/'+task['id']+'/dataset-preparation',view['preview_download_url'],*task_urls(task['id'])]
        assert_private_reads(client,other,reads)
        before=fingerprint()
        assert other.post(base+'/dataset-preparations',json=request,headers={'Idempotency-Key':'prepare'}).status_code==404
        assert decide(other,task,body).status_code==404
        assert fingerprint()==before
        approved=decide(client,task,body)
        assert approved.status_code==202
        assert run(approved.json())['status']=='succeeded'
        prepared=review(client,task)['result']
        from tests.api.test_analysis import selection
        plan_body=dict(dataset_id=prepared['id'],expected_setup_revision=0,selection=selection())
        created_plan=seed_legacy_plan(client, base+'/analysis-plans',json=plan_body,headers={'Idempotency-Key':'plan'})
        assert created_plan.status_code==202,created_plan.text
        plan=created_plan.json()
        assert run_plan(plan)['status']=='waiting_confirmation'
        plan_view=review_plan(client,plan)
        plan_input=plan_decision(plan_view)
        assert_private_reads(client,other,[base+'/prepared-dataset-versions',
            *[base+'/prepared-dataset-versions/'+prepared['id']+s for s in ('','/rows','/download','/evidence')],
            base+'/analysis-profile?sheet='+quote(prepared['source']['sheet_name'])+'&dataset_id='+prepared['id'],
            base+'/analysis-plans','/api/v1/tasks/'+plan['id']+'/analysis-plan',*task_urls(plan['id'])])
        before=fingerprint()
        assert seed_legacy_plan(other, base+'/analysis-plans',json=plan_body,headers={'Idempotency-Key':'plan'}).status_code==404
        assert decide_plan(other,plan,plan_input).status_code==404
        assert fingerprint()==before
        approved_plan=decide_plan(client,plan,plan_input)
        assert approved_plan.status_code==202
        assert run_plan(approved_plan.json())['status']=='succeeded'
        published=review_plan(client,plan)['result']
        assert_private_reads(client,other,[base+'/analysis-plans/'+published['id'],base+'/analysis-plans',
            base+'/lifecycle/assessment',base+'/lifecycle/tasks',base+'/lifecycle/deletion-requests'])
        with database_connection() as db:
            extract=db.execute("SELECT id FROM tasks WHERE task_type='extract_dataset'").fetchone()['id']
        assert_private_reads(client,other,task_urls(extract))
        before=fingerprint()
        for identifier in (task['id'],plan['id'],extract):
            assert_private_recovery(client,other,identifier)
        assert fingerprint()==before
        other_file=upload(client,base.split('/')[4]).json()['file']
        other_base='/'.join(base.split('/')[:-1])+'/'+other_file['id']
        for suffix in ('/dataset-versions/'+raw['id']+'/download',
                       '/prepared-dataset-versions/'+prepared['id']+'/download',
                       '/analysis-plans/'+published['id']):
            assert client.get(other_base+suffix).status_code==404
        assert client.post(other_base+'/dataset-preparations',json=request,headers={'Idempotency-Key':'wrong-file'}).status_code==404
        assert seed_legacy_plan(client, other_base+'/analysis-plans',json=plan_body,headers={'Idempotency-Key':'wrong-file'}).status_code==404


@pytest.mark.parametrize('kind',['docx','pdf','ocr'])
def test_document_subresources_reparse_ocr_and_task_matrix(client,kind):
    from tests.api.test_document_versions import uploaded_docx,uploaded_pdf
    from tests.api.test_ocr_versions import uploaded_image
    from app.adapters.docx_parser import parse_docx
    from app.adapters.pdf_parser import parse_pdf
    from tests.helpers.ocr_samples import ocr_result
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    if kind=='pdf':
        project,item,_=uploaded_pdf(client)
    else:
        project,_,_,item,_=(uploaded_docx if kind=='docx' else uploaded_image)(client)
    parser={'docx':parse_docx,'pdf':parse_pdf,'ocr':ocr_result}[kind]
    assert run_parse_file_task(item['task']['id'],1,parser=parser)['status']=='succeeded'
    base=f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    version=client.get(base+'/document-versions').json()['items'][0]
    detail=client.get(base+'/document-versions/'+version['id']).json()
    reads=[base+'/document-versions',base+'/document-versions/'+version['id'],version['download_url'],
        base+'/document-versions/'+version['id']+'/evidence',
        version['blocks_url'] if kind=='docx' else version['pages_url'],*task_urls(item['task']['id'])]
    reads += [image['download_url'] for image in detail.get('images',[])]
    with account_client('document-'+kind+'-matrix@example.test')[0] as other:
        assert_private_reads(client,other,reads)
        assert_private_recovery(client,other,item['task']['id'])
        before=fingerprint()
        body={'expected_latest_version':1,'expected_assessment_revision':assessment(client,base,'reparse')['assessment_revision']}
        assert other.post(base+'/document-versions',json=body,headers={'Idempotency-Key':'reparse'}).status_code==404
        if kind!='docx':
            assert other.post(base+'/document-versions/ocr',json={**body,'page_numbers':[1]},headers={'Idempotency-Key':'ocr'}).status_code==404
        assert fingerprint()==before
        allowed=client.post(base+'/document-versions'+('/ocr' if kind!='docx' else ''),
            json={**body,**({'page_numbers':[1]} if kind!='docx' else {})},headers={'Idempotency-Key':'reparse'})
        assert allowed.status_code==202,allowed.text


def test_ocr_review_candidate_publication_and_history_matrix(client):
    from tests.integration.test_ocr_review import setup_review,execute,decide
    _,base,parent,task,_=setup_review(client)
    assert execute(task)['status']=='waiting_confirmation'
    url='/api/v1/tasks/'+task['id']+'/ocr-review'
    view=client.get(url).json()
    value=assessment(client,base)
    assert value['counts']['registered_candidates']>=1
    with account_client('ocr-review-matrix@example.test')[0] as other:
        assert_private_reads(client,other,[url,view['preview_download_url'],base+'/ocr-reviews',*task_urls(task['id'])])
        assert_private_recovery(client,other,task['id'])
        before=fingerprint()
        assert other.post(base+'/ocr-reviews',json={'parse_id':parent['id']},headers={'Idempotency-Key':'create'}).status_code==404
        assert decide(other,view,'revise','foreign',[dict(block_id='text-1',action='accept_original')]).status_code==404
        assert fingerprint()==before
        saved=decide(client,view,'revise','save',[dict(block_id='text-1',action='accept_original')])
        assert execute(saved.json())['status']=='waiting_confirmation'
        view=client.get(url).json()
        assert decide(other,view,'approve','approve').status_code==404
        approved=decide(client,view,'approve','approve')
        assert execute(approved.json())['status']=='succeeded'
        result=client.get(url).json()['result']
        assert_private_reads(client,other,[base+'/ocr-review-versions',base+'/ocr-review-versions/'+result['id'],result['download_url'],parent['download_url']])
        after=assessment(client,base)
        assert after['counts']['ocr_review_versions']==1 and after['deletion_status']=='retained',after['reasons']
        assert after['latest_versions']['ocr_review_versions']==[dict(id=result['id'],version=1,parent_parse_id=parent['id'])]
