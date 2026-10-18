"""Real schema2/en plans with saved v1 Chinese artifacts remain retrievable."""
from tests.helpers.statistics import statistics_post
from copy import deepcopy
from datetime import datetime,timezone
import pytest
from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_research_plan import confirm_research
from tests.adapters.test_analysis_plot_response import png


def save_legacy_artifacts(client):
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from tests.helpers.tasks import task_owner
    from app.adapters.explanation_store import ExplanationStore
    from app.adapters.report_store import ReportStore,digest
    from app.adapters.report_docx import build_report
    from app.domain.boxplot import plot_data
    from app.domain.external_processing import disclosure,freeze_confirmation
    from app.domain.external_material import explanation_material
    from app.domain.explanation_content import render_explanation,LIMITATIONS
    from tests.domain.test_explanation_content import valid_draft
    base,file,_,_,_=confirm_research(client)
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    assert result['schema_version']==2 and result['analysis_context']['plan']['research_request']['output_language']=='en'
    project_id=base.split('/')[4]; store=ProjectStore(get_data_dir(),owner_id=task_owner(client))
    legacy={key:value for key,value in result.items() if key not in ('schema_version','analysis_context')}
    figure={**plot_data(legacy,[1.,5.,7.,9.],{'A':[1.,5.],'B':[7.,9.]}), 'source':result['source'],
        'created_at':datetime.now(timezone.utc).isoformat(),'engine':{'id':'openai_boxplot_v1','provider':'openai_code_interpreter','model':'synthetic'},
        'provenance':{'model':'synthetic'},'verification':{'status':'matched','note':'历史核对'}}
    figure=store.save_figure(project_id,file['id'],figure,png())
    snap={'result':legacy,'figure':figure,'source':result['source'],'file':file,'output_language':'zh-CN'}
    preview=disclosure(snap,'explanation',store.owner_id)
    external=freeze_confirmation(snap,'explanation',store.owner_id,{'version':3,'confirmed':True,'source_digest':preview['source_digest'],
        'labels':{item['key']:item['value'] for item in preview['labels']}})
    payload,_=explanation_material(result,figure,external)
    explanation={'analysis_run_id':result['id'],'figure_id':figure['id'],'figure_sha256':figure['sha256'],
        'source_sha256':result['source_sha256'],'source':result['source'],'setup_revision':1,'language':'zh-CN',
        'created_at':datetime.now(timezone.utc).isoformat(),'sections':render_explanation(valid_draft(payload),payload),'limitations':LIMITATIONS,
        'engine':{'id':'analysis_explanation_v1','provider':'openai','model':'synthetic'},'verification':{'status':'references_checked','note':'历史核对'},
        'provenance':{'model':'synthetic','input_sha256':digest(payload),'external_processing':external}}
    explanation=ExplanationStore(store).save(project_id,file['id'],explanation)
    project=store.project(project_id)
    snapshot={'project':{key:project[key] for key in ('id','name','research_topic','project_type','created_at')},
        'result':result,'figure':figure,'explanation':explanation,'source':result['source']}
    metadata=ReportStore.metadata(snapshot)
    report,_=ReportStore(store).save(snapshot,metadata,build_report(snapshot,metadata,png()))
    return base,result,figure,explanation,report,store


def test_saved_legacy_english_plan_artifacts_are_read_without_generation_cache_hit(client):
    from app.adapters.report_store import ReportStore
    base,result,figure,explanation,report,store=save_legacy_artifacts(client)
    url=base+'/analysis-runs/'+result['id']
    original_word=ReportStore(store).content(report)
    assert client.get(url+'/boxplot/image').content==png()
    plot=client.get(url+'/boxplot').json()
    assert plot['figure']['id']==figure['id'] and plot['generation_compatible'] is False
    old_explanation=client.get(url+'/explanation').json()
    assert old_explanation['explanation']['id']==explanation['id'] and old_explanation['generation_compatible'] is False
    old_report=client.get(url+'/report').json()
    assert old_report['report']['id']==report['id'] and old_report['generation_compatible'] is False
    assert client.get(url+'/report/'+report['id']+'/download').content==original_word
    from app.domain.plot_tasks import context
    from app.domain.explanations import context as explanation_context
    assert context(base.split('/')[4],result['file_id'],result['id'],store)[1]['figure'] is None
    assert explanation_context(store,base.split('/')[4],result['file_id'],result['id'])[1] is None
    assert client.post(url+'/explanation',json={'expected_revision':1,'figure_id':figure['id']}).status_code==409
    assert client.post(url+'/report',json={'expected_revision':1,'figure_id':figure['id'],'explanation_id':explanation['id']}).status_code==409
    assert ReportStore(store).content(report)==original_word
