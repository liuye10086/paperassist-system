from tests.api.test_research_findings import client,selected_cell


def test_report_task_freezes_and_publishes_complete_members_without_publishing_manuscript(client,tmp_path):
    from app.domain.research_results.execution import run_research_task
    from app.adapters.research_report_render import render_report
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json={'title':'外部结果原值','sources':[source]},headers={'Idempotency-Key':'report-finding'}).json()
    body=dict(title='结果报告',finding_version_id=finding['id'])
    created=client.post(base+'/research-reports',json=body,headers={'Idempotency-Key':'report-one'})
    assert created.status_code==201,created.text
    value=created.json();assert value['members']==[]
    done=run_research_task(value['task_id'],value['task']['revision'],task_type='research_report',engine=render_report,staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded',done
    saved=client.get(base+'/research-reports/'+value['id']);assert saved.status_code==200,saved.text
    saved=saved.json();roles={m['role'] for m in saved['members']}
    assert {'docx','xlsx','methods','manifest','zip'}<=roles
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
    # PDF is a separate public task over the exact successful DOCX member.
    pdf=client.post(base+'/pdf-exports',json={'source_kind':'research_report','source_id':docx['id'],'request_key':'report-pdf'})
    assert pdf.status_code==201,pdf.text
    assert pdf.json()['source_sha256']==docx['sha256'] and pdf.json()['status']=='queued'
    pending=client.get(base+'/research-reports/'+value['id']).json()
    assert pending['manifest_sha256']==saved['manifest_sha256']


def test_report_refuses_changed_renderer_identity(client,tmp_path,monkeypatch):
    from app.domain.research_results.execution import run_research_task
    from app.adapters import research_report_render as renderer
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json={'title':'固定结果','sources':[source]},headers={'Idempotency-Key':'identity-finding'}).json()
    report=client.post(base+'/research-reports',json={'title':'固定报告','finding_version_id':finding['id']},headers={'Idempotency-Key':'identity-report'}).json()
    identity=renderer.renderer_identity();identity['code_digest']='f'*64
    monkeypatch.setattr(renderer,'renderer_identity',lambda:identity)
    called=[]
    def engine(*args):called.append(True);raise AssertionError('must reject before rendering')
    result=run_research_task(report['task_id'],report['task']['revision'],task_type='research_report',engine=engine,staging_directory=tmp_path/'stage')
    assert result['status']=='failed' and not called
    saved=client.get(base+'/research-reports/'+report['id']).json()
    assert saved['members']==[] and saved['manifest_sha256'] is None


def test_published_report_checks_original_integrity_but_not_current_renderer(client,tmp_path,monkeypatch):
    from app.domain.research_results.execution import run_research_task
    from app.adapters import research_report_render as renderer
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from pathlib import Path
    base,source=selected_cell(client)
    finding=client.post(base+'/research-findings',json={'title':'Fixed external result','sources':[source]},headers={'Idempotency-Key':'integrity-finding'}).json()
    report=client.post(base+'/research-reports',json={'title':'Fixed report','finding_version_id':finding['id']},headers={'Idempotency-Key':'integrity-report'}).json()
    done=run_research_task(report['task_id'],report['task']['revision'],task_type='research_report',engine=renderer.render_report,staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded'
    endpoint=base+'/research-reports/'+report['id']
    saved=client.get(endpoint).json();download=next(m['download_url'] for m in saved['members'] if m['role']=='docx')
    identity=renderer.renderer_identity();identity['code_digest']='e'*64
    monkeypatch.setattr(renderer,'renderer_identity',lambda:identity)
    assert client.get(endpoint).status_code==200
    assert client.get(download).status_code==200
    with database_connection() as db:key=db.execute('SELECT object_key FROM files WHERE id=%s',(source['source_id'],)).fetchone()['object_key']
    original=Path(get_data_dir())/key;original.write_bytes(original.read_bytes()+b'changed-source')
    assert client.get(endpoint).status_code==409
    assert client.get(download).status_code==409
