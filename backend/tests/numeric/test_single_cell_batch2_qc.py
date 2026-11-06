import numpy as np
import pytest
from scipy import sparse
from app.adapters.bio_engine.qc import quality_control


def fixture():
    return sparse.csr_matrix([[3,2],[8,2],[3,2],[8,2]],dtype='int64'),dict(feature_ids=['g1','g2'],feature_symbols=['g1','MT-g2'],feature_types=['Gene Expression']*2),['a','b','c','d']


def test_library_qc_uses_original_axis_and_inherits_global_thresholds():
    matrix,features,barcodes=fixture()
    config=dict(min_counts=6,min_gene_spots=1,library_qc_overrides=[dict(library_id='L2',min_counts=1,max_counts=6)])
    qc=quality_control(matrix,features,barcodes,[],config,library_ids=['L1','L1','L2','L2'])
    assert qc['obs_mask'].tolist()==[False,True,True,False]
    assert qc['reasons']==[['min_counts'],[],[],['max_counts']]
    assert qc['library_qc'][0]['library_id']=='L1' and qc['library_qc'][1]['kept_cells']==1
    np.testing.assert_array_equal(matrix.toarray(),[[3,2],[8,2],[3,2],[8,2]])


def test_unknown_library_override_is_explicit_error():
    matrix,features,barcodes=fixture()
    with pytest.raises(ValueError,match='unknown_library_qc_override'):
        quality_control(matrix,features,barcodes,[],dict(library_qc_overrides=[dict(library_id='unknown')]),library_ids=['L1']*4)


def test_library_qc_single_library_mitochondrial_threshold():
    matrix,features,barcodes=fixture()
    qc=quality_control(matrix,features,barcodes,[],dict(min_gene_spots=1,mitochondrial_feature_ids=['g2'],library_qc_overrides=[dict(library_id='L1',max_mt_fraction=0.3)]),library_ids=['L1']*4)
    assert qc['obs_mask'].tolist()==[False,True,False,True]


def test_pipeline_matches_qc_to_import_library_after_mapping_edit(tmp_path):
    import json
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_engine.pipeline import run
    matrix,features,barcodes=fixture()
    source=tmp_path/'source';source.mkdir();writer=Writer(source)
    writer.matrix('matrix',matrix);writer.json('features_index',features);writer.json('barcodes_index',dict(barcodes=barcodes))
    original=[dict(barcode=b,library_id='L1' if i<2 else 'L2',original_barcode=b) for i,b in enumerate(barcodes)]
    writer.json('import_observation_map_index',dict(rows=original))
    writer.json('observation_map_index',dict(rows=[dict(barcode=b,donor=dict(status='known',value='edited')) for b in barcodes]))
    raw=dict(manifest=dict(assay='single_cell',input_shape=dict(observations=4,features=2)),members={m['key']:m for m in writer.artifacts})
    output=tmp_path/'output';output.mkdir()
    result=run(dict(mode='qc',raw=raw,output_directory=str(output),config=dict(min_counts=6,min_spots=1,library_qc_overrides=[dict(library_id='L2',min_counts=1,max_counts=6)])))
    assert result['summary']['retained_observations']==2
    assert result['summary']['single_cell_algorithms']['doublet']['status']=='not_requested'
    import csv
    from pathlib import Path
    members={m['key']:m for m in result['outputs']}
    rows=list(csv.DictReader(Path(members['observations']['path']).open(),delimiter='\t'))
    assert [r['library_id'] for r in rows]==['L1','L1','L2','L2']
    assert [r['kept'] for r in rows]==['False','True','True','False']
    assert all(r['donor']=='edited' for r in rows)
    assert {'library_qc','library_algorithms','single_cell_tool_versions','single_cell_tool_logs'}<=members.keys()


def test_final_library_qc_reason_counts_include_predicted_doublet(tmp_path,monkeypatch):
    import csv,json
    from pathlib import Path
    from app.adapters.bio_engine import pipeline
    from app.adapters.bio_engine.manifest import Writer
    original=pipeline.run_algorithms
    def predicted(*args,**kwargs):
        value=original(*args,**kwargs);value['keep'][0]=False
        value['observations'][0].update(doublet_status='completed',doublet_prediction='doublet',doublet_excluded=True)
        return value
    monkeypatch.setattr(pipeline,'run_algorithms',predicted)
    matrix,features,cells=fixture();source=tmp_path/'source';source.mkdir();writer=Writer(source)
    writer.matrix('matrix',matrix);writer.json('features_index',features);writer.json('barcodes_index',dict(barcodes=cells));writer.json('observation_map_index',dict(rows=[dict(barcode=b,library_id='L1') for b in cells]))
    output=tmp_path/'output';output.mkdir()
    raw=dict(manifest=dict(assay='single_cell',input_shape=dict(observations=4,features=2)),members={m['key']:m for m in writer.artifacts})
    result=pipeline.run(dict(mode='qc',raw=raw,output_directory=str(output),config=dict(min_spots=1)))
    member=next(m for m in result['outputs'] if m['key']=='library_qc')
    row=next(csv.DictReader(Path(member['path']).open(),delimiter='\t'))
    assert row['excluded_cells']=='1'
    assert json.loads(row['exclusion_reason_counts'])['predicted_doublet']==1
