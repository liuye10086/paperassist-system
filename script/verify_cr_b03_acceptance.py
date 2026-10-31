"""Resumable B03 public API -> real local queue acceptance, no model calls."""
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script/dev'),str(ROOT/'backend')]
import cr_b03_runner as control


class Verification:
    def __init__(self,phase='outputs'):
        import httpx
        self.state=control.read_state();control.configure(self.state)
        self.path=control.RUNTIME/('queue-verification.json' if phase=='outputs' else 'queue-writing-verification.json')
        self.record=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else dict(schema=self.state['schema'],actions={},real_model_calls=0,user_acceptance='pending',biological_validation='not_performed')
        if self.record['schema']!=self.state['schema']:raise ValueError('Wrong retained verification schema')
        self.client=httpx.Client(base_url=self.state['url'],timeout=600,trust_env=False,headers={'Origin':self.state['url'],'X-PaperAssist-Client':'web'})
        credential=json.loads((Path(self.state['assets']).parent/'credentials.json').read_text(encoding='utf-8'))['review']
        response=self.client.post('/api/v1/auth/login',json={k:credential[k] for k in ('email','password')})
        self.check(response);self.client.headers['X-CSRF-Token']=response.json()['csrf_token']
        self.original=json.loads((control.RUNTIME/'actual-output-verification-v2.json').read_text(encoding='utf-8'))
        self.base='/api/v1/projects/'+self.original['project_id']

    @staticmethod
    def check(response):
        if response.status_code not in (200,201,202):
            try:code=response.json()['detail']['code']
            except (ValueError,KeyError,TypeError):code='unexpected_response'
            raise RuntimeError(f'HTTP {response.status_code}: {code}')
        return response

    def save(self):control.worker_stack.private_write(self.path,json.dumps(self.record,ensure_ascii=False,indent=2))
    def get(self,path):return self.check(self.client.get(path)).json()

    def post(self,label,path,body,*,kind=None,lookup=None):
        hashed=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        old=self.record['actions'].get(label)
        if old:
            if old['digest']!=hashed or old['path']!=path:raise RuntimeError('Retained intent differs; do not overwrite it')
            if 'response' in old:return old['response']
            endpoint=lookup or (self.base+'/research-requests/'+old['key']+'?kind='+kind if kind else None)
            if not endpoint:raise RuntimeError('Unknown POST retained; inspect its original intent before retry')
            value=self.get(endpoint)
        else:
            old=dict(key='b03-'+uuid4().hex,path=path,digest=hashed,body=body,status='submitting')
            self.record['actions'][label]=old;self.save()
            value=self.check(self.client.post(path,json=body,headers={'Idempotency-Key':old['key']})).json()
        old.update(response=value,status='returned');self.save();return value

    def wait(self,task_id):
        started=time.monotonic();prior=None
        while time.monotonic()-started<1200:
            task=self.get('/api/v1/tasks/'+task_id)
            status=task['status']
            if status!=prior:print(json.dumps({'task_id':task_id,'status':status}),flush=True);prior=status
            if status=='succeeded':return task
            if status in ('failed','cancelled','waiting_confirmation'):raise RuntimeError('Queue task stopped: '+str(task.get('error_code') or status))
            time.sleep(3)
        raise RuntimeError('Task wait timed out; task and materials retained')

    def download(self,value,directory):
        directory.mkdir(parents=True,exist_ok=True)
        for member in value['members']:
            target=directory/(member['key']+'.'+member['format'])
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==member['sha256']:continue
            raw=self.check(self.client.get(member['download_url'])).content
            if hashlib.sha256(raw).hexdigest()!=member['sha256']:raise ValueError('Download hash differs')
            target.write_bytes(raw)

    def outputs(self):
        from app.db.database import database_connection
        with database_connection() as db:
            figures=db.execute("SELECT id FROM bio_figure_versions WHERE project_id=%s AND processed_dataset_version_id=%s AND config_json->>'kind' IN ('umap','spatial_cluster') ORDER BY config_json->>'kind'",
                (self.original['project_id'],'f88123c7-b269-5c43-8974-dd36c62ecd46')).fetchall()
        panels=[{'source':{'source_kind':'bio_figure_version','source_id':figures[i%2]['id']},'label':label} for i,label in enumerate(['A','B','C'])]
        figure=self.post('queue-three-panel',self.base+'/research-figures',dict(mode='composite',panels=panels,columns=3,width_mm=180.0,dpi=300,
            title='GSE262082 three-panel acceptance',caption='Exploratory spot-level results; panel C reuses A for layout verification.',language='en',figure_language='original',formats=['png','tiff','svg','pdf']),kind='figure')
        self.wait(figure['task_id']);figure=self.get(self.base+'/research-figures/'+figure['id'])
        self.download(figure,control.RUNTIME/'queue-delivery/figure')
        reports=[]
        for language,title in [('zh-CN','GSE262082 空间转录组分析报告'),('en','GSE262082 spatial analysis report')]:
            body=dict(title=title,language=language,finding_version_id=self.original['finding_version_id'],figure_version_ids=[figure['id']])
            if language=='zh-CN':body.update(root_id=self.original['report_root_id'],expected_revision=2)
            report=self.post('queue-report-'+language,self.base+'/research-reports',body,kind='report')
            self.wait(report['task_id']);report=self.get(self.base+'/research-reports/'+report['id'])
            self.download(report,control.RUNTIME/'queue-delivery'/language)
            docx=next(m for m in report['members'] if m['role']=='docx')
            pdf=self.post('report-pdf-'+language,self.base+'/pdf-exports',dict(source_kind='research_report',source_id=docx['id'],request_key='b03-queue-report-pdf-'+language))
            recovery=self.record['actions'].get('report-pdf-retry-'+language)
            if recovery and recovery.get('response'):pdf=recovery['response']
            self.wait(pdf['task_id']);pdf=self.get(self.base+'/pdf-exports/'+pdf['id'])
            raw=self.check(self.client.get(pdf['download_url'])).content
            if hashlib.sha256(raw).hexdigest()!=pdf['sha256']:raise ValueError('PDF hash differs')
            (control.RUNTIME/'queue-delivery'/language/'analysis.pdf').write_bytes(raw)
            reports.append(dict(report=report,pdf=pdf))
        chinese=reports[0];report=chinese['report'];body=dict(title=report['content']['title'],language='zh-CN',finding_version_id=self.original['finding_version_id'],
            figure_version_ids=[figure['id']],root_id=report['root_id'],expected_revision=report['revision'],include_pdf_id=chinese['pdf']['id'])
        packaged=self.post('queue-pdf-package',self.base+'/research-reports',body,kind='report')
        self.wait(packaged['task_id']);packaged=self.get(self.base+'/research-reports/'+packaged['id'])
        self.download(packaged,control.RUNTIME/'queue-delivery/with-pdf')
        import zipfile
        with zipfile.ZipFile(control.RUNTIME/'queue-delivery/with-pdf/analysis_package.zip') as archive:
            assert hashlib.sha256(archive.read('analysis.pdf')).hexdigest()==chinese['pdf']['sha256']
        self.record['outputs']=dict(figure_version_id=figure['id'],report_version_ids=[r['report']['id'] for r in reports],packaged_report_version_id=packaged['id'])
        self.save()

    def writing(self):
        # Activate writing only in the B03 acceptance copy, retaining original
        # requirements and adding a clearly identified engineering version.
        old=self.record['actions'].get('writing-deliveries')
        if old:body=old['body']
        else:
            intake=self.get(self.base+'/research-intake');current=intake['current_requirement']
            content=dict(current['content']) if current else {'schema_version':1}
            content.update(services=['analysis','sci_draft','thesis_draft'])
            content['notes']=content.get('notes','')+'\nCR-B03 验收副本：启用写作工程路径，不改变 B02 原需求。'
            keys=('delivery_id','file_id','bio_dataset_version_id','locator','availability','purpose','note')
            refs=[{k:r[k] for k in keys if k in r} for r in (current.get('material_refs',[]) if current else [])]
            body=dict(expected_revision=intake['revision'],operation='save',content=content,material_refs=refs)
        self.post('writing-deliveries',self.base+'/requirements',body)
        deliveries={d['kind']:d['id'] for d in self.get(self.base+'/deliveries')['items'] if d['active']}
        thesis=self.school_template()
        published=[]
        for kind in ('sci_draft','thesis_draft'):
            body=dict(delivery_id=deliveries[kind],finding_version_ids=[self.original['finding_version_id']],figure_version_ids=[self.original['figure_version_id']],
                manual_notes='CR-B03 工程验收：公共数据再分析，部分章节事实稿，尚未生物学验证。')
            if kind=='thesis_draft':body['thesis']=thesis
            preview=self.check(self.client.post(self.base+'/research-results/writing-selection',json=body)).json()
            assert preview['can_execute'] is False and preview['real_model_calls'] is False
            candidate=self.post('actual-candidate-'+kind,self.base+'/research-manuscript-candidates',body,kind='candidate')
            self.wait(candidate['task_id']);candidate=self.get(self.base+'/research-manuscript-candidates/'+candidate['id'])
            assert candidate['candidate']['writing_scope']=='results_methods'
            result=self.post('actual-publish-'+kind,self.base+'/research-manuscript-candidates/'+candidate['id']+'/publish',
                dict(candidate_id=candidate['id'],expected_revision=0),lookup=self.base+'/research-manuscript-candidates/'+candidate['id'])
            endpoint=self.base+'/manuscripts/'+result['manuscript_id']
            version=self.get(endpoint+'/versions/'+str(result['revision']))
            folder=control.RUNTIME/'queue-delivery'/kind;folder.mkdir(parents=True,exist_ok=True)
            (folder/'snapshot.json').write_text(json.dumps(version['snapshot'],ensure_ascii=False,indent=2),encoding='utf-8')
            options={} if kind=='sci_draft' else {'school':{'include_toc':False}}
            export=self.post('actual-docx-'+kind,endpoint+'/versions/'+str(result['revision'])+'/exports',options)
            self.wait(export['task_id']);export=self.get(endpoint+'/exports/'+export['id'])
            (folder/'analysis.docx').write_bytes(self.check(self.client.get(export['download_url'])).content)
            pdf=self.post('actual-manuscript-pdf-'+kind,self.base+'/pdf-exports',dict(source_kind='manuscript_export',source_id=export['id'],request_key='b03-manuscript-pdf-'+kind))
            self.wait(pdf['task_id']);pdf=self.get(self.base+'/pdf-exports/'+pdf['id'])
            (folder/'analysis.pdf').write_bytes(self.check(self.client.get(pdf['download_url'])).content)
            materials=self.get(endpoint+'/versions/'+str(result['revision'])+'/writing-materials')
            assert materials['materials']['sources']
            published.append(dict(kind=kind,delivery_id=deliveries[kind],**result,export_id=export['id'],pdf_id=pdf['id']))
        self.record['writing']=dict(published=published,template_kind='synthetic engineering template; no real school compliance claim',real_model_calls=0)
        self.save()

    def english_revision(self):
        # Keep the first English output as evidence and publish an independent
        # renderer revision after deterministic system-wording localization.
        original=self.record['actions']['queue-report-en']['response']
        figure=self.record['actions']['queue-three-panel']['response']
        body=dict(title=original['content']['title'],language='en',finding_version_id=self.original['finding_version_id'],
            figure_version_ids=[figure['id']],root_id=original['root_id'],expected_revision=original['revision'])
        report=self.post('queue-report-en-v2',self.base+'/research-reports',body,kind='report')
        self.wait(report['task_id']);report=self.get(self.base+'/research-reports/'+report['id'])
        folder=control.RUNTIME/'queue-delivery/en-v2';self.download(report,folder)
        docx=next(m for m in report['members'] if m['role']=='docx')
        pdf=self.post('report-pdf-en-v2',self.base+'/pdf-exports',dict(source_kind='research_report',source_id=docx['id'],request_key='b03-queue-report-pdf-en-v2'))
        self.wait(pdf['task_id']);pdf=self.get(self.base+'/pdf-exports/'+pdf['id'])
        raw=self.check(self.client.get(pdf['download_url'])).content
        if hashlib.sha256(raw).hexdigest()!=pdf['sha256']:raise ValueError('PDF hash differs')
        (folder/'analysis.pdf').write_bytes(raw)
        if 'initial_outputs' not in self.record:self.record['initial_outputs']=dict(self.record['outputs'])
        self.record['outputs']['report_version_ids']=[report['id'] if identifier==original['id'] else identifier for identifier in self.record['outputs']['report_version_ids']]
        self.record['outputs']['report_directories']={report['id']:'en-v2'}
        self.record['english_revision']=dict(report_id=report['id'],revision=report['revision'],pdf_id=pdf['id'],prior_report_id=original['id'],old_outputs_retained=True)
        self.save()

    def package_revision(self):
        # A known terminal failure under an older renderer is retained. This is
        # an explicit new report revision, never a new-key retry of unknown work.
        prior=self.record['actions']['queue-pdf-package']['response']
        prior_task=self.get('/api/v1/tasks/'+prior['task_id'])
        if prior_task['status']!='failed':raise RuntimeError('Original package must be a confirmed terminal failure')
        body=dict(self.record['actions']['queue-pdf-package']['body'])
        body['expected_revision']=prior['revision']
        report=self.post('queue-pdf-package-new-renderer',self.base+'/research-reports',body,kind='report')
        self.wait(report['task_id']);report=self.get(self.base+'/research-reports/'+report['id'])
        self.download(report,control.RUNTIME/'queue-delivery/with-pdf-new-renderer')
        pdf=self.get(self.base+'/pdf-exports/'+body['include_pdf_id'])
        import zipfile
        with zipfile.ZipFile(control.RUNTIME/'queue-delivery/with-pdf-new-renderer/analysis_package.zip') as archive:
            assert hashlib.sha256(archive.read('analysis.pdf')).hexdigest()==pdf['sha256']
        self.record['outputs']=dict(figure_version_id=self.record['actions']['queue-three-panel']['response']['id'],
            report_version_ids=[self.record['actions']['queue-report-'+lang]['response']['id'] for lang in ('zh-CN','en')],
            packaged_report_version_id=report['id'],package_directory='with-pdf-new-renderer')
        self.record['package_revision']=dict(prior_report_id=prior['id'],prior_task=prior_task,report_id=report['id'],revision=report['revision'],old_materials_retained=True)
        self.save()

    def school_template(self):
        from docx import Document
        from docx.shared import Cm
        from uuid import uuid5,NAMESPACE_URL
        folder=control.RUNTIME/'school-fixture';folder.mkdir(exist_ok=True)
        path=folder/'CR-B03-合成学校模板.docx'
        if not path.exists():
            document=Document();section=document.sections[0];section.page_width=Cm(21);section.page_height=Cm(29.7)
            document.add_paragraph('CR-B03 合成工程模板；非客户学校正式规范。')
            for text in ('绪论','材料与方法','研究结果'):
                document.add_heading(text,1);document.add_paragraph('待研究人员填写，不生成身份、伦理或结论。')
            document.save(path)
        raw=path.read_bytes();cid=str(uuid5(NAMESPACE_URL,'cr-b03-school-fixture'))
        batch=self.post('school-upload-batch',self.base+'/file-batches',dict(items=[dict(client_id=cid,filename=path.name,size_bytes=len(raw))]))
        uploaded=self.record.get('school_upload')
        if uploaded is None:
            current=self.get(self.base+'/file-batches/'+batch['id']);item=next(i for i in current['items'] if i['id']==cid)
            if item.get('file_id'):
                detail=self.get(self.base+'/files/'+item['file_id']+'/details')
                uploaded=dict(file_id=item['file_id'],task=None)
                if detail.get('parse_status')!='parsed':raise RuntimeError('Retained school upload unfinished; inspect its task')
            else:uploaded=self.check(self.client.post(self.base+'/file-batches/'+batch['id']+'/items/'+cid,files={'file':(path.name,raw)})).json()
            self.record['school_upload']=uploaded;self.save()
        if uploaded.get('task'):self.wait(uploaded['task']['id'])
        template=self.post('school-template',self.base+'/school-templates',dict(name='CR-B03 合成学校模板',school='工程验收学校（非真实规范）',template_file_id=uploaded['file_id']))
        self.wait(template['task']['id'])
        ready=next(t for t in self.get(self.base+'/school-templates')['items'] if t['id']==template['id'])
        chapters=[dict(id='b03-introduction',title='绪论',level=1),dict(id='b03-methods',title='材料与方法',level=1),dict(id='b03-results',title='研究结果',level=1)]
        # The fixture is authored here; choose only its observed style option.
        decisions=[dict(conflict_id=c['id'],option_id=c['options'][0]['id']) for c in ready['analysis']['conflicts']]
        text_decisions=[dict(id=o['id'],choice='attributes' if 'attributes' in o['choices'] else o['choices'][0],source_sha256=o['source_sha256']) for o in ready['text_decision_options']]
        confirmation=self.post('school-confirm',self.base+'/school-templates/'+template['id']+'/confirm',dict(analysis_sha256=ready['analysis_sha256'],decisions=decisions,chapters=chapters,text_decisions=text_decisions))
        profile=self.get(self.base+'/thesis-profile')
        old=self.record['actions'].get('school-binding');body=old['body'] if old else dict(confirmation_id=confirmation['id'],expected_revision=profile['revision'])
        profile=self.post('school-binding',self.base+'/thesis-template-binding',body)
        purposes=['introduction','materials_and_methods','results']
        return dict(confirmation_id=confirmation['id'],profile_revision=profile['revision'],chapter_mappings=[dict(chapter_id=c['id'],purpose=p,output_language='project',result_group_ids=['research-results'] if p=='results' else []) for c,p in zip(chapters,purposes)])


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['outputs','writing','english_revision','package_revision'],default='outputs');args=parser.parse_args()
    run=Verification('writing' if args.phase=='writing' else 'outputs');getattr(run,args.phase)()
    print(json.dumps(run.record.get(args.phase,{}),ensure_ascii=False))


if __name__=='__main__':main()
