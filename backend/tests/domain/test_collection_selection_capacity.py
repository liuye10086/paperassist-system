"""Pure composition checks; saved source I/O is a boundary, no database/assets."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.core.exceptions import StorageError
from app.core.errors import error_detail
from app.domain.manuscripts import collection_selection
from app.domain.manuscripts.contracts import ManuscriptRequest

@pytest.fixture(autouse=True)
def postgres_schema():yield None


def saved_packet(monkeypatch,count,different_runs):
    items=[dict(file_id='file',analysis_run_id='run-'+str((i+5)%count) if different_runs else 'run-shared',
        figure_id='figure-'+str(i),caption='Saved caption '+str(i),figure_number=i+1) for i in range(count)]
    report=dict(kind='collection_report',id='report',file_id='file',role='user_results',label='Saved collection',sha256='c'*64,
        download_url=None,content=dict(items=items,text='Saved report body',text_truncated=False))
    catalog={('collection_report','report'):report}
    for item in items:
        catalog[('analysis_run',item['analysis_run_id'])]=dict(kind='analysis_run',id=item['analysis_run_id'],file_id='file',role='computed_results',label=item['analysis_run_id'],sha256='a'*64,download_url=None,content=dict(id=item['analysis_run_id'],setup_revision=1))
        catalog[('figure',item['figure_id'])]=dict(kind='figure',id=item['figure_id'],file_id='file',role='image_observation',label=item['figure_id'],sha256='b'*64,download_url=None,content=dict(analysis_run_id=item['analysis_run_id']))
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda *_:SimpleNamespace(fetchone=lambda:dict(input_json=dict(items=[dict(result=dict(file_id='file'))]))))
    service=SimpleNamespace(store=SimpleNamespace(connection=connection),require_project=lambda *_:dict(project_type='sci'))
    calls=[]
    def read(_service,project,selection):
        assert project=='project' and selection['file_id']=='file'
        calls.append((selection['kind'],selection['id']))
        return deepcopy(catalog[(selection['kind'],selection['id'])])
    monkeypatch.setattr(collection_selection,'read_source',read)
    request=dict(collection_id='collection',collection_version_id='version',report_id='report')
    return service,request,items,report,catalog,calls


@pytest.mark.parametrize('count,different_runs,source_count',[(21,False,23),(21,True,43),(30,False,32)])
def test_collection_uses_one_ordered_group_within_existing_manuscript_contract(monkeypatch,count,different_runs,source_count):
    service,request,items,report,catalog,calls=saved_packet(monkeypatch,count,different_runs)
    packet=collection_selection.select(service,'project',request)
    runs=list(dict.fromkeys(item['analysis_run_id'] for item in items))
    assert len(packet['sources'])==source_count and packet['sources'][-1]==report
    assert len(packet['results_groups'])==1 and packet['results_groups'][0]['id']=='collection-version'
    group=packet['results_groups'][0]
    assert group['analysis_run_ids']==runs==packet['analysis_run_ids']
    assert group['figure_ids']==[item['figure_id'] for item in items]
    assert packet['figure_notes']==[dict(figure_id=item['figure_id'],caption=item['caption'],panels=[]) for item in items]
    expected=[];seen=set()
    for item in items:
        if item['analysis_run_id'] not in seen:expected.append(catalog[('analysis_run',item['analysis_run_id'])]);seen.add(item['analysis_run_id'])
        expected.append(catalog[('figure',item['figure_id'])])
    assert packet['sources']==expected+[report]
    assert calls.count(('analysis_run',runs[0]))==1
    assert collection_selection.select(service,'project',request)==packet
    input=dict(title='Synthetic collection handoff',output_language='en',sources=[{k:s[k] for k in ('kind','id','file_id','role')} for s in packet['sources']],results_groups=packet['results_groups'],figure_notes=packet['figure_notes'],analysis_handoff_run_ids=runs)
    assert ManuscriptRequest.model_validate(input).results_groups[0].figure_ids==group['figure_ids']
    if root:=os.environ.get('PAPERASSIST_BIII_EVIDENCE_DIR'):
        destination=Path(root)/(str(count)+('-unique' if different_runs else '-same')+'.json')
        destination.write_text(json.dumps(dict(boundary='pure_composition_no_database_or_artifact_IO',input=input,packet=packet),ensure_ascii=False,indent=2),encoding='utf8')


def test_genuine_source_overflow_is_a_clear_input_limit_not_source_conflict(monkeypatch):
    service,request,*_=saved_packet(monkeypatch,25,True)
    with pytest.raises(StorageError) as caught:collection_selection.select(service,'project',request)
    assert caught.value.status==422 and caught.value.code=='manuscript_source_limit'
    detail=error_detail(caught.value.code,caught.value.message)
    assert detail['code']=='manuscript_source_limit' and '50' in detail['message']
