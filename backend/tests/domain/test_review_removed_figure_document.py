from copy import deepcopy
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def removed_revision():
    from app.domain.manuscript_writing.contracts import SECTION_IDS
    parent=dict(output_language='en',sections=[dict(id=s,paragraphs=[]) for s in SECTION_IDS],sources=[],results_groups=[dict(id='figures',title='Observed images',paragraphs=[],tables=[],figures=[dict(id='old-figure',number=1,title='Saved synthetic image',caption='Engineering observation.')])])
    final=deepcopy(parent);final['results_groups'][0]['figures']=[]
    change=dict(item_id='i1',kind='remove_figure',location=dict(kind='figure',id='old-figure',section_id='figures',section_title='Observed images'),before=parent['results_groups'][0]['figures'][0],after=None,reason='Old image explicitly omitted; new image remains pending.',evidence=[])
    result=dict(actual_changes=[change],items=[dict(id='i1',source_id='r1',number=1,original_text='Remove the superseded illustration.',status='completed')],output=dict(manuscript_id='m1',version_id='new',revision=3),synthetic=True)
    return dict(id='run',round_id='round',snapshot_json=dict(project_type='sci',manuscript=dict(version_id='parent')),result_json=result,result_sha256='a'*64,_output_snapshot=final,_base_snapshot=parent)

def test_removed_figure_documents_refer_to_fixed_parent_without_inventing_final_location():
    from app.domain.review_rounds.documents import build_snapshot
    from app.adapters.review_docx import render_review_document
    from io import BytesIO
    from docx import Document
    row=removed_revision();original=deepcopy(row)
    for kind in ('comparison','reply'):
        doc=build_snapshot(row,kind,'en');loc=doc['items'][0]['locations'][0]
        assert loc['id']=='old-figure' and loc['removed_from_output'] is True and loc['parent_version_id']=='parent'
        assert 'page_number' not in loc and 'line' not in loc
        text='\n'.join(p.text for p in Document(BytesIO(render_review_document(doc))).paragraphs)
        assert 'Parent location (removed from this manuscript)' in text
        assert 'Removed from this manuscript' in text
    assert row==original

def test_missing_nonremoved_or_unknown_parent_location_remains_rejected():
    from app.domain.review_rounds.documents import build_snapshot
    from app.core.exceptions import StorageError
    for patch in (dict(kind='figure_caption',after='Changed.'),dict(location=dict(kind='figure',id='unknown'))):
        row=removed_revision();row['result_json']['actual_changes'][0].update(patch)
        with pytest.raises(StorageError):build_snapshot(row,'comparison','en')
