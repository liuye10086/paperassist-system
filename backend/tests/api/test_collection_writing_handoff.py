"""Actual local v5 A/B pixels plus synthetic explanations; no network calls."""
from copy import deepcopy
from io import BytesIO
import json
import pytest
from pathlib import Path
from hashlib import sha256
from tests.api.test_analysis import client
from tests.api.test_analysis_writing_handoff import next_run,counts
from tests.api.test_review_figure_adoptions import actual_plot,post
from tests.api.test_manuscripts import body
from app.db.database import database_connection


def second_plot(a,result,monkeypatch):
    from app.adapters.figure_workbench_store import FigureWorkbenchStore,read_bundle
    from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection,GenerateFigure
    from app.domain.figure_workbench.tasks import submit
    from app.domain.figure_workbench.execution import run_figure_workbench_task
    from tests.helpers.projection import check_projection,confirm_projection
    from tests.integration.test_batch05_figure_execution import frozen_policy,IndependentLineProvider
    workbench=FigureWorkbenchStore(a['workbench'].assets);project=a['project'];file=a['file'];second=True
    args=(project,file['id'],result['id'])
    saved=workbench.save(*args,SaveConfiguration(config=dict(figure_kind='line',language='en',projection=dict(x_column='A',y_column='C'),style=dict(title='Synthetic historical B'))))
    vid=saved['version']['id'];checked=check_projection(workbench,*args,vid)
    projection=confirm_projection(workbench,*args,vid,ConfirmProjection(input_sha256=checked['input_sha256'],approved=True))
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',frozen_policy)
    task=submit(workbench,*args,vid,GenerateFigure(idempotency_key='collection-B-plot',external_processing=dict(confirmed=True,payload_sha256=workbench.external_preview(*args,vid)['payload_sha256'])))['task']
    # Honest controlled transport: actual local projection supplies both its
    # synthetic manifest and an input-dependent Pillow geometry, never old bytes.
    class LocalPixels(IndependentLineProvider):
        def receipt(self):
            value=super().receipt();identity='resp_synthetic_'+result['id']
            value['response_id']=identity;value['response']['id']=identity
            return value
        def upload_input(self, container_id, payload, *, policy):
            response=super().upload_input(container_id,payload,policy=policy)
            from PIL import Image, ImageDraw
            image=Image.new('RGB',(2400,1600),'white');draw=ImageDraw.Draw(image)
            points=[(100+float(r['x'])*300,1450-float(r['y'])*50) for r in payload['observations'] if r.get('x') is not None and r.get('y') is not None]
            draw.line(points,fill='navy',width=10)
            for x,y in points:draw.ellipse((x-12,y-12,x+12,y+12),fill='red')
            draw.text((80,40),'SYNTHETIC local Pillow pixels / network disabled',fill='black')
            raw=BytesIO();image.save(raw,format='PNG');self.png=raw.getvalue()
            return response
        def download(self, file_id, container_id, limit, *, policy):
            if file_id=='cfile_png':return self.png
            # This is a controlled manifest, not an independent external recompute.
            expected=workbench.material(*args,vid)[4]
            return json.dumps(expected).encode()
    provider=LocalPixels(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    bundle=read_bundle(workbench.assets,project,task['result_figure_id'])
    assert workbench.assets.figure_png(bundle['figure'])==provider.png
    return dict(project=project,file=file,result=result,config_id=vid,task=task,figure=bundle['figure'],png=provider.png,projection=projection,workbench=workbench)


def explain(a,monkeypatch):
    from app.adapters.figure_workbench_store import read_bundle
    from app.domain.figure_workbench.explanations import build_payload
    from app.domain.figure_workbench.tasks import submit,prompt_version
    from app.domain.figure_workbench.contracts import GenerateFigure
    from app.domain.figure_workbench.execution import run_figure_explanation_task
    from tests.integration.test_explanation_execution import SyntheticProvider
    from app.domain.literature.service import digest
    def policy(payload,explanation=False):
        return dict(policy=dict(model='test-explanation',prompt_version=prompt_version(payload,explanation=True),max_output_tokens=10000,timeout_seconds=15,tools=[],output_format='analysis_explanation_v1',price=dict(version='synthetic-only',model='test-explanation',input_micro_usd_per_million=100,cached_input_micro_usd_per_million=50,output_micro_usd_per_million=200)),input_token_allowance=100000,task_limit_micro_usd=500000)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',policy)
    payload=build_payload(read_bundle(a['workbench'].assets,a['project'],a['figure']['id']))
    task=submit(a['workbench'],a['project'],a['file']['id'],a['result']['id'],a['config_id'],GenerateFigure(idempotency_key='collection-explain-'+a['result']['id'],external_processing=dict(confirmed=True,payload_sha256=digest(payload))),figure_id=a['figure']['id'])['task']
    class Provider(SyntheticProvider):
        def receipt(self):
            receipt=super().receipt();sent=self.posts[0][1]
            value={key:' '.join('{{'+ref+'}}' for ref in refs) for key,refs in sent['required_references'].items()}
            receipt['response']['output'][0]['content'][0]['text']=json.dumps(value)
            receipt['response_id']='resp_synthetic_explain_'+a['result']['id'];receipt['response']['id']=receipt['response_id']
            return receipt
    provider=Provider()
    for _ in range(5):
        task=run_figure_explanation_task(task['id'],task['revision'],provider_factory=lambda:provider)
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    return task['result_explanation_id']


@pytest.mark.parametrize('project_type',['sci','thesis'])
def test_saved_dual_run_collection_transfers_exact_order_all_sources_caption_report_text_and_bytes(client,monkeypatch,project_type):
    from app.adapters.collection_store import CollectionStore
    from app.domain.report_collections.contracts import CollectionRequest
    from app.domain.report_collections.execution import run_collection_word_task
    from app.domain.tasks.execution import run_task
    from app.domain.manuscript_writing.bundle import build_bundle
    school_root=None
    if project_type=='thesis':
        from tests.api.test_school_exports import published
        school_path,_,_,school_root=published(client)
    a=actual_plot(client,monkeypatch,project=school_path.split('/')[4] if school_root else None);b=second_plot(a,next_run(client,a),monkeypatch)
    ea=explain(a,monkeypatch);eb=explain(b,monkeypatch)
    repository=CollectionStore(a['workbench'].assets)
    state=repository.create(a['project'],CollectionRequest(title='Synthetic A/B historical collection',language='en',items=[dict(figure_id=b['figure']['id'],explanation_id=eb,caption='User B caption'),dict(figure_id=a['figure']['id'],explanation_id=ea,caption='User A caption')]),'dual-run-collection')
    request=state['versions'][0]['requests'][0];assert request['status']=='queued',request
    assert run_collection_word_task(request['task_id'],1,config=repository.store.db_config,directory=repository.store.directory)['status']=='succeeded'
    state=repository.get(a['project'],state['id']);report=state['versions'][0]['requests'][0]['report']
    path=f'/api/v1/projects/{a["project"]}/manuscripts'
    payload=dict(collection_id=state['id'],collection_version_id=state['current_version_id'],report_id=report['id'])
    before=counts();response=post(client,path+'/collection-report-selection',payload,'collection-select')
    assert response.status_code==200,response.text
    assert counts()==before;selected=response.json()
    assert selected['analysis_run_ids']==[b['result']['id'],a['result']['id']]
    assert [g['figure_ids'] for g in selected['results_groups']]==[[b['figure']['id'],a['figure']['id']]]
    assert [n['caption'] for n in selected['figure_notes']]==[repository.preview(a['project'],state['id'],state['current_version_id'])['items'][i]['caption'] for i in range(2)]
    report_source=selected['sources'][-1];assert report_source['kind']=='collection_report'
    assert report_source['content']['report']==report
    assert report_source['content']['text'] and len(report_source['content']['items'])==2
    data=body(sources=[{k:s[k] for k in ('kind','id','file_id','role')} for s in selected['sources']],results_groups=selected['results_groups'],figure_notes=selected['figure_notes'],analysis_handoff_run_ids=selected['analysis_run_ids'])
    if school_root:
        data['thesis']=deepcopy(school_root['versions'][0]['input']['thesis'])
        data['thesis']['chapter_mappings'][-1]['result_group_ids']=[g['id'] for g in selected['results_groups']]
    response=post(client,path+'/preview',data,'collection-preview');assert response.status_code==200,response.text
    response=post(client,path,data,'collection-save');assert response.status_code==201,response.text
    version=response.json()['versions'][0];assert run_task(version['task_id'],1)['status']=='succeeded'
    materials=client.get(path+'/'+response.json()['id']+'/versions/1/writing-materials')
    assert materials.status_code==200,materials.text
    assert materials.json()['can_execute'] is False and materials.json()['materials']['sources'][-1]['report_text']==report_source['content']['text']
    from tests.api.test_analysis_writing_handoff import evidence
    evidence('collection-'+project_type,dict(selection=selected,input=data,saved=response.json(),materials=materials.json()),**{'collection-report.docx':repository.download(a['project'],state['id'],report['id'])[1],'A.png':a['png'],'B.png':b['png']})
    bundle=build_bundle(version['snapshot'],dict(mode='full',target_section=None,output_language='en',instructions='',keywords=[],acknowledgements='',selected_source_ids=[s['id'] for s in selected['sources']],selected_evidence_ids=[]))
    wire=json.loads(json.loads(bundle['wire_json'])['input']);assert wire['sources'][-1]['report_text']==report_source['content']['text']
    assert wire['sources'][-1]['facts']==[]
    with database_connection() as db:
        assert db.execute('SELECT collection_report_id FROM manuscript_sources WHERE version_id=%s AND source_id=%s',(version['id'],report['id'])).fetchone()['collection_report_id']==report['id']
        from app.domain.file_lifecycle.references import file_ids,frozen_references
        assert a['file']['id'] in file_ids(report_source)
        assert ('collection_reports',report['id']) in set(frozen_references(report_source))
    foreign=client.post('/api/v1/projects',json=dict(name='Foreign collection',research_topic='Synthetic',project_type='sci')).json()['id']
    assert post(client,f'/api/v1/projects/{foreign}/manuscripts/collection-report-selection',payload,'foreign').status_code in (404,409)
    assert post(client,path+'/collection-report-selection',payload|dict(collection_version_id='missing'),'wrong-version').status_code in (404,409)
    target=repository.directory/(report['id']+'.docx');raw=target.read_bytes();target.write_bytes(raw+b'changed')
    assert post(client,path+'/collection-report-selection',payload,'changed-bytes').status_code==409
    target.write_bytes(raw)
    with database_connection(write=True) as db:
        row=db.execute('SELECT input_json FROM collection_reports WHERE id=%s',(report['id'],)).fetchone()
        broken=deepcopy(row['input_json']);broken['title']='Tampered title'
        from psycopg.types.json import Jsonb
        db.execute('UPDATE collection_reports SET input_json=%s WHERE id=%s',(Jsonb(broken),report['id']))
    assert post(client,path+'/collection-report-selection',payload,'changed-metadata').status_code==409
