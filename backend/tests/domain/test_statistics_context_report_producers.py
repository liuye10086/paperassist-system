"""Context report aliases accept only trusted formal or legacy producers."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def prepared(kind):
    from tests.domain.test_statistics_legacy_exports import fixed_word_task
    from app.domain.statistics_reader_reports.legacy_exports import POLICY,ADAPTER_VERSION,OUTPUT_POLICY
    from app.domain.bioinformatics.contracts import digest
    context=dict(id='context',content_sha256='a'*64)
    content=dict(language='en',finding={'content':{'sources':[dict(source_kind='statistics_report_context',
        source_id=context['id'],sha256=context['content_sha256'])]}})
    report=dict(id=kind+'-version',project_id='project',user_id='owner',task_id=kind+'-task',language='en',
        content_json=content,content_sha256=digest(content),manifest_object_id='manifest')
    if kind=='research_report':
        task=dict(id=report['task_id'],task_type=kind,status='succeeded',project_id='project',user_id='owner',
            input_snapshot={'report_version_id':report['id'],'content_sha256':report['content_sha256']},
            result_research_report_version_id=report['id'])
        return context,report,task,None
    task=fixed_word_task()
    task.update(id=report['task_id'],user_id='owner')
    if kind=='collection_word_report':
        snapshot=dict(project_id='project',collection_id='collection',collection_version_id='collection-version',output_language='en')
        snapshot['reader_export']=dict(policy=POLICY,adapter_version=ADAPTER_VERSION,output_policy=OUTPUT_POLICY,
            source_snapshot_sha256=digest(snapshot))
        task.update(task_type=kind,workflow_version='collection_word_report_v1',input_snapshot=snapshot,result_report_id=None)
    marker=task['input_snapshot']['reader_export']
    marker.update(context_id=context['id'],report_version_id=report['id'],content_sha256=report['content_sha256'])
    if kind=='collection_word_report':task['input_digest']=digest(task['input_snapshot'])
    binding=dict(id=task['id'],project_id='project',user_id='owner',**{key:marker[key] for key in (
        'context_id','report_version_id','policy','source_snapshot_sha256','content_sha256')},
        report_id='word' if kind=='word_report' else None,collection_report_id='collection-word' if kind=='collection_word_report' else None)
    return context,report,task,binding


def environment(entries):
    from app.adapters.research_results_store import invalid
    bindings={task['id']:binding for _,_,task,binding in entries if binding is not None}
    tasks={task['id']:task for _,_,task,_ in entries}
    reports=[report for _,report,_,_ in entries]
    class DB:
        def execute(self,sql,args):
            if 'FROM projects' in sql:self.rows=[dict(id='project',owner_id='owner')] if args==('project','owner') else []
            elif 'FROM statistics_legacy_report_exports' in sql:
                row=bindings.get(args[0]);self.rows=[row] if row and (row['project_id'],row['user_id'])==args[1:] else []
            elif sql.startswith('SELECT count(*)'):self.rows=[{'n':len(reports)}]
            elif 'FROM research_report_versions r WHERE' in sql:self.rows=reports
            else:raise AssertionError(sql)
            return self
        def fetchone(self):return self.rows[0] if self.rows else None
        def fetchall(self):return self.rows
    db=DB()
    @contextmanager
    def connection():yield db
    service=SimpleNamespace(assets=SimpleNamespace(owner_id='owner',db_config=object()),
        store=SimpleNamespace(user_id='owner',connection=connection,require_task=lambda db,identifier:tasks[identifier],
                              public_task=lambda task:dict(id=task['id'],task_type=task['task_type'])),
        verify_content=lambda report:report['content_json'],require=lambda *args:entries[0][0],
        checked_members=lambda db,project,report,**kwargs:(None,[dict(id=report['id']+'-'+role,role=role,format=role)
            for role in ('docx','xlsx','zip','methods')]))
    return db,service,bindings


@pytest.mark.parametrize('kind',('research_report','word_report','collection_word_report'))
@pytest.mark.parametrize('status',('queued','succeeded'))
def test_context_member_projection_retains_real_producer_and_three_published_roles(kind,status):
    from app.api.statistics_reader_reports import report_members
    entry=prepared(kind);context,report,task,_=entry;task['status']=status
    if status=='queued':
        task.update(result_report_id=None,result_research_report_version_id=None)
        report['manifest_object_id']=None
        if entry[3] is not None:entry[3].update(report_id=None,collection_report_id=None)
    db,service,_=environment([entry])
    actual,members=report_members(db,service,'project',context,report)
    assert actual['id']==task['id'] and actual['task_type']==kind
    assert [m['role'] for m in members]==(['docx','xlsx','zip'] if status=='succeeded' else [])


@pytest.mark.parametrize('kind',('word_report','collection_word_report'))
@pytest.mark.parametrize('tamper',('context','version','scope','compatibility'))
def test_legacy_context_alias_rejects_wrong_trusted_binding(kind,tamper):
    from app.api.statistics_reader_reports import report_members
    from app.domain.bioinformatics.contracts import digest
    from app.core.exceptions import StorageError
    entry=prepared(kind);context,report,task,binding=entry
    if tamper in ('context','version'):
        key='context_id' if tamper=='context' else 'report_version_id'
        binding[key]='another';task['input_snapshot']['reader_export'][key]='another'
        if kind=='collection_word_report':task['input_digest']=digest(task['input_snapshot'])
    elif tamper=='scope':binding['user_id']='another-owner'
    else:binding.update(report_id=None,collection_report_id=None)
    db,service,_=environment([entry])
    with pytest.raises(StorageError):report_members(db,service,'project',context,report)


@pytest.mark.parametrize('kind',('word_report','collection_word_report'))
def test_context_list_can_mix_formal_and_original_producers(monkeypatch,kind):
    from app.api import statistics_reader_reports as api
    entries=[prepared('research_report'),prepared(kind)]
    _,service,_=environment(entries)
    monkeypatch.setattr(api,'ResearchReportService',lambda store:service)
    result=api.reports('project','context',object(),page=1)
    assert result['total']==2
    assert [item['task']['task_type'] for item in result['items']]==['research_report',kind]
    for item in result['items']:
        assert len(item['members'])==3
        assert all(m['download_url'].startswith(f"/api/v1/projects/project/statistics-reader-reports/context/reports/{item['id']}/members/") for m in item['members'])
