from copy import deepcopy
from io import BytesIO

from docx import Document
import pytest

from app.adapters.manuscript_docx import build_manuscript_docx, revised_manuscript_filename
from app.adapters.review_docx import render_review_document, review_document_filename
from app.domain.manuscript_writing.live_notice import update_notice
from app.domain.review_rounds.documents import build_snapshot
from tests.adapters.test_manuscript_full_docx import full_sample
from tests.adapters.test_manuscript_review_docx import reviewed_sample
from tests.adapters.test_school_docx import fixture as school_fixture, plan
from tests.api.test_review_documents import fixed_result


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def visible_text(content):
    document = Document(BytesIO(content))
    return '\n'.join(p.text for p in document.paragraphs)


@pytest.mark.parametrize(('kind', 'language', 'required'), [
    ('comparison', 'zh-CN', ('处理状态：待补材料', '讨论，第 3 段', '样本量 12', 'P 值 0.049')),
    ('reply', 'en', ('Status: Awaiting additional material', 'Discussion, paragraph 3', 'Sample size 12', 'P value 0.049')),
])
def test_customer_review_docx_shows_facts_without_internal_references(kind, language, required):
    result = fixed_result()
    result['actual_changes'][0]['location'].update(section_title='discussion', paragraph_number=3)
    result['actual_changes'][0]['evidence'].append(dict(id='private-analysis-id', kind='analysis_run',
        sha256='b' * 64, content=dict(numeric_name='Measured response', unit='AU', overall=dict(n=12, p_value='0.049'))))
    frozen = dict(id='rev', round_id='round', snapshot_json=dict(project_type='sci'),
                  result_json=result, result_sha256='hash')
    saved = build_snapshot(frozen, kind, language)
    source = dict(saved, document_version=8, confirmed_at='2026-11-17T00:00:00Z')
    original = deepcopy(source)
    legacy = render_review_document(source)
    raw = render_review_document(dict(source, renderer_version='review_docx_v4'))
    body = visible_text(raw)
    assert all(value in body for value in (*required, 'Clarify limitation', 'causality is not established',
                                          'existing limitation', 'No new experiment is available.'))
    assert not any(value in body for value in ('SHA-256', 'a' * 64, 'b' * 64, 'private-analysis-id',
        'numeric_name', 'p_value', 'waiting_material', ' / discussion / paragraph / p1', 'Document version',
        'Final manuscript version', '最终稿件版本', '独立文档版本', '2026-11-17', 'engineering', '合成工程'))
    assert legacy == render_review_document(source)
    assert 'SHA-256' in visible_text(legacy)
    assert review_document_filename(saved, 'review_docx_v4') == saved['title'] + '.docx'
    assert raw == render_review_document(dict(source, renderer_version='review_docx_v4'))
    assert source == original


def test_customer_revised_sci_keeps_body_and_review_findings_without_internal_locations():
    snapshot, images = reviewed_sample('en', True)
    original = deepcopy(snapshot)
    body = visible_text(build_manuscript_docx(snapshot, images, customer_revision=True))
    assert 'The supplied protocol leaves the observation period unresolved.' in body
    assert 'Original laboratory record' in body
    assert 'Original confirmation applies only to the old fact' in body
    assert not any(value in body for value in ('analysis_run:old:/overall/mean', 'specific:limitation',
        'methods:study_design', 'Offline partial fact draft', 'exact source versions'))
    assert revised_manuscript_filename(snapshot) == 'Revised manuscript.docx'
    assert snapshot == original


def test_customer_sci_manuscript_uses_prose_without_the_saved_provider_notice():
    snapshot, images = full_sample('en')
    snapshot['writing_provenance'] = dict(provider_provenance='openai_live', composition_version=2)
    update_notice(snapshot, dict(mode='full_draft', schema_version=4), reviewed=True)
    limitation = 'The observed association does not establish causality.'
    snapshot['issues'].append(dict(id='study-design-limitation', kind='limitation', field='design',
                                   message=limitation, values=[]))
    original = deepcopy(snapshot)
    old = build_manuscript_docx(snapshot, images)
    body = visible_text(build_manuscript_docx(snapshot, images, customer_view=True))
    technical = ('server-managed', 'OpenAI live response', 'Explicit human scientific review recorded')
    assert all(value in visible_text(old) for value in technical)
    assert not any(value in body for value in technical)
    assert all(value in body for value in (snapshot['title'], 'NEW-RESULTS', 'Author A. Saved reference', limitation))
    assert build_manuscript_docx(snapshot, images) == old
    assert snapshot == original


