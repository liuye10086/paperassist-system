"""Retired PDF creation, shared Word sources and immutable historical reads."""
from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_pdf_routes_only_expose_historical_reads():
    from app.api.pdf_exports import router
    assert [(r.path, r.methods) for r in router.routes] == [
        ('/api/v1/projects/{project_id}/pdf-exports', {'GET'}),
        ('/api/v1/projects/{project_id}/pdf-exports/{export_id}', {'GET'}),
        ('/api/v1/projects/{project_id}/pdf-exports/{export_id}/download', {'GET'})]


def test_pdf_service_has_no_creation_or_retry():
    from app.domain.pdf_exports.service import PdfExportService
    assert not hasattr(PdfExportService, 'create')
    assert not hasattr(PdfExportService, 'retry')


def test_new_report_rejects_pdf_while_frozen_request_is_readable():
    from app.domain.research_results.contracts import ResearchReportRequest, FrozenResearchReportRequest
    body=dict(title='Report',finding_version_id='finding',include_pdf_id='old-pdf')
    with pytest.raises(ValidationError):ResearchReportRequest.model_validate(body)
    assert FrozenResearchReportRequest.model_validate(body).include_pdf_id=='old-pdf'


def test_new_figure_rejects_pdf_while_frozen_config_is_readable():
    from app.domain.research_results.contracts import ResearchFigureRequest, FrozenResearchFigureRequest
    body=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id='file'))],formats=['pdf'])
    with pytest.raises(ValidationError):ResearchFigureRequest.model_validate(body)
    assert FrozenResearchFigureRequest.model_validate(body).formats==['pdf']


def test_new_delivery_rejects_pdf_while_frozen_selection_is_readable():
    from app.domain.delivery_packages.contracts import SnapshotWrite,Selection
    body=dict(stage='first',expected_revision=0,requirement_version_id='r',change_note='fixed',opinion_round='first',members=[dict(kind='pdf_export',export_id='old')])
    with pytest.raises(ValidationError):SnapshotWrite.model_validate(body)
    assert Selection.model_validate(body['members'][0]).export_id=='old'


def test_layout_and_historical_pdf_use_same_docx_reader(monkeypatch,tmp_path):
    from app.domain.docx_sources import DocxSourceReader
    from app.domain.pdf_exports.service import PdfExportService
    from app.domain.layout_exports.service import LayoutExportService
    assets=SimpleNamespace(owner_id='user',db_config=None,directory=tmp_path)
    calls=[]
    def source(self,*args,**kw):calls.append((args,kw));return {'fixed':'docx'},b'PK'
    monkeypatch.setattr(DocxSourceReader,'source',source)
    assert PdfExportService(assets).source('db','project','report','fixed')==({'fixed':'docx'},b'PK')
    assert LayoutExportService(assets).source('db','project','report','fixed')==({'fixed':'docx'},b'PK')
    assert calls==[(('db','project','report','fixed'),{}),(('db','project','report','fixed'),{})]


def test_historical_pdf_row_keeps_project_and_owner_scope(tmp_path):
    from app.domain.pdf_exports.service import PdfExportService
    from app.core.exceptions import StorageError
    service=PdfExportService(SimpleNamespace(owner_id='owner',db_config=None,directory=tmp_path))
    checked=[]
    service.store.require_project=lambda db,project:checked.append(project)
    class DB:
        def execute(self,sql,params):
            assert 'project_id=%s AND user_id=%s' in sql
            assert params==('pdf','project','owner')
            return SimpleNamespace(fetchone=lambda:None)
    with pytest.raises(StorageError) as error:service.row(DB(),'project','pdf')
    assert error.value.code=='pdf_export_not_found' and checked==['project']


