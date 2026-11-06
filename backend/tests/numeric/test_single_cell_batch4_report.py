import io
from copy import deepcopy

from docx import Document
import pytest


@pytest.mark.parametrize('language',['zh-CN','en'])
def test_word_retains_annotation_status_evidence_and_subset_source(language):
    from app.adapters.single_cell_report import build_single_cell_report
    annotation=dict(id='ann-v2',set_id='ann',version=2,processed_dataset_version_id='processed',name='PBMC labels',
        labels=[dict(id='l1',name='T cells',status='proposed',cluster_ids=['1'],cell_ids=[],note='Candidate only'),dict(id='l2',name='Unresolved',status='uncertain',cluster_ids=['2'],cell_ids=[],note='Mixed markers')],
        assignments=[dict(barcode='c1',label_id='l1',status='assigned'),dict(barcode='c2',label_id='l2',status='uncertain'),dict(barcode='c3',label_id=None,status='unknown')],
        evidence=[dict(label_id='l1',kind='marker',analysis_artifact_id='marker-fixed',file_id=None,note='CD3D marker table'),dict(label_id='l2',kind='manual',note='Needs review')],
        algorithm=dict(tool='SingleR',version='2.8.0',reference=dict(id='monaco_immune',version='2024-02-26',source='https://example.org/reference'),candidate_only=True))
    before=deepcopy(annotation)
    manifest=dict(summary=dict(subset=dict(parent_processed_source=dict(processed_dataset_version_id='parent-fixed'),selected_cells=3,retained_features=100,qc='inherited_parent',capture_models_rerun=False)),params={},steps=[])
    content=build_single_cell_report('project','processed','a'*64,manifest,{},[],language,annotation=annotation)
    document=Document(io.BytesIO(content));text='\n'.join([p.text for p in document.paragraphs]+[c.text for t in document.tables for r in t.rows for c in r.cells])
    assert 'ann-v2' in text and 'T cells' in text and 'Unresolved' in text
    assert 'parent-fixed' in text and 'CD3D marker table' in text and 'Needs review' in text
    assert 'SingleR' in text and '2024-02-26' in text
    assert ('未确定' if language=='zh-CN' else 'Uncertain') in text
    assert ('候选' if language=='zh-CN' else 'Proposed') in text
    paragraphs=[p.text for p in document.paragraphs]
    assert paragraphs[paragraphs.index('Unresolved')+1].endswith('1')
    assert annotation==before
