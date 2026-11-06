"""Subset identity and inherited QC can be checked without an R runtime."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import sparse


def parent_fixture(tmp_path):
    from app.adapters.bio_engine.manifest import Writer
    raw=sparse.csr_matrix(np.arange(40,dtype='int64').reshape(8,5)+1)
    cells=[f'library:cell{i}' for i in range(8)]
    features=dict(feature_ids=[f'g{i}' for i in range(5)],feature_symbols=[f'G{i}' for i in range(5)],feature_types=['Gene Expression']*5)
    mask=np.array([False,True,True,True,True,True,True,True]);fmask=np.array([True,True,True,True,False])
    writer=Writer(tmp_path)
    writer.json('raw_axes',dict(barcodes=cells,**features));writer.array('observation_mask',mask);writer.array('feature_mask',fmask)
    writer.matrix('counts',raw[mask][:,fmask].tocsr());writer.matrix('decontx_counts',raw[mask][:,fmask].astype('float64')*.8)
    rows=[]
    for i,c in enumerate(cells):
        rows.append(dict(raw_index=i,barcode=c,kept=bool(mask[i]),cluster='0' if i<4 else '1',
            total_counts=int(raw[i].sum()),detected_genes=5,zero_fraction=0,extreme_counts_candidate=False,
            extreme_genes_candidate=False,mt_fraction=None,mt_reason='mitochondrial_rule_unconfirmed',
            exclusion_reasons='' if mask[i] else 'predicted_doublet',doublet_status='completed',doublet_score=.1+i/100,
            doublet_prediction='singlet' if mask[i] else 'doublet',doublet_excluded=not bool(mask[i]),doublet_reason=None,
            decontx_status='completed',decontx_contamination=.2,decontx_reason=None,library_id='library',preliminary_qc_kept=True))
    writer.table('observations',rows)
    manifest=dict(summary=dict(single_cell_algorithms=dict(doublet=dict(status='completed'),decontx=dict(status='completed',layer_emitted=True),versions=dict(decontX='1.4.0'))))
    parent=dict(manifest=manifest,members={v['key']:v for v in writer.artifacts})
    selected=dict(parent_processed_source={'processed_dataset_version_id':'parent'},cluster_ids=['1'],cell_ids=[],resolved_cell_ids=cells[3:])
    return raw,features,cells,parent,selected


def test_subset_retains_axes_counts_correction_and_parent_qc(tmp_path):
    from app.adapters.bio_engine.subset import inherit_subset
    raw,features,cells,parent,selection=parent_fixture(tmp_path)
    result=inherit_subset(raw,features,cells,parent,selection)
    qc=result['qc'];algorithms=result['algorithms']
    assert qc['obs_mask'].tolist()==[False,False,False,True,True,True,True,True]
    assert qc['feature_mask'].tolist()==[True,True,True,True,False]
    assert (qc['filtered_counts']!=raw[3:,:4]).nnz==0
    np.testing.assert_allclose(result['decontx_counts'].toarray(),raw[3:,:4].toarray()*.8)
    assert result['algorithm_rows'][3]['doublet_score']==.13
    assert qc['reasons'][0]==['predicted_doublet']
    assert qc['reasons'][1]==['outside_parent_selection']
    assert algorithms['summary']['inherited_from_parent'] is True
    assert result['provenance']['selected_cell_ids']==cells[3:]
    assert result['provenance']['parent_processed_source']==selection['parent_processed_source']


@pytest.mark.parametrize('selection_cells',[['library:cell0'],['library:cell1','library:cell1'],['unknown']])
def test_subset_rejects_excluded_unknown_or_duplicate_cells(tmp_path,selection_cells):
    from app.adapters.bio_engine.subset import inherit_subset
    raw,features,cells,parent,selection=parent_fixture(tmp_path)
    selection['resolved_cell_ids']=selection_cells
    with pytest.raises(ValueError,match='subset_selection'):
        inherit_subset(raw,features,cells,parent,selection)


def test_subset_refuses_parent_counts_different_from_original(tmp_path):
    from app.adapters.bio_engine.subset import inherit_subset
    raw,features,cells,parent,selection=parent_fixture(tmp_path)
    item=parent['members']['counts_data'];path=Path(item['path'])
    values=np.load(path);values[9]+=1;np.save(path,values,allow_pickle=False)
    item.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
    with pytest.raises(ValueError,match='subset_parent_counts'):
        inherit_subset(raw,features,cells,parent,selection)