def test_historical_download_checks_fixed_source_and_pdf_bytes(monkeypatch,tmp_path):
    from app.domain.pdf_exports.service import PdfExportService
    from app.core.exceptions import StorageError
    raw=b'%PDF-frozen';identity=str(uuid4());name=identity+'-'+str(uuid4())+'.pdf'
    metadata=dict(object_name=name,sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
    row=dict(id=identity,metadata_json=metadata)
    service=PdfExportService(SimpleNamespace(owner_id='owner',db_config=None,directory=tmp_path))
    service.directory.mkdir();(service.directory/name).write_bytes(raw)
    @contextmanager
    def connection():yield 'db'
    service.store.connection=connection
    service.row=lambda db,project,identifier:row
    service.view=lambda db,saved:dict(status='succeeded')
    verified=[]
    service.verify_source=lambda db,saved,**kw:verified.append(saved)
    assert service.download('project',identity)==(metadata,raw)
    assert verified==[row]
    (service.directory/name).write_bytes(b'changed')
    with pytest.raises(StorageError) as error:service.download('project',identity)
    assert error.value.code=='report_changed'


@pytest.mark.parametrize('family',['report','figure'])
def test_new_delivery_rejects_generated_pdf_member_before_reading_bytes(monkeypatch,family,tmp_path):
    from app.domain.delivery_packages import sources
    from app.domain.delivery_packages.contracts import Selection
    from app.core.exceptions import StorageError
    class Phase:
        def __init__(self,*args):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(sources,'VerificationPhase',Phase)
    monkeypatch.setattr(sources.ResearchSourceReader,'_read_source_in_phase',lambda *a,**kw:SimpleNamespace(source_file_ids=[],content={},sha256='a'*64))
    class DB:
        def execute(self,sql,params):return SimpleNamespace(fetchone=lambda:dict(id='member',format='pdf',**{family+'_version_id':'version'}))
    service=SimpleNamespace(assets=SimpleNamespace(owner_id='owner',db_config=None,directory=tmp_path),store=SimpleNamespace(user_id='owner'))
    selection=Selection(kind='research_'+family+'_member',version_id='version',member_id='member')
    with pytest.raises(StorageError) as error:sources.resolve_members(service,DB(),'project',{},[selection],'complete')
    assert error.value.code=='research_source_unsupported'


def test_old_pdf_tasks_cannot_be_claimed_or_mutated(monkeypatch):
    from app.adapters import task_execution_store as module
    monkeypatch.setattr(module,'ensure_schema_current',lambda db:None)
    statements=[]
    class DB:
        def execute(self,sql,params):
            statements.append(sql)
            return SimpleNamespace(fetchone=lambda:dict(task_type='pdf_export',revision=1))
    @contextmanager
    def connection(**kw):yield DB()
    repository=module.TaskExecutionStore.__new__(module.TaskExecutionStore);repository.connection=connection
    assert repository.claim('old-task',1,task_type='pdf_export') is None
    assert statements==['SELECT * FROM tasks WHERE id=%s']


@pytest.mark.parametrize('tamper',[None,'task_owner','source_id'])
def test_historical_pdf_binding_is_still_checked(tmp_path,tamper):
    from app.domain.pdf_exports.service import PdfExportService
    from app.domain.literature.service import digest
    from app.core.exceptions import StorageError
    source=dict(source_kind='report',source_id='fixed',source_sha256='a'*64,renderer_identity={'old':'manifest'},project_id='project',workflow_version='pdf_export_v1')
    row=dict(id='export',task_id='task',project_id='project',user_id='owner',source_kind='report',source_id='fixed',source_sha256='a'*64,renderer_identity={'old':'manifest'},report_id='fixed',parent_export_id=None,input_json=source,input_sha256=digest(source),request_digest=digest(dict(source_kind='report',source_id='fixed',parent_export_id=None)))
    snapshot=dict(export_id='export',**source)
    task=dict(task_type='pdf_export',workflow_version='pdf_export_v1',project_id='project',user_id='owner',input_snapshot=snapshot,input_digest=digest(snapshot))
    service=PdfExportService(SimpleNamespace(owner_id='owner',db_config=None,directory=tmp_path));service.store.require_task=lambda db,identifier:task
    if tamper=='task_owner':task['user_id']='other'
    if tamper=='source_id':row['source_id']='newer'
    if tamper:
        with pytest.raises(StorageError):service.verify('db',row)
    else:assert service.verify('db',row)==task


@pytest.mark.parametrize('old',[False,True])
def test_report_replay_uses_explicit_snapshot_pdf_policy(monkeypatch,tmp_path,old):
    from app.domain.research_results import reports
    from app.adapters import research_report_render
    from app.domain.literature.service import digest
    content={'included_pdf':None}
    snapshot=dict(report_version_id='report',content_sha256=digest(content),renderer_identity={'old':'fixed'},request=dict(title='Fixed',finding_version_id='finding'))
    if not old:snapshot['output_policy']='no_generated_pdf_v1'
    task=dict(id='task',project_id='project',input_snapshot=snapshot)
    row=dict(task_id='task',content_json=content,content_sha256=digest(content))
    service=reports.ResearchReportService(SimpleNamespace(owner_id='owner',db_config=None,directory=tmp_path))
    service.require=lambda *a:row
    monkeypatch.setattr(reports,'require_phase',lambda *a:None)
    monkeypatch.setattr(reports,'input_version',lambda *a:None)
    monkeypatch.setattr(research_report_render,'renderer_identity',lambda:{'old':'fixed'})
    policies=[]
    def freeze(*args,**kwargs):policies.append(kwargs['legacy_content']);return content,[],{}
    service._freeze_in_phase=freeze
    assert service._require_sources_in_phase('db',task,phase='phase')['snapshot']==content
    assert policies==[old]


@pytest.mark.parametrize('kind',['figure','report'])
def test_frozen_models_cannot_bypass_new_creation_validation(tmp_path,kind):
    from app.domain.research_results.contracts import FrozenResearchFigureRequest,FrozenResearchReportRequest
    from app.domain.research_results.figures import ResearchFigureService
    from app.domain.research_results.reports import ResearchReportService
    assets=SimpleNamespace(owner_id='owner',db_config=None,directory=tmp_path)
    if kind=='figure':
        request=FrozenResearchFigureRequest(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id='file'))],formats=['pdf'])
        service=ResearchFigureService(assets)
    else:
        request=FrozenResearchReportRequest(title='Fixed',finding_version_id='finding',include_pdf_id='old')
        service=ResearchReportService(assets)
    def connection(**kwargs):raise AssertionError('must reject before opening a write transaction')
    service.store.connection=connection
    with pytest.raises(ValidationError):service.create('project',request,'new-request')


