from tests.api.test_projects import client,create_project
from tests.api.test_bio_insight_publication import create_run,synthetic_engine


def published(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.execution import run_bio_insight_task
    project,run=create_run(client,monkeypatch)
    result=run_bio_insight_task(run['task_id'],run['task_revision'],task_type='bio_result_import',engine=synthetic_engine,staging_directory=tmp_path/'insight-stage')
    assert result['status']=='succeeded',result
    base=f'/api/v1/projects/{project}'
    value=client.get(base+'/bio-insight-results/'+result['result_bio_insight_result_version_id']).json()
    member=next(m for m in value['members'] if m['key']=='comparison_results')
    return project,value,member


def test_insight_members_project_exact_raw_facts_into_findings_and_full_report_tables(client,monkeypatch,tmp_path):
    project,result,member=published(client,monkeypatch,tmp_path);base=f'/api/v1/projects/{project}'
    source=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],
        locator=dict(kind='row',table='comparison_results',row_key={'row_key':'g1'},column='p_value'))
    preview=client.post(base+'/research-results/preview',json={'sources':[source]})
    assert preview.status_code==200,preview.text
    catalog=preview.json()['catalogs'][0];facts=catalog['facts']
    assert len(facts)==1 and facts[0]['raw_value']=='0' and facts[0]['origin']=='external_result'
    assert facts[0]['locator']['row_key']=={'row_key':'g1'} and facts[0]['verification_status']=='unverified'
    assert catalog['limitations'] and catalog['methods']
    assert client.get(base+'/research-results/sources?source_kind=bio_insight_result_member').status_code==200
    wrong={**source,'sha256':'a'*64}
    assert client.post(base+'/research-results/preview',json={'sources':[wrong]}).status_code==409
    finding=client.post(base+'/research-findings',json={'title':'external exact fact','sources':[source],'selected_fact_ids':[facts[0]['id']],'expected_revision':0},headers={'Idempotency-Key':'insight-finding'})
    assert finding.status_code==201,finding.text
    value=finding.json();assert value['content']['facts'][0]['raw_value']=='0'
    from app.db.database import database_connection
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.domain.research_results.report_tables import collect_tables
    from app.domain.research_results.sources import ResearchSourceReader
    with database_connection() as db:owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
    reader=ResearchSourceReader(ProjectStore(get_data_dir(),owner_id=owner))
    with reader.store.connection() as db:tables,raws=collect_tables(reader,db,project,value['content']['sources'])
    table=next(t for t in tables if t['key']=='comparison_results')
    assert table['expected_rows']==2 and b'g2\tg2\t\t0.2' in raws[tables.index(table)]
    other=create_project(client)['id']
    assert client.post(f'/api/v1/projects/{other}/research-results/preview',json={'sources':[source]}).status_code==404


def test_member_locator_cannot_replace_table_values_or_select_ambiguous_rows(client,monkeypatch,tmp_path):
    project,result,member=published(client,monkeypatch,tmp_path);base=f'/api/v1/projects/{project}'
    source=dict(source_kind='bio_insight_result_member',source_id=member['id'],locator=dict(kind='row',table='comparison_results',row_key={'row_key':'missing'},column='p_value'))
    assert client.post(base+'/research-results/preview',json={'sources':[source]}).status_code==422
    source['locator']['row_key']={'row_key':'g2'}
    preview=client.post(base+'/research-results/preview',json={'sources':[source]})
    assert preview.status_code==200,preview.text
    assert preview.json()['catalogs'][0]['facts'][0]['verification_status']=='missing'
    source['raw_value']=999
    assert client.post(base+'/research-results/preview',json={'sources':[source]}).status_code==422


def test_bridge_report_exports_complete_table_and_typed_audit_passes(client,monkeypatch,tmp_path):
    import io,json
    from openpyxl import load_workbook
    from app.domain.research_results.execution import run_research_task
    from app.adapters.research_report_render import render_report
    project,result,member=published(client,monkeypatch,tmp_path);base=f'/api/v1/projects/{project}'
    source=dict(source_kind='bio_insight_result_member',source_id=member['id'],locator=dict(kind='row',row_key={'row_key':'g1'},column='p_value',table=member['key']))
    finding=client.post(base+'/research-findings',json=dict(title='external values',sources=[source]),headers={'Idempotency-Key':'report-finding'})
    assert finding.status_code==201,finding.text
    report=client.post(base+'/research-reports',json=dict(title='fixed external report',finding_version_id=finding.json()['id'],language='en'),headers={'Idempotency-Key':'bridge-report'})
    assert report.status_code==201,report.text
    report=report.json()
    done=run_research_task(report['task_id'],report['task']['revision'],task_type='research_report',engine=render_report,staging_directory=tmp_path/'report-stage')
    assert done['status']=='succeeded',done
    saved=client.get(base+'/research-reports/'+report['id'])
    assert saved.status_code==200,saved.text
    members=saved.json()['members'];xlsx=next(m for m in members if m['role']=='xlsx')
    workbook=load_workbook(io.BytesIO(client.get(xlsx['download_url']).content),read_only=True,data_only=False)
    try:
        tables=[list(sheet.values) for sheet in workbook.worksheets]
        selected=next(rows for rows in tables if rows and rows[0][:2]==('row_key','feature_id'))
        assert len(selected)==3 and selected[1][2]=='0' and selected[2][3]=='0.2'
    finally:workbook.close()
    from app.db.database import database_connection
    from app.maintenance.research_results_audit import audit_research_task_sources
    with database_connection() as db:
        assert audit_research_task_sources(db)[0]['invalid']==0


