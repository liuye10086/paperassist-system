"""Figure references follow saved identity, never infer findings from pixels."""
from copy import deepcopy
import pytest
from app.domain.manuscripts.contracts import ManuscriptRequest
from app.domain.manuscripts.draft import freeze


def source(kind='original', caption=''):
    content = {'source': {'file_type': 'png'}} if kind == 'original' else {'title': 'Saved plot', 'language': 'en', 'caption': caption}
    if kind == 'document_version':
        content = {'images': [{'id': 'img', 'caption_candidates': [caption] if caption else [], 'sha256': 'a'*64, 'preview_url': '/image'}]}
    return dict(kind=kind,id='image',file_id='file',role='image_observation',label='Saved image',sha256='a'*64,download_url='/source',content=content)


def draft(item, *, language='en', notes=None):
    request = ManuscriptRequest(title='Synthetic observations',output_language=language,
        sources=[{k:item[k] for k in ('kind','id','file_id','role')}],
        results_groups=[dict(id='observations',title='Observations',figure_ids=['image'])],
        figure_notes=notes or [])
    return freeze(None, 'project', request, frozen_sources=[item])


@pytest.mark.parametrize('kind', ['original','figure','document_version'])
def test_missing_caption_is_pending_for_every_image_source(kind):
    snapshot = draft(source(kind))
    assert any(i['id'].startswith('missing:caption:') for i in snapshot['issues'])
    assert snapshot['results_groups'][0]['figures'][0]['caption_status'] == 'missing'


@pytest.mark.parametrize('language', ['en','zh-CN'])
def test_saved_identity_generates_body_figure_and_panel_references(language):
    snapshot = draft(source(), language=language, notes=[dict(figure_id='image', caption='Supplied description',
        panels=[dict(label='A',description='Observation A'),dict(label='B',description='Observation B')])])
    group = snapshot['results_groups'][0]
    paragraph = group['paragraphs'][0]
    assert paragraph['origin'] == 'image_observation'
    assert paragraph['cross_references'] == [
        dict(kind='figure', target_id='image', number=1, panel_label=None),
        dict(kind='figure', target_id='image', number=1, panel_label='A'),
        dict(kind='figure', target_id='image', number=1, panel_label='B')]
    assert ('Figure 1A' if language=='en' else '图 1A') in paragraph['text']
    assert not any(i['id'].startswith('missing:caption:') for i in snapshot['issues'])
    assert snapshot['illustration_check_version'] == 1


def test_duplicate_or_nonletter_panel_labels_stay_pending_without_ambiguous_body_links():
    snapshot = draft(source(),notes=[dict(figure_id='image',caption='Supplied',panels=[
        dict(label='A',description='First'),dict(label=' A ',description='Second'),dict(label='unknown',description='Third')])])
    assert any(i['id']=='panels:image' and i['kind']=='conflict' for i in snapshot['issues'])
    assert [r['panel_label'] for r in snapshot['results_groups'][0]['paragraphs'][0]['cross_references']] == [None]
    assert len(snapshot['results_groups'][0]['figures'][0]['panels'])==3


def test_unverified_document_caption_stays_flagged_and_no_sources_are_mutated():
    item=source('document_version','Source caption candidate')
    original=deepcopy(item)
    snapshot=draft(item)
    assert item==original
    assert any(i['id'].startswith('verify:caption:') for i in snapshot['issues'])


def test_reference_checker_reports_number_target_and_panel_mismatch():
    from app.domain.manuscripts.illustrations import check_references
    snapshot=draft(source(),notes=[dict(figure_id='image',caption='Supplied',panels=[dict(label='A',description='Panel A')])])
    refs=snapshot['results_groups'][0]['paragraphs'][0]['cross_references']
    refs[0]['number']=9
    refs[1]['panel_label']='B'
    issues=check_references(snapshot['results_groups'],'en')
    assert len(issues)>=2
    assert all(i['kind']=='conflict' for i in issues)


def test_wrong_visible_reference_is_reported_even_with_valid_identity_metadata():
    from app.domain.manuscripts.illustrations import check_references
    snapshot=draft(source(),notes=[dict(figure_id='image',caption='Supplied',panels=[dict(label='A',description='Panel A')])])
    paragraph=snapshot['results_groups'][0]['paragraphs'][0]
    paragraph['text']=paragraph['text'].replace('Figure 1A','Figure 9B')
    assert check_references(snapshot['results_groups'],'en')


def test_user_methods_and_caption_unknown_numbers_stay_pending_without_rewriting():
    item=source()
    request=ManuscriptRequest(title='References',output_language='en',sources=[{k:item[k] for k in ('kind','id','file_id','role')}],
        methods={'procedures':'See Figure 99 and Table 8.'},
        results_groups=[dict(id='images',title='Images',figure_ids=['image'])],
        figure_notes=[dict(figure_id='image',caption='Compare with Figure 1B.',panels=[dict(label='A',description='Observed panel')])])
    snapshot=freeze(None,'project',request,frozen_sources=[item])
    issues=[i for i in snapshot['issues'] if i['id'].startswith('body-reference:')]
    assert len(issues)==3
    assert any(i['field']=='methods:procedures' for i in issues)
    assert 'See Figure 99 and Table 8.' in snapshot['methods'][0]['text']
    assert snapshot['results_groups'][0]['figures'][0]['caption']=='Compare with Figure 1B.'
