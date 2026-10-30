"""Review corrections exercise real service gates with no environment or DB reads."""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def postgres_schema(monkeypatch):
    import dotenv
    def forbidden(*a,**k):raise AssertionError('No dotenv file reads in pure mapping tests')
    monkeypatch.setattr(dotenv,'dotenv_values',forbidden)
    import app.core.config
    monkeypatch.setattr(app.core.config,'dotenv_values',forbidden)
    yield None


def fixture(variant='A'):
    from tests.adapters.test_school_front_matter import configured
    from app.domain.manuscripts.school_export import compile_school_export
    from app.domain.literature.service import digest
    snapshot,analysis,front=configured();context=snapshot['thesis_context']
    analysis.update(conflicts=[],rules=deepcopy(context['confirmation']['rules']),missing=deepcopy(context['confirmation']['missing']),unsupported=deepcopy(context['confirmation']['unsupported']))
    acknowledgement=dict(id='ack',title='Synthetic acknowledgements',level=1,purpose='acknowledgements',output_language='en',result_group_ids=[])
    context['chapters'].append(acknowledgement)
    context['confirmation']['chapters'].append({k:acknowledgement[k] for k in ('id','title','level')})
    snapshot['sections'].append(acknowledgement|dict(paragraphs=[dict(id='school:ack:pending',text='Pending user content',citations=[],source_ids=[])]))
    front['content_requirements'].append(dict(id='ack',kind='acknowledgements',required=True,chapter_id='ack',source_id=front['fields'][0]['source_id']))
    if variant=='B':
        front['fields'][0].update(id='category',label='Synthetic paper category')
        front['fields'].reverse()
    context['confirmation']['analysis_sha256']=digest(analysis)
    context['confirmation_sha256']=digest(context['confirmation'])
    options=dict(manual_fields={},manual_chapters=[],english_title='',keywords=[],include_toc=False,toc_depth=3,field_values={})
    return dict(snapshot=snapshot,analysis=analysis,plan=compile_school_export(snapshot,analysis,options),**{'confirm-payload':dict(analysis_sha256=digest(analysis),decisions=[],chapters=context['confirmation']['chapters'],front_matter=front)})


class ReadOnlyDB:
    def __init__(self,saved=None):self.saved=saved;self.writes=[]
    def execute(self,sql,args=()):
        if not sql.lstrip().upper().startswith('SELECT'):
            self.writes.append(sql)
            raise AssertionError('Invalid mapping reached immutable persistence boundary')
        self.result=self.saved if 'FROM school_template_confirmations WHERE id=' in sql else None
        return self
    def fetchone(self):return self.result


def test_conflicting_content_kinds_rejected_before_immutable_confirmation_insert():
    from app.core.exceptions import StorageError
    from app.domain.school_templates.contracts import ConfirmRequest
    from app.domain.school_templates.service import SchoolTemplateService
    data=fixture();payload=deepcopy(data['confirm-payload']);first=payload['front_matter']['content_requirements'][0]
    payload['front_matter']['content_requirements'].append(first|dict(id='incompatible',kind='acknowledgements'))
    assert all('purpose' not in c for c in payload['chapters'])
    db=ReadOnlyDB();service=object.__new__(SchoolTemplateService)
    service.store=SimpleNamespace(connection=lambda **k:nullcontext(db),user_id='synthetic')
    service.project=lambda *a:None
    service.row=lambda *a:dict(id='template',analysis_json=data['analysis'],analysis_sha256=payload['analysis_sha256'])
    service.require_current=lambda *a:([],dict(status='succeeded',id='parse'))
    service.text_options=lambda *a:[]
    with pytest.raises(StorageError) as caught:service.confirm('project','template',ConfirmRequest.model_validate(payload),'same-key')
    assert caught.value.code=='task_input_invalid' and caught.value.status==422
    assert db.writes==[]


def test_same_kind_multiple_requirements_remain_compatible():
    from app.domain.school_templates.front_matter import validate_front_matter
    data=fixture();front=deepcopy(data['confirm-payload']['front_matter'])
    front['content_requirements'].append(front['content_requirements'][0]|dict(id='same-kind-source'))
    assert validate_front_matter(front,data['analysis'],data['confirm-payload']['chapters'])==front


@pytest.mark.parametrize('kind,wrong',[('declaration','acknowledgements'),('declaration','other'),('acknowledgements','manual')])
def test_actual_mapping_is_rejected_by_frozen_chapter_validation(kind,wrong):
    from app.domain.manuscripts.school import validate_chapters
    data=fixture();context=deepcopy(data['snapshot']['thesis_context'])
    requirement=next(r for r in context['confirmation']['front_matter']['content_requirements'] if r['kind']==kind)
    context['confirmation']['front_matter']['content_requirements']=[requirement]
    next(c for c in context['chapters'] if c['id']==requirement['chapter_id'])['purpose']=wrong
    with pytest.raises(ValueError):validate_chapters(context,{'evidence'})