def test_new_insight_version_reports_impact_without_replacing_old_finding(client,monkeypatch,tmp_path):
    from tests.api.test_bio_insight_plans import import_plan
    from app.domain.bio_insights.execution import run_bio_insight_task
    project,result,member=published(client,monkeypatch,tmp_path);base=f'/api/v1/projects/{project}'
    source=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'])
    finding=client.post(base+'/research-findings',json=dict(title='frozen insight source',sources=[source]),headers={'Idempotency-Key':'old-finding'}).json()
    from app.db.database import database_connection
    with database_connection() as db:
        version=db.execute('SELECT plan_id FROM bio_insight_plan_versions WHERE id=%s',(result['plan_version_id'],)).fetchone()
    uploaded=client.get(base+'/bio-resource-files/requests/original-file').json()
    plan=client.post(base+'/bio-insight-plans/'+version['plan_id']+'/versions',json=import_plan(uploaded,'confirmed',1),headers={'Idempotency-Key':'new-version'})
    assert plan.status_code==201,plan.text
    plan=plan.json()
    run=client.post(base+'/bio-insight-runs',json=dict(plan_version_id=plan['id'],expected_plan_revision=2,source_digest=plan['source_digest']),headers={'Idempotency-Key':'new-version-run'}).json()
    done=run_bio_insight_task(run['task_id'],run['task_revision'],task_type='bio_result_import',engine=synthetic_engine,staging_directory=tmp_path/'new-stage')
    assert done['status']=='succeeded',done
    change=client.post(base+'/research-results/source-changes',json={'sources':[source]})
    assert change.status_code==200,change.text
    item=change.json()['items'][0]
    assert item['newer_version_id'] and item['automatic_replacement'] is False
    assert any(value['source_id']==finding['id'] for value in item['affected'])
    fixed=client.get(base+'/research-findings/'+finding['set_id']+'/versions/'+finding['id']).json()
    assert fixed['sha256']==finding['sha256']
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.domain.bio_insights.sources import InsightSourceReader
    with database_connection() as db:owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
    reader=InsightSourceReader(ProjectStore(get_data_dir(),owner_id=owner))
    new_result=client.get(base+'/bio-insight-results/'+done['result_bio_insight_result_version_id']).json()
    with reader.store.connection() as db:
        values=[reader.resolve(db,project,dict(source_kind='bio_insight_result_version',source_id=value['id'],sha256=value['manifest_sha256'],role='result')) for value in (result,new_result)]
    assert values[0]['metadata']['canonical_dataset_ids']==values[1]['metadata']['canonical_dataset_ids']==['original_file_sha256:'+uploaded['sha256']]


