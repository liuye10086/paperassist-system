import json
from pathlib import Path

import numpy as np


def test_subset_pipeline_reclusters_parent_counts_without_capture_models(tmp_path,monkeypatch):
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_engine import pipeline
    from app.adapters.bio_analysis_process import validate_engine_result,validate_processed_arrays
    from tests.numeric.test_single_cell_batch3_algorithms import sample
    import anndata as ad
    counts,_,genes,batches=sample();cells=[f'cell{i}' for i in range(80)]
    source=tmp_path/'source';source.mkdir();writer=Writer(source)
    writer.matrix('matrix',counts);writer.json('features_index',dict(feature_ids=genes,feature_symbols=genes,feature_types=['Gene Expression']*len(genes)))
    writer.json('barcodes_index',dict(barcodes=cells));writer.json('observation_map_index',dict(rows=[dict(barcode=c,library_id=b,batch=dict(status='known',value=b)) for c,b in zip(cells,batches)]))
    raw=dict(manifest=dict(assay='single_cell',input_shape=dict(observations=80,features=36)),members={m['key']:m for m in writer.artifacts})
    config=dict(min_spots=1,hvg_count=12,pca_components=6,harmony=dict(enabled=False))
    parent_dir=tmp_path/'parent';parent_dir.mkdir()
    parent=pipeline.run(dict(mode='compute',raw=raw,config=config,output_directory=str(parent_dir)))
    parent_members={m['key']:m for m in parent['outputs']}
    parent_hashes={m['key']:m['sha256'] for m in parent['outputs']}
    def forbidden(*args,**kwargs):raise AssertionError('subset must inherit capture models')
    monkeypatch.setattr(pipeline,'run_algorithms',forbidden)
    output=tmp_path/'child';output.mkdir();chosen=cells[10:50]
    selection=dict(parent_processed_source=dict(processed_dataset_version_id='parent'),cluster_ids=[],cell_ids=chosen,resolved_cell_ids=chosen)
    result=pipeline.run(dict(mode='compute',raw=raw,config=config,output_directory=str(output),processed=dict(manifest=parent['manifest'],members=parent_members),subset=selection))
    validate_engine_result(result,output,mode='compute')
    assert validate_processed_arrays(result['outputs'])['observations']==40
    outputs={m['key']:m for m in result['outputs']};obj=ad.read_h5ad(outputs['processed']['path'])
    assert list(obj.obs_names)==chosen and list(obj.var_names)==genes
    assert (obj.layers['counts']!=counts[10:50]).nnz==0
    assert obj.obsm['X_umap'].shape==(40,2)
    assert json.loads(obj.uns['paperassist_subset_json'])['parent_processed_source']==selection['parent_processed_source']
    assert result['manifest']['subset']['capture_models_rerun'] is False
    assert result['summary']['subset']['selected_cells']==40
    assert {step['key']:step for step in result['steps']}['scdblfinder']['reason']=='inherited_parent_qc'
    assert 'subset_cells' in outputs and 'inherited' in Path(outputs['methods']['path']).read_text().lower()
    assert {m['key']:m['sha256'] for m in parent['outputs']}==parent_hashes


def test_single_cell_annotation_figure_reuses_saved_umap_and_retains_uncertainty(tmp_path):
    from app.adapters.bio_engine.figure import render
    from app.adapters.bio_engine.manifest import Writer
    from scipy import sparse
    import anndata as ad
    import pandas as pd
    rawdir=tmp_path/'raw';rawdir.mkdir();w=Writer(rawdir)
    counts=sparse.csr_matrix(np.array([[1,2,3],[2,3,4],[3,4,5]],dtype='int64'))
    w.matrix('matrix',counts);w.json('features_index',dict(feature_ids=['g1','g2','g3'],feature_symbols=['G1','G2','G3'],feature_types=['Gene Expression']*3));w.json('barcodes_index',{'barcodes':['a','b','c']})
    raw=dict(manifest=dict(assay='single_cell',input_shape=dict(observations=3,features=3)),members={m['key']:m for m in w.artifacts})
    parentdir=tmp_path/'parent';parentdir.mkdir();p=Writer(parentdir)
    obj=ad.AnnData(counts.astype('float32'),obs=pd.DataFrame(dict(raw_index=[0,1,2],cluster=['0','0','1']),index=['a','b','c']))
    obj.obsm['X_umap']=np.array([[1.,2.],[3.,4.],[5.,6.]])
    path=parentdir/'processed.h5ad';obj.write_h5ad(path);p.existing('processed',path,'h5ad')
    anndir=tmp_path/'annotation';anndir.mkdir();a=Writer(anndir)
    a.json('geometry',dict(regions=[]));a.json('assignments',dict(rows=[dict(barcode='a',label_id='label',status='assigned'),dict(barcode='b',label_id='label',status='uncertain'),dict(barcode='c',label_id=None,status='unknown')]))
    output=tmp_path/'output';output.mkdir()
    result=render(dict(raw=raw,processed=dict(manifest={},members={m['key']:m for m in p.artifacts}),
        annotation=dict(members={m['key']:m for m in a.artifacts},labels=[dict(id='label',name='Candidate T',status='proposed')]),
        config=dict(kind='annotation',title='Cell labels',palette='tab20',output_language='en'),output_directory=str(output)))
    data=json.loads(Path(next(m['path'] for m in result['outputs'] if m['key']=='annotation_data')).read_text())
    assert data['barcodes']==['a','b','c'] and data['coordinates']==obj.obsm['X_umap'].tolist()
    assert data['color_labels']==['Candidate T [proposed]','Candidate T [uncertain]','unknown']
    assert data['basis']=='saved_X_umap_no_recomputation'
