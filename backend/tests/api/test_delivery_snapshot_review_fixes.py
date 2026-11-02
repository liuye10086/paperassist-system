"""Four bounded W3 review counterexamples; no renderer, real package, or model."""
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
import pytest
from tests.api.test_delivery_snapshots import client,synthetic_capacity,setup_delivery
from app.db.database import database_connection


def post(client,path,body,key):return client.post(path,json=body,headers={'Idempotency-Key':key})


def test_br01_appended_evidence_does_not_rebind_frozen_attachment(client):
    base,path,body=setup_delivery(client);file_id=body['members'][0]['file_id']
    evidence=dict(file_id=file_id,source_kind='original',title='Fixed first declaration',intended_use='reference',original_data='unknown',limitations='External, not recomputed')
    first=post(client,base+'/external-evidence',evidence,'evidence-first');assert first.status_code==201,first.text
    saved=post(client,path+'/snapshots',body,'frozen-before-append').json();member=saved['members'][0]
    original=client.get(member['download_url']);assert original.status_code==200,original.text
    queued=post(client,path+'/snapshots/'+saved['id']+'/package',{},'frozen-source-task');assert queued.status_code==201,queued.text
    later=post(client,base+'/external-evidence',dict(evidence,title='Later declaration',previous_version_id=first.json()['id']),'evidence-later');assert later.status_code==201,later.text
    downloaded=client.get(member['download_url'])
    assert downloaded.status_code==200,downloaded.text
    assert downloaded.content==original.content and sha256(downloaded.content).hexdigest()==member['sha256']
    from app.adapters.task_store import DatasetTaskAssets
    from app.domain.delivery_packages.service import DeliveryService
    from app.core.config import get_data_dir
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(queued.json()['task_id'],)).fetchone()
        service=DeliveryService(DatasetTaskAssets(task['user_id'],db.config,get_data_dir()))
        payload=service.require_sources(db,task)
    assert payload['snapshot']['sha256']==saved['sha256'] and payload['raws']==[original.content]
    assert client.get(path+'/snapshots/'+saved['id']).json()['sha256']==saved['sha256']
    assert all(later.json()['id'] not in str(n) for n in payload['snapshot']['source_notices'])
    # Original bytes remain guarded, even though later declarations do not rebind history.
    from app.core.config import get_data_dir
    with database_connection() as db:key=db.execute('SELECT object_key FROM files WHERE id=%s',(file_id,)).fetchone()['object_key']
    target=get_data_dir()/key;target.write_bytes(target.read_bytes()+b'changed')
    assert client.get(member['download_url']).status_code==409


def test_br02_a_b_to_a_c_has_no_guessed_replacement(client):
    base,path,body=setup_delivery(client)
    from tests.api.test_projects import upload
    project=base.rsplit('/',1)[-1]
    second=upload(client,project).json()['file'];third=upload(client,project).json()['file']
    old_body=dict(body,members=[body['members'][0],dict(kind='file',file_id=second['id'])])
    first=post(client,path+'/snapshots',old_body,'members-a-b');assert first.status_code==201,first.text
    first=first.json();revision=dict(body,stage='revision',expected_revision=1,parent_snapshot_id=first['id'],members=[body['members'][0],dict(kind='file',file_id=third['id'])])
    next=post(client,path+'/snapshots',revision,'members-a-c');assert next.status_code==201,next.text
    next=next.json();old={m['selection']['file_id']:m['id'] for m in first['members']};new={m['selection']['file_id']:m['id'] for m in next['members']}
    assert next['changes']['added']==[new[third['id']]] and next['changes']['removed']==[old[second['id']]]
    assert next['changes']['replaced']==[],next['changes']


def tiny_pdf():
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 144] /Resources << >> >>']
    raw=b'%PDF-1.4\n';offsets=[]
    for i,obj in enumerate(objects,1):offsets.append(len(raw));raw+=str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start=len(raw);return raw+b'xref\n0 4\n0000000000 65535 f \n'+b''.join(f'{v:010d} 00000 n \n'.encode() for v in offsets)+b'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n'