def test_published_b04_figure_member_is_reusable_in_b03_figure_panels(client,monkeypatch,tmp_path):
    import hashlib,json,io
    from pathlib import Path
    from PIL import Image
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.domain.research_results.execution import run_research_figure_task
    from app.adapters.research_figure_render import render_figure
    project,result,member=published(client,monkeypatch,tmp_path);base=f'/api/v1/projects/{project}'
    body=dict(name='synthetic figure lifecycle',kind='figure',decision='confirmed',expected_revision=0,
        sources=[dict(source_kind='bio_insight_result_version',source_id=result['id'],sha256=result['manifest_sha256'],role='result')],
        config=dict(kind='figure',result_source_id=result['id'],figure_type='volcano',formats=['png']))
    plan=client.post(base+'/bio-insight-plans',json=body,headers={'Idempotency-Key':'figure-plan'})
    assert plan.status_code==201,plan.text
    plan=plan.json();run=client.post(base+'/bio-insight-runs',json=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest']),headers={'Idempotency-Key':'figure-run'}).json()
    def image_engine(payload,output):
        from tests.domain.bio_insight_validation_fixtures import put,refresh,portable
        stream=io.BytesIO();Image.new('RGB',(160,80),'navy').save(stream,'PNG');content=stream.getvalue()
        path=Path(output)/'figure_png.png';path.write_bytes(content)
        artifact=dict(key='figure_png',format='png',role='figure',path=str(path.resolve()),size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
        methods={'method':'synthetic_image_lifecycle','config':payload['config'],'analysis_recomputed':False,
                 'upstream_inference_scopes':['external_result'],'data_driven_grouping':False}
        manifest=dict(schema_version=1,kind=payload['kind'],identity=payload['identity'],engine_version='bio_insights_v1.0.0',
            summary={'synthetic_lifecycle_fixture':True},methods=methods,provenance='system_computed',inference_scope='visualization',
            source_bindings=portable(payload['sources']),members=[])
        result=dict(_root=str(output),schema_version=1,status='completed',kind=payload['kind'],identity=payload['identity'],engine_version='bio_insights_v1.0.0',
            summary=manifest['summary'],methods=methods,provenance='system_computed',inference_scope='visualization',manifest=manifest,outputs=[artifact])
        for key,value in [('plot_data',{'synthetic_lifecycle_fixture':True}),('figure_metadata',methods),('methods',methods),('recipe',portable(payload)),('manifest',{})]:put(result,key,value)
        refresh(result);result.pop('_root');return result
    done=run_bio_insight_task(run['task_id'],run['task_revision'],task_type='bio_insight_figure',engine=image_engine,staging_directory=tmp_path/'figure-stage')
    assert done['status']=='succeeded',done
    figure=client.get(base+'/bio-insight-results/'+done['result_bio_insight_result_version_id']).json()
    panel=next(m for m in figure['members'] if m['format']=='png')
    preview=client.post(base+'/research-results/preview',json={'sources':[dict(source_kind='bio_insight_result_member',source_id=panel['id'],locator={'kind':'image'})]})
    assert preview.status_code==200,preview.text
    assert any('External values' in text for text in preview.json()['catalogs'][0]['limitations'])
    request=dict(mode='reuse',panels=[dict(source=dict(source_kind='bio_insight_result_member',source_id=panel['id'],sha256=panel['sha256'],locator={'kind':'image'}))],formats=['png'])
    created=client.post(base+'/research-figures',json=request,headers={'Idempotency-Key':'reuse-insight-figure'})
    assert created.status_code==201,created.text
    value=created.json();done=run_research_figure_task(value['task_id'],value['task']['revision'],engine=render_figure,staging_directory=tmp_path/'b03-stage')
    assert done['status']=='succeeded',done
    # Actual scoped DB chain: imported result -> figure plan -> run -> result
    # -> image member -> B03 figure. Querying either identity reaches all nodes.
    impact=client.get(base+'/bio-insight-results/'+result['id']+'/impact')
    assert impact.status_code==200,impact.text
    affected={(item['source_kind'],item['source_id']) for item in impact.json()['affected']}
    assert {('bio_insight_plan_version',plan['id']),('bio_insight_run',run['id']),
        ('bio_insight_result_version',figure['id']),('bio_insight_result_member',panel['id']),
        ('research_figure_version',value['id'])} <= affected
    changes=client.post(base+'/research-results/source-changes',json={'sources':[dict(source_kind='bio_insight_result_member',source_id=member['id'])]})
    assert changes.status_code==200,changes.text
    assert ('research_figure_version',value['id']) in {(v['source_kind'],v['source_id']) for v in changes.json()['items'][0]['affected']}


def test_result_impact_endpoint_scopes_version_and_member_dependencies(client,monkeypatch,tmp_path):
    project,result,member=published(client,monkeypatch,tmp_path)
    base=f'/api/v1/projects/{project}'
    source=dict(source_kind='bio_insight_result_member',source_id=member['id'])
    finding=client.post(base+'/research-findings',json=dict(title='impact member fact',sources=[source]),headers={'Idempotency-Key':'impact-finding'})
    assert finding.status_code==201,finding.text
    response=client.get(base+'/bio-insight-results/'+result['id']+'/impact')
    assert response.status_code==200,response.text
    impact=response.json()
    assert any(item['source_id']==finding.json()['id'] for item in impact['affected'])
    assert len({(item['source_kind'],item['source_id']) for item in impact['affected']})==len(impact['affected'])
    assert impact['automatic_replacement'] is False
    from app.db.database import database_connection
    from app.domain.research_results.source_changes import dependency_impact
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
        bounded=dependency_impact(db,project,owner,'bio_insight_result_version',result['id'],limit=2)
    assert bounded['affected_truncated'] and len(bounded['affected'])<=1
    other=create_project(client)['id']
    assert client.get(f'/api/v1/projects/{other}/bio-insight-results/'+result['id']+'/impact').status_code==404
