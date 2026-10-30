"""Saved historical sources enter real manuscript inputs, without running writing."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from tests.api.test_analysis import client
from tests.api.test_manuscripts import body
from tests.api.test_review_figure_adoptions import actual_plot, post
from app.db.database import database_connection


def next_run(client, a):
    from tests.domain.test_correlation_plan_contracts import selection, research
    from tests.helpers.analysis_plan import run_plan, review_plan, decide_plan
    from tests.test_batch09_research_flow import decision
    from tests.helpers.statistics import statistics_post
    base=f'/api/v1/projects/{a["project"]}/files/{a["file"]["id"]}'
    selected=selection();selected.update(sheet_name=a['result']['source']['sheet_name'],columns=['A','C'],units={'A':'','C':''})
    created=post(client,base+'/analysis-plans',dict(schema_version=5,input_kind='data',file_id=a['file']['id'],dataset_id=a['result']['source']['dataset_id'],expected_setup_revision=1,selection=selected,research_request=research(),evidence_version_ids=[]),'handoff-v5-B')
    assert created.status_code==202,created.text
    task=created.json();assert run_plan(task)['status']=='waiting_input'
    view=review_plan(client,task);request={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
    request.update(expected_task_revision=view['task']['revision'],source_resolution=dict(confirmed=True,note='Synthetic same-file historical handoff test'))
    response=post(client,'/api/v1/tasks/'+task['id']+'/analysis-plan/source-decisions',request,'handoff-v5-B-source')
    assert response.status_code==202,response.text
    assert run_plan(response.json())['status']=='waiting_confirmation'
    approved=decide_plan(client,task,decision(review_plan(client,task)),'handoff-v5-B-confirm')
    assert approved.status_code==202,approved.text
    assert run_plan(approved.json())['status']=='succeeded'
    response=statistics_post(client,base+'/analysis-runs',json={'expected_revision':2})
    assert response.status_code in (200,201),response.text
    return response.json()


def counts():
    with database_connection() as db:
        return {t:db.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'] for t in ('tasks','manuscripts','manuscript_versions','model_calls')}


def evidence(label,values,**files):
    """Optional audit output; ordinary tests have no runtime fixture dependency."""
    import os
    from hashlib import sha256
    root=os.environ.get('PAPERASSIST_BIII_EVIDENCE_DIR')
    if not root:return
    target=Path(root)/label;target.mkdir(exist_ok=False)
    hashes={}
    for name,raw in files.items():
        (target/name).write_bytes(raw);hashes[name]=sha256(raw).hexdigest()
    (target/'context.json').write_text(json.dumps(dict(evidence='synthetic_local_engineering_only',values=values,artifact_sha256=hashes),ensure_ascii=False,indent=2,default=str),encoding='utf8')


def test_fixed_v5_historical_run_and_png_are_read_only_and_enter_preview_save_bundle(client,monkeypatch):
    from app.domain.tasks.execution import run_task
    from app.domain.manuscript_writing.bundle import build_bundle
    a=actual_plot(client,monkeypatch);b=next_run(client,a)
    assert b['id']!=a['result']['id'] and b['setup_revision']==2
    path=f'/api/v1/projects/{a["project"]}/manuscripts'
    request=dict(file_id=a['file']['id'],analysis_run_id=a['result']['id'],figure_id=a['figure']['id'])
    before=counts();response=post(client,path+'/analysis-selection',request,'selection')
    assert response.status_code==200,response.text
    selected=response.json();assert counts()==before
    assert selected['analysis_run_id']==a['result']['id']
    assert selected['sources'][0]['content']==a['result']
    assert selected['sources'][1]['sha256']==a['figure']['sha256']
    assert selected['report_status']=='not_selected'
    assert post(client,path+'/analysis-selection',request,'repeat').json()==selected
    data=body(sources=[{k:s[k] for k in ('kind','id','file_id','role')} for s in selected['sources']],results_groups=[selected['results_group']],figure_notes=selected['figure_notes'],analysis_handoff_run_ids=[a['result']['id']])
    preview=post(client,path+'/preview',data,'preview');assert preview.status_code==200,preview.text
    saved=post(client,path,data,'save');assert saved.status_code==201,saved.text
    version=saved.json()['versions'][0]
    assert version['snapshot']==preview.json()
    assert run_task(version['task_id'],1)['status']=='succeeded'
    materials=client.get(path+'/'+saved.json()['id']+'/versions/1/writing-materials')
    assert materials.status_code==200,materials.text
    assert materials.json()['can_execute'] is False and materials.json()['materials']['sources'][0]['facts']
    bundle=build_bundle(version['snapshot'],dict(mode='full',target_section=None,output_language='en',instructions='',keywords=[],acknowledgements='',selected_source_ids=[s['id'] for s in selected['sources']],selected_evidence_ids=[]))
    wire=json.loads(json.loads(bundle['wire_json'])['input'])
    assert wire['sources'][0]['facts'] and next(i for i in wire['illustrations'] if i['kind']=='figure')['caption']==a['figure']['caption']
    assert client.get(path+'/'+saved.json()['id']).status_code==200
    live_preview=post(client,path+'/'+saved.json()['id']+'/writing-previews',dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[s['id'] for s in selected['sources']],selected_evidence_ids=[]),'historical-live-preview')
    assert live_preview.status_code==201,live_preview.text
    evidence('historical-sci',dict(a=a['result'],latest_b=b,selection=selected,input=data,saved=saved.json(),materials=materials.json(),writing_preview=live_preview.json()),**{'A.png':a['png']})
    bad=request|dict(file_id='missing');assert post(client,path+'/analysis-selection',bad,'bad').status_code in (404,409)
    with database_connection() as db:
        foreign=db.execute('SELECT id FROM projects WHERE id<>%s LIMIT 1',(a['project'],)).fetchone()
    assert post(client,path+'/analysis-selection',request|dict(analysis_run_id=b['id'],figure_id=a['figure']['id']),'wrong-run').status_code==409
    assets=a['workbench'].assets;png=assets.directory/'figures'/(a['figure']['id']+'.png')
    original=png.read_bytes();png.write_bytes(original+b'changed')
    assert post(client,path+'/analysis-selection',request,'tampered').status_code==409
    png.write_bytes(original)


@pytest.mark.parametrize('project_type',['sci','thesis'])
def test_saved_report_source_validates_input_docx_and_enters_public_writing_bundle(client,monkeypatch,project_type):
    from tests.integration.test_dataset_artifact_chain import complete_chain
    from tests.helpers.tasks import task_owner
    from app.adapters.storage import ProjectStore
    from app.adapters.report_store import ReportStore
    from app.core.config import get_data_dir
    from app.domain.manuscript_writing.bundle import build_bundle
    from app.domain.tasks.execution import run_task
    school_root=None
    if project_type=='thesis':
        from tests.api.test_school_exports import published
        school_path,_,_,school_root=published(client)
    with monkeypatch.context() as chain_patch:
        if school_root:
            from tests.api.test_review_science import upload_in_project
            chain_patch.setattr('tests.integration.test_dataset_artifact_chain.add_file',lambda instance:upload_in_project(instance,school_path.split('/')[4],[['指标','组别'],[1,'A'],[2,'A'],[None,'B'],[3,None],[0,'B']]))
        a=complete_chain(client,chain_patch)
    assets=ProjectStore(get_data_dir(),owner_id=task_owner(client));reports=ReportStore(assets)
    with database_connection() as db:
        row=db.execute('SELECT * FROM reports WHERE analysis_run_id=%s',(a['result']['id'],)).fetchone()
    report=json.loads(row['report_json']);pid=a['base'].split('/')[4];path=f'/api/v1/projects/{pid}/manuscripts'
    request=dict(file_id=a['file']['id'],analysis_run_id=a['result']['id'],figure_id=a['figure']['id'],report_id=report['id'])
    before=counts();response=post(client,path+'/analysis-selection',request,'report-selection')
    assert response.status_code==200,response.text
    assert counts()==before;selected=response.json();source=selected['sources'][2]
    assert source['kind']=='analysis_report' and source['role']=='user_results'
    assert source['content']['report']==report and source['content']['text']
    assert source['content']['input_sha256']==report['input_sha256']
    candidates=client.get(path+'/candidates').json()['items'];assert any(s['kind']=='analysis_report' and s['id']==report['id'] for s in candidates)
    data=body(output_language='zh-CN',sources=[{k:s[k] for k in ('kind','id','file_id','role')} for s in selected['sources']],results_groups=[selected['results_group']],figure_notes=selected['figure_notes'])
    if school_root:
        data['thesis']=deepcopy(school_root['versions'][0]['input']['thesis'])
        data['thesis']['chapter_mappings'][-1]['result_group_ids']=[selected['results_group']['id']]
    preview=post(client,path+'/preview',data,'report-preview');assert preview.status_code==200,preview.text
    saved=post(client,path,data,'report-save');assert saved.status_code==201,saved.text
    v=saved.json()['versions'][0];assert run_task(v['task_id'],1)['status']=='succeeded'
    material_preview=client.get(path+'/'+saved.json()['id']+'/versions/1/writing-materials')
    assert material_preview.status_code==200,material_preview.text
    assert material_preview.json()['materials']['sources'][2]['report_text']==source['content']['text']
    bundle=build_bundle(v['snapshot'],dict(mode='full',target_section=None,output_language='zh-CN',instructions='',keywords=[],acknowledgements='',selected_source_ids=[s['id'] for s in selected['sources']],selected_evidence_ids=[]))
    wire=json.loads(json.loads(bundle['wire_json'])['input']);attachment=wire['sources'][2]
    assert attachment['report_text']==source['content']['text'] and attachment['facts']==[]
    assert 'download_url' not in attachment and report['id'] not in bundle['wire_json']
    evidence('single-report-'+project_type,dict(selection=selected,input=data,saved=saved.json(),materials=material_preview.json()),**{'analysis-report.docx':reports.content(report)})
    with database_connection() as db:
        bound=db.execute('SELECT file_id,kind FROM manuscript_sources WHERE version_id=%s AND source_id=%s',(v['id'],report['id'])).fetchone()
        assert dict(bound)==dict(file_id=a['file']['id'],kind='analysis_report')
        from app.domain.file_lifecycle.references import file_ids,frozen_references
        assert a['file']['id'] in file_ids(v['snapshot']) and ('reports',report['id']) in set(frozen_references(v['snapshot']))
    # Foreign project and wrong explicit figure are rejected by the scoped reader.
    foreign=client.post('/api/v1/projects',json=dict(name='Foreign',research_topic='Test',project_type='sci')).json()['id']
    assert post(client,f'/api/v1/projects/{foreign}/manuscripts/analysis-selection',request,'foreign').status_code in (404,409)
    assert post(client,path+'/analysis-selection',request|dict(report_id='missing'),'missing').status_code in (404,409)
    file=reports.directory/(report['id']+'.docx');raw=file.read_bytes();file.write_bytes(raw+b'tamper')
    assert post(client,path+'/analysis-selection',request,'tamper-docx').status_code==409
    file.write_bytes(raw)
    changed=json.loads(row['input_json']);changed['project']['name']='tampered'
    with database_connection(write=True) as db:db.execute('UPDATE reports SET input_json=%s WHERE id=%s',(json.dumps(changed),report['id']))
    assert post(client,path+'/analysis-selection',request,'tamper-input').status_code==409


def test_thesis_explicit_historical_handoff_can_publish_but_still_checks_school_and_sources(client,monkeypatch):
    from tests.api.test_school_exports import published
    from app.domain.tasks.execution import run_task
    from app.domain.manuscript_writing.bundle import build_bundle
    path,old_path,_,old=published(client)
    a=actual_plot(client,monkeypatch,project=path.split('/')[4]);b=next_run(client,a)
    assert b['setup_revision']==2
    response=post(client,path+'/manuscripts/analysis-selection',dict(file_id=a['file']['id'],analysis_run_id=a['result']['id'],figure_id=a['figure']['id']),'thesis-select')
    assert response.status_code==200,response.text
    selected=response.json();assert selected['project_type']=='thesis'
    data=deepcopy(old['versions'][0]['input']);data.update(title='Explicit historical A',expected_revision=0,output_language='en',sources=[{k:s[k] for k in ('kind','id','file_id','role')} for s in selected['sources']],results_groups=[selected['results_group']],figure_notes=selected['figure_notes'],analysis_handoff_run_ids=[a['result']['id']])
    data['thesis']['chapter_mappings'][-1]['result_group_ids']=[selected['results_group']['id']]
    assert post(client,path+'/manuscripts/preview',data,'thesis-preview').status_code==200
    saved=post(client,path+'/manuscripts',data,'thesis-handoff');assert saved.status_code==201,saved.text
    version=saved.json()['versions'][0]
    assert run_task(version['task_id'],1)['status']=='succeeded'
    materials=client.get(path+'/manuscripts/'+saved.json()['id']+'/versions/1/writing-materials')
    assert materials.status_code==200,materials.text
    assert materials.json()['can_execute'] is False
    evidence('historical-thesis',dict(a=a['result'],latest_b=b,selection=selected,input=data,saved=saved.json(),materials=materials.json()),**{'A.png':a['png']})
    preview_request=dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[s['id'] for s in selected['sources']],selected_evidence_ids=[])
    assert post(client,path+'/manuscripts/'+saved.json()['id']+'/writing-previews',preview_request,'thesis-live-still-closed').status_code==422
    bundle=build_bundle(version['snapshot'],dict(mode='full',target_section=None,output_language='en',instructions='',keywords=[],acknowledgements='',selected_source_ids=[s['id'] for s in selected['sources']],selected_evidence_ids=[]))
    assert json.loads(json.loads(bundle['wire_json'])['input'])['sources'][0]['facts']
    assert client.get(old_path+'/versions/1').json()['snapshot']==old['versions'][0]['snapshot']
    bad=deepcopy(data);bad['analysis_handoff_run_ids']=[b['id']]
    assert post(client,path+'/manuscripts/preview',bad,'wrong-allowlist').status_code==422
    bad=deepcopy(data);bad['thesis']['profile_revision']+=1
    assert post(client,path+'/manuscripts/preview',bad,'wrong-school').status_code==409
