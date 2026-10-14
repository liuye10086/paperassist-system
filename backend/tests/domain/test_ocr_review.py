import importlib.util
import pytest
from tests.helpers.ocr_samples import ocr_result


def sample():
    document = ocr_result(b'x', 'scan.png', 'png', [1], {}).document
    source = dict(file_id='file', parse_id='parse', parse_version=1, source_sha256='a'*64,
                  document_sha256='b'*64, parser_version=document.parser_version, selected_pages=[1])
    return document, source


def implementation():
    assert importlib.util.find_spec('app.domain.ocr_review') is not None, 'OCR review domain is not implemented'
    from app.domain.ocr_review.transform import review_document
    return review_document


@pytest.mark.parametrize('action,text,effective', [('accept_original', None, '候选 12 mg'),
    ('replace_text', '001.20 mg/mL', '001.20 mg/mL'), ('unreadable', None, None)])
def test_review_preserves_original_evidence_and_literal_replacement(action, text, effective):
    build = implementation()
    document, source = sample()
    original = document.model_dump()
    edit = dict(block_id='text-1', action=action)
    if text is not None: edit['text'] = text
    result = build(document, source, [edit])
    assert document.model_dump() == original
    assert result.blocks[0].original.model_dump() == original['pages'][0]['text_blocks'][0]
    assert result.blocks[0].effective_text == effective
    assert result.summary.unreviewed_blocks == 0


def test_unreviewed_blocks_cannot_be_published_and_no_text_pages_are_reported():
    build = implementation()
    document, source = sample()
    result = build(document, source, [])
    assert result.summary.unreviewed_blocks == 1
    assert result.blocks[0].effective_text is None
    with pytest.raises(ValueError): result.require_publishable()
    document.pages[0].text_blocks = []
    with pytest.raises(ValueError): build(document, source, [])


@pytest.mark.parametrize('edits', [
    [dict(block_id='missing', action='unreadable')],
    [dict(block_id='text-1', action='unreadable')]*2,
    [dict(block_id='text-1', action='accept_original', text='hidden')],
    [dict(block_id='text-1', action='replace_text', text='a'*20001)],
    [dict(block_id='text-1', action='replace_text', text='')],
    [dict(block_id='text-1', action='replace_text', text=' \t\n')],
])
def test_rejects_unknown_duplicate_or_malformed_edits(edits):
    build = implementation()
    document, source = sample()
    with pytest.raises(ValueError): build(document, source, edits)


def test_replacement_total_is_bounded_and_spaces_are_preserved():
    build = implementation()
    document, source = sample()
    result = build(document, source, [dict(block_id='text-1',action='replace_text',text=' 001 mg ' )])
    assert result.blocks[0].effective_text == ' 001 mg '
    original = document.pages[0].text_blocks[0]
    document.pages[0].text_blocks = [original.model_copy(update={'id':f'b-{i}'}) for i in range(210)]
    with pytest.raises(ValueError):
        build(document,source,[dict(block_id=f'b-{i}',action='replace_text',text='a'*20000) for i in range(210)])


def test_mixed_ocr_keeps_no_text_physical_pages_outside_transcription_confirmation():
    build=implementation()
    document=ocr_result(b'x','scan.pdf','pdf',[2,3],{}).document
    document.pages[1].text_blocks=[]
    source=dict(file_id='file',parse_id='parse',parse_version=3,source_sha256='a'*64,
        document_sha256='b'*64,parser_version=document.parser_version,selected_pages=[2,3])
    result=build(document,source,[dict(block_id='text-2',action='accept_original')])
    assert result.summary.no_text_pages==[3]
    assert result.summary.total_blocks==1 and result.summary.unreviewed_blocks==0
    result.require_publishable()
