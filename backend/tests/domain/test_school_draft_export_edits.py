from types import SimpleNamespace

import pytest

from app.core.exceptions import StorageError
from app.domain.sci_draft_reader import school_export_projection


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_school_export_edits_keep_exact_prose_and_only_reposition_existing_citations():
    from app.domain.manuscripts.school_draft_edits import SchoolDraftEdits, export_parts

    citation = dict(number=2, project_reference_id='ref', excerpts=[])
    paragraph = dict(id='p1', parts=[dict(text='First sentence. Second sentence.', citations=[citation])])
    edits = SchoolDraftEdits(citations={'p1': [dict(sentence='First sentence.', numbers=[2])]})
    parts = export_parts(paragraph, edits.citations['p1'])
    assert parts == [dict(text='First sentence.', citations=[citation]),
                     dict(text=' Second sentence.', citations=[])]
    assert paragraph['parts'][0]['text'] == 'First sentence. Second sentence.'
    for sentence, number in [('Missing sentence.', 2), ('First sentence.', 3)]:
        invalid = SchoolDraftEdits(citations={'p1': [dict(sentence=sentence, numbers=[number])]})
        with pytest.raises(StorageError):
            export_parts(paragraph, invalid.citations['p1'])


def test_simple_draft_recognizes_pinned_school_template_in_export_only():
    from app.domain.literature.service import digest
    from app.domain.school_templates import bsu_gs501

    confirmation = {'analysis_sha256': 'sealed'}
    context = dict(confirmation=confirmation, confirmation_sha256=digest(confirmation),
                   source_files=[dict(role='template', sha256=bsu_gs501.TEMPLATE_SHA256)])
    snapshot = dict(thesis_context=context, writing_provenance={})
    projected = school_export_projection(snapshot, [])
    assert bsu_gs501.selected(projected)
    assert 'format_profile' not in confirmation
    assert digest(projected['thesis_context']['confirmation']) == projected['thesis_context']['confirmation_sha256']
    assert projected['thesis_context']['source_files'] == context['source_files']


def test_gs501_restarts_once_for_each_page_number_format():
    from docx import Document
    from docx.oxml.ns import qn
    from app.adapters.school_docx import _SchoolPagination2

    document = Document()
    pagination = _SchoolPagination2(document, gs501=True)
    page = dict(width_cm=21, height_cm=29.7, margin_top_cm=3.8, margin_bottom_cm=3.8,
                margin_left_cm=3.2, margin_right_cm=3.2)
    for index, fmt in enumerate(('upperRoman', 'upperRoman', 'decimal', 'decimal')):
        pagination.new_section(dict(id=f'section-{index}', page=page,
                                    page_number=dict(format=fmt, start='1')))
    attributes = [section._sectPr.find(qn('w:pgNumType')).get(qn('w:start'))
                  for section in document.sections]
    assert attributes == ['1', None, '1', None]