def static_report(client,base,file_id,label):
    """Persist tiny declared bytes using existing publication, without executing a renderer."""
    finding=post(client,base+'/research-findings',dict(title=label,sources=[dict(source_kind='original_file',source_id=file_id)]),'finding-'+label).json()
    report=post(client,base+'/research-reports',dict(title=label,finding_version_id=finding['id']),'report-'+label).json()
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.adapters.task_store import DatasetTaskAssets
    from app.adapters.research_objects import ResearchObjects
    from app.domain.research_results.reports import ResearchReportService
    from app.domain.bioinformatics.contracts import canonical
    from app.core.config import get_data_dir
    repository=TaskExecutionStore();lease=repository.claim(report['task_id'],1,task_type='research_report');assert lease
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);assets=DatasetTaskAssets(task['user_id'],repository.config,get_data_dir());objects=ResearchObjects(assets.directory)
        raw=b'static DOCX-boundary fixture '+label.encode();record=objects.describe(report['id'],raw);objects.write(record,raw)
        member=dict(id=str(uuid4()),key='analysis',role='docx',format='docx',**record,properties={})
        manifest=dict(schema_version=1,members=[{k:v for k,v in member.items() if k!='object_key'}]);ref=objects.describe(report['id'],canonical(manifest),json=True);objects.write(ref,canonical(manifest))
        for obj in (member,ref):
            identifier=str(uuid4());db.execute("INSERT INTO storage_objects(id,namespace,object_key,size_bytes,sha256,state,scanned_at) VALUES(%s,'local:assets-v1',%s,%s,%s,'present',clock_timestamp())",(identifier,obj['object_key'],obj['size_bytes'],obj['sha256']))
            db.execute("INSERT INTO storage_references(object_id,project_id,owner_id,kind) VALUES(%s,%s,%s,'research_report')",(identifier,task['project_id'],task['user_id']))
        cp=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        assert ResearchReportService(assets).publish(db,task,cp,repository.now(db),dict(manifest_ref=ref,members=[member]),progress=lambda:None)['status']=='succeeded'
    return dict(report_id=report['id'],finding_id=finding['id'],member=member)


def test_br03_pdf_report_finding_participates_in_cross_member_consistency(client,monkeypatch):
    base,path,body=setup_delivery(client);file_id=body['members'][0]['file_id'];a=static_report(client,base,file_id,'A');b=static_report(client,base,file_id,'B')
    # The existing successful PDF download guard is a controlled boundary here;
    # this test targets only W3's cross-member research identity collection.
    from app.domain.pdf_exports.service import PdfExportService
    lookup={'pdf-a':a,'pdf-b':b}
    def row(self,db,project,identifier):
        item=lookup[identifier]
        return dict(source_kind='research_report',source_id=item['member']['id'],source_sha256=item['member']['sha256'],input_json=dict(source=dict(version=dict(id=item['report_id']),files=[dict(file_id=file_id)])))
    monkeypatch.setattr(PdfExportService,'row',row)
    monkeypatch.setattr(PdfExportService,'download',lambda self,project,identifier,**kw:(dict(filename='fixed.pdf',sha256=sha256(tiny_pdf()).hexdigest(),size_bytes=len(tiny_pdf())),tiny_pdf()))
    pdf_a=dict(kind='pdf_export',export_id='pdf-a');pdf_b=dict(kind='pdf_export',export_id='pdf-b')
    member_a=dict(kind='research_report_member',version_id=a['report_id'],member_id=a['member']['id']);member_b=dict(kind='research_report_member',version_id=b['report_id'],member_id=b['member']['id'])
    responses=[client.post(path+'/snapshots/preview',json=dict(body,members=members,required_formats=[])) for members in ([pdf_a,member_b],[pdf_a,pdf_b],[pdf_a,member_a])]
    assert [r.status_code for r in responses]==[409,409,200],[r.text for r in responses]
    proof=responses[2].json()['members'][0]['source_metadata']
    assert proof['report_version_id']==a['report_id'] and proof['finding_version_id']==a['finding_id']


def test_br04_confirmed_figure_number_preserves_image_quality_unknowns(client):
    base,path,body=setup_delivery(client);project=base.rsplit('/',1)[-1]
    from PIL import Image
    output=BytesIO();Image.new('RGB',(8,6)).save(output,format='PNG')
    from tests.api.test_file_batches import register
    batch_base,batch,item,raw=register(client,dict(id=project),output.getvalue(),'fixed.png','png-batch')
    uploaded=client.post(batch_base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':('fixed.png',raw)});assert uploaded.status_code==202,uploaded.text
    png=dict(id=uploaded.json()['file_id']);mapping=dict(figure_number='Figure 1',confirmed=True,panel_order=[],caption='Fixed original')
    request=dict(body,required_formats=['png'],members=[dict(kind='file',file_id=png['id'],figure_mapping=mapping)])
    saved=post(client,path+'/snapshots',request,'confirmed-number');assert saved.status_code==201,saved.text
    saved=saved.json()
    assert saved['completeness']=='quality_unresolved',saved
    for key in ('text_verification','font_verification','semantic_verification'):
        assert any(key in item for item in saved['quality_items']),saved['quality_items']
    assert not any('figure_mapping:' in item for item in saved['quality_items'])
    assert client.get(saved['members'][0]['download_url']).status_code==200
    batch_base,batch,item,raw=register(client,dict(id=project),tiny_pdf(),'figure.pdf','pdf-batch')
    pdf_upload=client.post(batch_base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':('figure.pdf',raw)});assert pdf_upload.status_code==202,pdf_upload.text
    pdf_request=dict(body,stage='revision',expected_revision=1,parent_snapshot_id=saved['id'],required_formats=['pdf'],members=[dict(kind='file',file_id=pdf_upload.json()['file_id'],figure_mapping=dict(mapping,confirmed=False))])
    preview=client.post(path+'/snapshots/preview',json=pdf_request);assert preview.status_code==200,preview.text
    assert preview.json()['completeness']=='quality_unresolved' and any('figure_mapping:' in q for q in preview.json()['quality_items'])