def test_customer_narrative_review_hides_only_absent_original_study_fields():
    from app.domain.manuscript_writing.article_contract import STRUCTURES

    snapshot, _ = full_sample('en')
    snapshot.update(article_type='narrative_review', results_groups=[])
    snapshot['sections'] = [dict(id=section, paragraphs=[] if section == 'references' else [
        dict(id=section+':1', text=snapshot['title'] if section == 'title' else section+' prose',
             origin='model_generated', source_ids=[], citations=[])
    ]) for section in STRUCTURES['narrative_review']]
    missing = {'ethics': 'Ethics information: Not supplied; to be completed.',
               'hypothesis': 'Hypothesis: Not supplied; to be completed.',
               'results': 'No computed Results selected.'}
    literature = 'The available literature selection still needs full-text checking.'
    feedback = 'Check the wording of the ethics statement cited in the literature.'
    snapshot['issues'] = [
        dict(id='missing:'+field, kind='missing', field=field, message=message, values=[])
        for field, message in (missing | {'literature_scope': literature}).items()
    ] + [dict(id='review-note', kind='limitation', field='ethics', message=feedback, values=[])]
    original = deepcopy(snapshot)
    old = visible_text(build_manuscript_docx(snapshot, {}))
    new = visible_text(build_manuscript_docx(snapshot, {}, customer_view=True))
    legacy_customer = visible_text(build_manuscript_docx(
        snapshot, {}, customer_view=True, renderer_version='manuscript_docx_v8'))
    assert all(message in old for message in missing.values())
    assert all(message in legacy_customer for message in missing.values())
    assert not any(message in new for message in missing.values())
    assert all(part in new for part in (literature, feedback, 'themes prose', 'Author A. Saved reference'))
    assert snapshot == original


def test_customer_revised_school_keeps_template_front_matter_without_engineering_banner():
    snapshot, analysis = school_fixture()
    fixed_plan = plan(snapshot, analysis, include_toc=False, manual_fields={'author': '示例作者'})
    original = deepcopy(snapshot)
    body = visible_text(build_manuscript_docx(snapshot, {}, school_plan=fixed_plan, customer_revision=True))
    assert snapshot['title'] in body
    assert '示例作者' in body
    assert '4 Observed findings' in body
    assert '学校论文工程稿' not in body
    assert revised_manuscript_filename(snapshot) == 'Revised thesis.docx'
    assert revised_manuscript_filename(dict(snapshot, output_language='zh-CN'), blind=True) == '毕业论文盲审修订稿.docx'
    assert snapshot == original


def test_customer_response_formats_auto_citations_and_preserves_custom_wording():
    result = fixed_result()
    item = result['actual_changes'][0]
    article = dict(metadata=dict(title='Verified specimen', year='2024'), review=dict(status='needs_review'))
    item.update(kind='bind_citation', before=[], after=[article])
    frozen = dict(id='rev', round_id='round', snapshot_json=dict(project_type='sci'),
                  result_json=result, result_sha256='hash')
    snapshot = dict(build_snapshot(frozen, 'reply', 'en'), renderer_version='review_docx_v4')
    body = visible_text(render_review_document(snapshot))
    assert 'Verified specimen / 2024 — Requires review' in body
    assert 'needs_review' not in body
    snapshot['items'][0]['text'] = 'We have retained the reviewer’s wording in the response.'
    assert snapshot['items'][0]['text'] in visible_text(render_review_document(snapshot))


def test_customer_english_response_translates_only_known_system_waiting_reasons():
    result = fixed_result()
    reason = '待补充或核验材料、分析、实验、文献；取得实际结果并通过公共检查后才能完成修改。'
    original_comment = '请补做独立实验。'
    result['items'][1].update(uncompleted_reason=reason, original_text=original_comment)
    frozen = dict(id='rev', round_id='round', snapshot_json=dict(project_type='sci'),
                  result_json=result, result_sha256='hash')
    snapshot = build_snapshot(frozen, 'reply', 'en')
    old = render_review_document(dict(snapshot, renderer_version='review_docx_v4'))
    body = visible_text(render_review_document(dict(snapshot, renderer_version='review_docx_v5')))
    assert 'Further evidence is needed before this point can be addressed.' in body
    assert original_comment in body and reason not in body
    assert reason in visible_text(old)
    assert old == render_review_document(dict(snapshot, renderer_version='review_docx_v4'))
    preview = build_snapshot(frozen, 'reply', 'en', customer_view=True)['items'][1]
    assert 'Further evidence is needed' in preview['text']
    assert reason not in preview['text'] and preview['original_text'] == original_comment
    custom_note = '作者备注：独立实验将在本学期后续安排。'
    snapshot['items'][1]['text'] = custom_note
    assert custom_note in visible_text(render_review_document(dict(snapshot, renderer_version='review_docx_v5')))


def test_customer_review_renderer_keeps_frozen_rules_when_future_defaults_change():
    from app.domain.admin_configuration.rule_legacy import affected
    from app.domain.literature.service import digest
    from app.domain.review_rounds.document_contracts import WORKFLOW

    snapshot = dict(kind='review_document_export', project_id='project', renderer_version='review_docx_v4',
        workflow_version=WORKFLOW, export_id='export', document_id='document', document_sha256='a' * 64,
        revision_id='revision', round_id='round', real_model_calls=False, real_network_calls=False,
        document=dict(language='zh-CN', items=[dict(text='Sample response.')]))
    task = dict(task_type='review_document_export', project_id='project', workflow_version=WORKFLOW,
                input_snapshot=snapshot, input_digest=digest(snapshot))
    assert affected(task, ['review.default_language']) is False