@pytest.mark.parametrize('historical',[False,True])
def test_report_package_omits_generated_pdf_only_under_new_policy(monkeypatch,tmp_path,historical):
    from app.domain.research_results import reports,statistics_package
    from app.domain.research_results.contracts import ResearchReportRequest
    assets=SimpleNamespace(owner_id='owner',db_config=None,directory=tmp_path)
    service=reports.ResearchReportService(assets)
    finding={'claims':[],'sources':[]}
    members=[dict(id=fmt,key='figure_'+fmt,format=fmt,role='figure',sha256=sha256(fmt.encode()).hexdigest(),size_bytes=len(fmt)) for fmt in ('png','pdf')]
    figure=dict(task={'status':'succeeded'},config={'formats':['png','pdf']},manifest_sha256='a'*64,members=members)
    def require(db,table,project,identifier):
        if table=='research_finding_versions':return {'id':'finding','content_sha256':'a'*64}
        return dict(next(m for m in members if m['id']==identifier),figure_version_id='figure',storage_object_id=identifier)
    service.require=require;service.verify_content=lambda row:finding
    monkeypatch.setattr(reports,'require_phase',lambda *a:None)
    monkeypatch.setattr(reports.ResearchSourceReader,'_read_source_in_phase',lambda *a,**kw:SimpleNamespace(content=finding))
    monkeypatch.setattr(reports.ResearchFindingService,'format_view',staticmethod(lambda row,content:dict(content=content)))
    monkeypatch.setattr(reports.ResearchFigureService,'_get_in_phase',lambda *a,**kw:figure)
    monkeypatch.setattr(reports,'scoped_object',lambda db,project,owner,identifier:dict(next(m for m in members if m['id']==identifier),raw=identifier.encode()))
    monkeypatch.setattr(reports.ResearchObjects,'read',lambda self,obj:obj['raw'])
    monkeypatch.setattr(reports,'_collect_tables_in_phase',lambda *a,**kw:([],[]))
    monkeypatch.setattr(statistics_package,'statistics_reproduction_files',lambda sources:[])
    request=ResearchReportRequest(title='Fixed',finding_version_id='finding',figure_version_ids=['figure'])
    content,_,payload=service._freeze_in_phase('db','project',request,phase='phase',legacy_content=historical)
    names=[f['name'] for f in payload['package_files']]
    assert names==(['figures/figure_01/figure_png.png','figures/figure_01/figure_pdf.pdf'] if historical else ['figures/figure_01/figure_png.png'])
    assert ('included_pdf' in content)==historical
