from tests.api.test_research_findings import client,selected_cell
from tests.api.test_reader_report_narratives import reader_policy


def test_new_report_requires_successful_reader_narrative(client):
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json={'title':'Fixed result','sources':[source]},
        headers={'Idempotency-Key':'reader-required-finding'}).json()
    response=client.post(base+'/research-reports',json={'title':'Fixed report','finding_version_id':finding['id']},
        headers={'Idempotency-Key':'reader-required-report'})
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='reader_report_narrative_required'


def test_report_freeze_passes_verified_caption_facts_from_a_different_source(client,tmp_path):
    from io import BytesIO
    from openpyxl import Workbook
    from app.adapters.research_figure_render import render_figure
    from app.db.database import database_connection
    from app.domain.research_results.contracts import ResearchReportRequest
    from app.domain.research_results.execution import run_research_figure_task
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from tests.api.test_projects import upload
    from tests.api.test_research_figure_publication import selected_image
    from tests.helpers.ocr_samples import ocr_result
    from tests.integration.test_research_validation_efficiency import report_service

    project,image_id=selected_image(client)
    base=f'/api/v1/projects/{project}'
    with database_connection() as db:
        parse=db.execute("SELECT id,revision FROM tasks WHERE project_id=%s AND task_type='parse_file'",(project,)).fetchone()
    assert run_parse_file_task(parse['id'],parse['revision'],parser=ocr_result)['status']=='succeeded'
    finding_file=upload(client,project)
    assert finding_file.status_code==201,finding_file.text
    finding_source=dict(source_kind='original_file',source_id=finding_file.json()['file']['id'],
        locator=dict(kind='cell',sheet='研究数据',cell='B2'))
    finding=client.post(base+'/research-findings',json=dict(title='Report finding',sources=[finding_source]),
        headers={'Idempotency-Key':'caption-separate-finding'})
    assert finding.status_code==201,finding.text

    table=Workbook()
    table.active.title='Sample counts'
    table.active.append(['Measure','Value'])
    table.active.append(['Number of samples',17])
    data=BytesIO()
    table.save(data)
    table.close()
    caption_file=upload(client,project,content=data.getvalue(),filename='panel-sample-counts.xlsx')
    assert caption_file.status_code==201,caption_file.text
    caption_source=dict(source_kind='original_file',source_id=caption_file.json()['file']['id'],
        locator=dict(kind='cell',sheet='Sample counts',cell='B2'))
    preview=client.post(base+'/research-results/preview',json=dict(sources=[caption_source]))
    assert preview.status_code==200,preview.text
    caption_fact=preview.json()['catalogs'][0]['facts'][0]
    assert caption_fact['raw_value']==17

    figure=client.post(base+'/research-figures',json=dict(mode='reuse',formats=['png'],caption='User note for this panel.',
        panels=[dict(source=dict(source_kind='original_file',source_id=image_id))],
        caption_sources=[caption_source],caption_fact_ids=[caption_fact['id']]),
        headers={'Idempotency-Key':'caption-separate-figure'})
    assert figure.status_code==201,figure.text
    result=run_research_figure_task(figure.json()['task_id'],figure.json()['task']['revision'],
        engine=render_figure,staging_directory=tmp_path/'stage')
    assert result and result['status']=='succeeded',result

    service=report_service(project)
    request=ResearchReportRequest(title='Report with separately sourced panel',finding_version_id=finding.json()['id'],
        figure_version_ids=[figure.json()['id']],language='en')
    with service.store.connection() as db:
        content,_,payload=service.freeze(db,project,request)
    assert [fact['raw_value'] for fact in content['finding']['content']['facts']]==[0]
    assert payload['figures'][0]['caption_facts']==[caption_fact]
    narrative_preview=client.post(base+'/research-report-narratives/preview',json=request.model_dump(mode='json'))
    assert narrative_preview.status_code==200,narrative_preview.text
    material=narrative_preview.json()
    assert [fact['value'] for fact in material['facts']['facts']]==[0]
    figure_material=material['figures'][0]
    assert [fact['raw_value'] for fact in figure_material['caption_facts']]==[17]
    assert figure_material['source_caption']=='User note for this panel.'


