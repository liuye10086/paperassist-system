"""Parent independently reconciles candidate scores with the retained cell axis."""
import io
import json
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def fixture(tmp_path):
    def leaf(key,content):
        path=tmp_path/key;path.write_bytes(content)
        return dict(path=str(path))
    raw=leaf('raw_axes.json',json.dumps(dict(barcodes=['a','filtered','b'])).encode())
    buffer=io.BytesIO();np.save(buffer,np.array([True,False,True]),allow_pickle=False)
    mask=leaf('observation_mask.npy',buffer.getvalue())
    candidates=leaf('annotation_candidates.tsv',b'barcode\tcandidate_label\tpruned_label\tdelta_next\tdelta_median\na\tT\tT\t0.5\t0.7\nb\tB\tunknown\t0.1\t0.2\n')
    scores=leaf('annotation_scores.tsv',b'barcode\tT\tB\na\t0.8\t0.3\nb\t0.5\t0.6\n')
    result=dict(outputs=[dict(key='annotation_candidates',**candidates),dict(key='annotation_scores',**scores)],
        summary=dict(cells=2,score_labels=['T','B']),manifest=dict(algorithm='SingleR'))
    payload=dict(processed=dict(members=dict(raw_axes=raw,observation_mask=mask)))
    return result,payload


def test_parent_accepts_complete_finite_scores_with_pruned_unknown(tmp_path):
    from app.adapters.bio_single_cell_validation import validate_annotation_result
    result,payload=fixture(tmp_path)
    assert validate_annotation_result(result,payload)['cells']==2


@pytest.mark.parametrize('mutation',['axis','scores_axis','nan','candidate_label','summary'])
def test_parent_rejects_changed_axis_scores_or_unknown_label(tmp_path,mutation):
    from app.adapters.bio_single_cell_validation import validate_annotation_result
    from app.core.exceptions import StorageError
    from pathlib import Path
    result,payload=fixture(tmp_path)
    if mutation=='axis':
        path=Path(result['outputs'][0]['path']);path.write_text(path.read_text().replace('b\tB','filtered\tB'))
    if mutation=='scores_axis':
        path=Path(result['outputs'][1]['path']);path.write_text(path.read_text().replace('b\t0.5','a\t0.5'))
    if mutation=='nan':
        path=Path(result['outputs'][1]['path']);path.write_text(path.read_text().replace('0.8','nan'))
    if mutation=='candidate_label':
        path=Path(result['outputs'][0]['path']);path.write_text(path.read_text().replace('a\tT\tT','a\tUnknownType\tT'))
    if mutation=='summary':result['summary']['cells']=3
    with pytest.raises(StorageError):validate_annotation_result(result,payload)
