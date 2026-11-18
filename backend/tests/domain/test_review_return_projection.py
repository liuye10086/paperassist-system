from copy import deepcopy
from io import BytesIO

import pytest
from docx import Document

from app.adapters.manuscript_docx import build_manuscript_docx
from app.adapters.school_docx import build_school_docx
from app.domain.journals.display import apply, plan
from app.domain.literature.service import digest
from app.domain.manuscripts.contracts import SchoolExportOptions
from app.domain.manuscripts.school import pending
from app.domain.manuscripts.school_return import extract
from app.domain.review_rounds.returns import ReviewReturnService, apply_supported_return, return_base
from app.domain.manuscripts.school_export import compile_school_export
from tests.domain.test_frontiers_review_format import confirmed_target, reviewed_input
from tests.domain.test_school_writing_live import material


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def replace_in_section(section, text, *, keep_bookmark=True):
    paragraph = section['paragraphs'][0]
    return dict(id=section['id'], paragraphs=[text], paragraph_items=[
        dict(text=text, original_id=paragraph['id'] if keep_bookmark else None)])


def returned_candidate(monkeypatch, snapshot, frozen):
    service = object.__new__(ReviewReturnService)
    service.manuscripts = None
    monkeypatch.setattr(service, 'validate_return', lambda db, row: {'snapshot_json': snapshot})
    mappings = [dict(input_section_id=s['id'], chapter_id=s['suggested_chapter_id'])
                for s in frozen['sections'] if s.get('suggested_chapter_id')]
    return service.candidate(None, dict(snapshot_json=frozen, project_id='p', manuscript_id='m',
                                        output_version_id=None), mappings)


def test_revised_frontiers_return_exports_word_with_the_preserved_claims(monkeypatch):
    parent = reviewed_input()
    parent['article_structure_version'] = 'article-scope-v1'
    target = confirmed_target()
    parent = apply(parent, plan(parent, target, [])['actions'])
    original = build_manuscript_docx(parent, {}, customer_view=True)
    updated = 'Discussion revised for clarity.'
    inputs = [replace_in_section(s, updated if s['id']=='discussion' else s['paragraphs'][0]['text'])
              | dict(suggested_chapter_id=s['id']) for s in return_base(parent)['sections']]
    revised, _, issues = returned_candidate(monkeypatch, parent, dict(
        schema_version=3, sections=inputs, issues=[], synthetic=True))
    assert not any(row['severity']=='error' for row in issues)
    word = Document(BytesIO(build_manuscript_docx(revised, {}, customer_view=True, customer_revision=True)))
    content = {p.text for p in word.paragraphs}
    assert {updated, 'Supported claim 1 (1).', 'Supported claim 2 (2).'} <= content
    assert revised['references'] == parent['references']
    assert build_manuscript_docx(parent, {}, customer_view=True) == original


@pytest.mark.parametrize('drop_body_chapter', [False, True])
def test_school_return_uses_the_export_scope_with_automatic_contents_disabled(monkeypatch, drop_body_chapter):
    parent, _, analysis = material(bilingual=True)
    chapter = dict(id='contents', title='目录', level=1, purpose='manual', output_language='zh-CN', result_group_ids=[])
    parent['thesis_context']['chapters'].insert(4, chapter)
    parent['thesis_context']['confirmation']['chapters'].insert(4, {k:chapter[k] for k in ('id','title','level')})
    analysis['chapters'].insert(4, dict(analysis['chapters'][0], id='contents', title='目录'))
    confirmation = parent['thesis_context']['confirmation']
    confirmation['analysis_sha256'] = digest(analysis)
    parent['thesis_context']['confirmation_sha256'] = digest(confirmation)
    original_contents = dict(chapter, paragraphs=[pending(chapter)])
    parent['sections'].insert(4, original_contents)
    parent['paper_plan'] = dict(kind='thesis', title=parent['title'], sections=[], materials=[], keywords=[])
    options = SchoolExportOptions(include_toc=False).model_dump(mode='json')
    baseline = build_school_docx(parent, {}, compile_school_export(parent, analysis, options))
    doc = Document(BytesIO(baseline))
    assert '目录' not in [p.text for p in doc.paragraphs]
    sections = {s['id']:s for s in parent['sections']}
    introduction = sections['private-intro']['paragraphs'][0]
    revised_text = introduction['text']+' 补充普通措辞。'
    next(p for p in doc.paragraphs if p.text==introduction['text']).runs[0].text = revised_text
    stream = BytesIO()
    doc.save(stream)
    parsed = extract(stream.getvalue(), 'thesis-return.docx', parent, baseline, match_export_scope=True)
    assert parsed['exported_chapter_ids'] == [s['id'] for s in parent['sections'] if s['id']!='contents']
    if drop_body_chapter:
        parsed['sections'] = [s for s in parsed['sections'] if s['suggested_chapter_id']!='private-intro']
    revised, changes, issues = returned_candidate(monkeypatch, parent, dict(parsed, schema_version=3, synthetic=True))
    assert next(s for s in revised['sections'] if s['id']=='contents') == original_contents
    if drop_body_chapter:
        assert any(p['code']=='mapping_required' for p in issues)
    else:
        assert not any(p['severity']=='error' for p in issues), issues
        assert any(revised_text in d['after'] for d in changes)


@pytest.mark.parametrize('keep_bookmark', [False, True])
def test_changed_sci_statement_with_frozen_parenthetical_marker_requires_review(keep_bookmark):
    parent = reviewed_input()
    parent['article_structure_version'] = 'article-scope-v1'
    base = return_base(parent)
    cited = next(s for s in base['sections'] if s['id']=='introduction')
    original = deepcopy(cited)
    text = cited['paragraphs'][0]['text'].replace('Supported claim', 'Different claim')
    incoming = [replace_in_section(s, text if s==cited else s['paragraphs'][0]['text'],
                                   keep_bookmark=keep_bookmark) for s in base['sections']]
    mappings = [dict(input_section_id=s['id'], chapter_id=s['id']) for s in base['sections']]
    revised, _, issues = apply_supported_return(base, incoming, mappings)
    assert any(p['code']=='citation_changed' and p['severity']=='error' for p in issues), issues
    assert revised['sections'][1]['paragraphs'][0]['citations']==[]
    assert cited==original
    preserved = next(s for s in revised['sections'] if s['id']=='themes')
    assert preserved == next(s for s in base['sections'] if s['id']=='themes')