def test_report_task_freezes_and_publishes_complete_members_without_publishing_manuscript(client,tmp_path, research_reader_narrative):
    from app.domain.research_results.execution import run_research_task
    from app.adapters.research_report_render import render_report
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json={'title':'外部结果原值','sources':[source]},headers={'Idempotency-Key':'report-finding'}).json()
    body=dict(title='结果报告',finding_version_id=finding['id'],reader_narrative_id=research_reader_narrative)
    created=client.post(base+'/research-reports',json=body,headers={'Idempotency-Key':'report-one'})
    assert created.status_code==201,created.text
    value=created.json();assert value['members']==[]
    done=run_research_task(value['task_id'],value['task']['revision'],task_type='research_report',engine=render_report,staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded',done
    saved=client.get(base+'/research-reports/'+value['id']);assert saved.status_code==200,saved.text
    saved=saved.json();roles={m['role'] for m in saved['members']}
    assert {'docx','xlsx','methods','manifest','zip'}<=roles
    record=value['content']['reader_report']
    assert saved['content']['reader_report']==record
    assert saved['content']['finding']['content']['claims']==finding['content']['claims']
    assert saved['manifest']['reader_report_provenance']==record['provenance']
    for member in saved['members']:
        downloaded=client.get(member['download_url']);assert downloaded.status_code==200
        import hashlib
        assert hashlib.sha256(downloaded.content).hexdigest()==member['sha256']
    replay=client.post(base+'/research-reports',json=body,headers={'Idempotency-Key':'report-one'})
    assert replay.status_code==200 and replay.json()['id']==value['id']
    source_preview=client.post(base+'/research-results/preview',json={'sources':[{'source_kind':'research_report_version','source_id':value['id']}]})
    assert source_preview.status_code==200,source_preview.text
    from app.db.database import database_connection
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscripts WHERE project_id=%s',(base.rsplit('/',1)[-1],)).fetchone()['n']==0
    docx=next(m for m in saved['members'] if m['role']=='docx')
    # Document PDF creation is retired; the fixed DOCX remains available.
    pdf=client.post(base+'/pdf-exports',json={'source_kind':'research_report','source_id':docx['id'],'request_key':'report-pdf'})
    assert pdf.status_code==405,pdf.text
    pending=client.get(base+'/research-reports/'+value['id']).json()
    assert pending['manifest_sha256']==saved['manifest_sha256']


def test_report_refuses_changed_renderer_identity(client,tmp_path,monkeypatch, research_reader_narrative):
    from app.domain.research_results.execution import run_research_task
    from app.adapters import research_report_render as renderer
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json={'title':'固定结果','sources':[source]},headers={'Idempotency-Key':'identity-finding'}).json()
    report=client.post(base+'/research-reports',json={'title':'固定报告','finding_version_id':finding['id'], 'reader_narrative_id':research_reader_narrative},headers={'Idempotency-Key':'identity-report'}).json()
    identity=renderer.renderer_identity();identity['code_digest']='f'*64
    monkeypatch.setattr(renderer,'renderer_identity',lambda:identity)
    called=[]
    def engine(*args):called.append(True);raise AssertionError('must reject before rendering')
    result=run_research_task(report['task_id'],report['task']['revision'],task_type='research_report',engine=engine,staging_directory=tmp_path/'stage')
    assert result['status']=='failed' and not called
    saved=client.get(base+'/research-reports/'+report['id']).json()
    assert saved['members']==[] and saved['manifest_sha256'] is None


def test_published_report_checks_original_integrity_but_not_current_renderer(client,tmp_path,monkeypatch, research_reader_narrative):
    from app.domain.research_results.execution import run_research_task
    from app.adapters import research_report_render as renderer
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from pathlib import Path
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json={'title':'Fixed external result','sources':[source]},headers={'Idempotency-Key':'integrity-finding'}).json()
    report=client.post(base+'/research-reports',json={'title':'Fixed report','finding_version_id':finding['id'], 'reader_narrative_id':research_reader_narrative},headers={'Idempotency-Key':'integrity-report'}).json()
    done=run_research_task(report['task_id'],report['task']['revision'],task_type='research_report',engine=renderer.render_report,staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded'
    endpoint=base+'/research-reports/'+report['id']
    saved=client.get(endpoint).json();download=next(m['download_url'] for m in saved['members'] if m['role']=='docx')
    original_bytes=client.get(download).content
    from app.domain.reader_reports.service import ReaderReportService
    def unexpected_reader_access(*args,**kwargs):
        raise AssertionError('Historic downloads must only read the published bytes')
    monkeypatch.setattr(ReaderReportService,'record_for',unexpected_reader_access)
    identity=renderer.renderer_identity();identity['code_digest']='e'*64
    monkeypatch.setattr(renderer,'renderer_identity',lambda:identity)
    assert client.get(endpoint).status_code==200
    downloaded=client.get(download)
    assert downloaded.status_code==200 and downloaded.content==original_bytes
    with database_connection() as db:key=db.execute('SELECT object_key FROM files WHERE id=%s',(source['source_id'],)).fetchone()['object_key']
    original=Path(get_data_dir())/key;original.write_bytes(original.read_bytes()+b'changed-source')
    assert client.get(endpoint).status_code==409
    assert client.get(download).status_code==409