def manuscript_service(monkeypatch,context):
    from app.domain.manuscripts import school_binding as binding
    from app.domain.manuscripts.service import ManuscriptService
    from app.domain.literature.service import digest
    saved=dict(id=context['confirmation_id'],template_version_id=context['template_version_id'],snapshot_sha256=digest(context['confirmation']))
    db=ReadOnlyDB(saved);service=object.__new__(ManuscriptService)
    service.assets=object();service.store=SimpleNamespace(connection=lambda **k:nullcontext(db),user_id='synthetic')
    service.require_project=lambda *a:dict(project_type='thesis')
    monkeypatch.setattr(binding,'readiness',lambda *a:dict(ready=True,confirmation_id=context['confirmation_id'],profile=context['profile'],chapters=context['confirmation']['chapters'],template_source_file_ids=[]))
    fake=SimpleNamespace(row=lambda *a:dict(id=context['template_version_id']),require_current=lambda *a:(context['source_files'],{}),confirmation=lambda *a:context['confirmation'])
    monkeypatch.setattr(binding,'SchoolTemplateService',lambda *a:fake)
    return service,db


@pytest.mark.parametrize('kind,wrong',[('declaration','acknowledgements'),('declaration','other'),('acknowledgements','manual')])
def test_create_rejects_wrong_actual_purpose_before_task_or_manuscript_persistence(monkeypatch,kind,wrong):
    from app.core.exceptions import StorageError
    from app.domain.manuscripts import service as module
    data=fixture();context=deepcopy(data['snapshot']['thesis_context']);front=context['confirmation']['front_matter']
    requirement=next(r for r in front['content_requirements'] if r['kind']==kind);front['content_requirements']=[requirement]
    service,db=manuscript_service(monkeypatch,context)
    def too_late(*a):raise AssertionError('Wrong mapping passed freeze_context into research freezing')
    monkeypatch.setattr(module,'freeze',too_late)
    mappings=[dict(chapter_id=c['id'],purpose=wrong if c['id']==requirement['chapter_id'] else c['purpose'],output_language='project',result_group_ids=c['result_group_ids']) for c in context['chapters']]
    request=dict(title='Synthetic mapping check',output_language='en',results_groups=[dict(id='evidence',title='Synthetic results')],thesis=dict(confirmation_id=context['confirmation_id'],profile_revision=context['profile']['revision'],chapter_mappings=mappings))
    with pytest.raises(StorageError) as caught:service.create('project',request,'same-key')
    assert caught.value.code=='task_input_invalid' and caught.value.status==422
    assert db.writes==[]


@pytest.mark.parametrize('variant',['A','B'])
def test_valid_synthetic_context_recompiles_without_plan_or_snapshot_changes(variant):
    from app.domain.manuscripts.school import validate_chapters
    from app.domain.manuscripts.school_export import compile_school_export
    from app.domain.literature.service import digest
    data=fixture(variant);before=deepcopy(data)
    validate_chapters(data['snapshot']['thesis_context'],{'evidence'})
    assert compile_school_export(data['snapshot'],data['analysis'],data['plan']['options'])==data['plan']
    assert data==before and digest(data['snapshot'])==data['plan']['snapshot_sha256']


def test_legacy_without_front_matter_keeps_mapping_and_serialized_context(monkeypatch):
    from app.domain.manuscripts.school import validate_chapters
    from app.domain.manuscripts.school_binding import freeze_context
    from app.domain.manuscripts.contracts import ManuscriptRequest
    from app.domain.literature.service import digest
    data=fixture();context=deepcopy(data['snapshot']['thesis_context']);context['confirmation'].pop('front_matter')
    context['confirmation_sha256']=digest(context['confirmation']);context['chapters'][0]['purpose']='other'
    before=deepcopy(context);validate_chapters(context,{'evidence'})
    service,_=manuscript_service(monkeypatch,context)
    request=ManuscriptRequest.model_validate(dict(title='Synthetic legacy',output_language='en',results_groups=[dict(id='evidence',title='Synthetic results')],thesis=dict(confirmation_id=context['confirmation_id'],profile_revision=context['profile']['revision'],chapter_mappings=[dict(chapter_id=c['id'],purpose=c['purpose'],output_language='project',result_group_ids=c['result_group_ids']) for c in context['chapters']])))
    assert freeze_context(service,'project',request)==before
    assert digest(context)==digest(before)
