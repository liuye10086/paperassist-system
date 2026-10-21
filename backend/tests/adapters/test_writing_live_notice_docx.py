"""Notice changes are in stored candidates and visible in DOCX, not renderer filters."""
from copy import deepcopy
from io import BytesIO
import pytest
from docx import Document
from app.adapters.manuscript_docx import build_manuscript_docx
from app.domain.manuscript_writing.live_execution import compose_live_candidate
from tests.domain.test_writing_live_candidates import notice_fixture


@pytest.fixture(autouse=True)
def postgres_schema(): yield None


@pytest.mark.parametrize('language',['en','zh-CN'])
@pytest.mark.parametrize('mode',['full_draft','rewrite_section'])
def test_docx_renders_new_candidate_scope_and_keeps_scientific_body(language,mode):
    snapshot,bundle,output=notice_fixture(language,mode)
    snapshot['base_snapshot']['schema_version']=1
    for source in snapshot['base_snapshot']['sources']: source['label']='Frozen study facts'
    for section in snapshot['base_snapshot'].get('sections',[]):
        for paragraph in section['paragraphs']: paragraph['origin']='model_generated'
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    before=deepcopy(candidate)
    doc=Document(BytesIO(build_manuscript_docx(candidate,{})))
    text='\n'.join(p.text for p in doc.paragraphs)
    assert 'Local deterministic fact draft' not in text
    assert candidate['notice'] in text
    assert ('Scientific review pending' if language=='en' else '科学审核待完成') in text
    assert all(p['text'] in text for s in candidate['sections'] for p in s['paragraphs'])
    assert candidate==before
