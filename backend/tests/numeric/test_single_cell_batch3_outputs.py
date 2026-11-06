import json
from pathlib import Path
import numpy as np


def test_pipeline_exports_adjustment_evidence_and_preserves_expression(tmp_path):
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_engine.pipeline import run
    from tests.numeric.test_single_cell_batch3_algorithms import sample
    import anndata as ad
    counts,logged,genes,batches=sample();cells=[f'cell{i}' for i in range(len(batches))]
    source=tmp_path/'source';source.mkdir();writer=Writer(source)
    writer.matrix('matrix',counts);writer.json('features_index',dict(feature_ids=genes,feature_symbols=genes,feature_types=['Gene Expression']*len(genes)))
    writer.json('barcodes_index',dict(barcodes=cells));writer.json('observation_map_index',dict(rows=[dict(barcode=c,library_id=b,batch=dict(status='known',value=b),group=dict(status='known',value='healthy')) for c,b in zip(cells,batches)]))
    output=tmp_path/'output';output.mkdir()
    result=run(dict(mode='compute',raw=dict(manifest=dict(assay='single_cell',input_shape=dict(observations=80,features=36)),members={m['key']:m for m in writer.artifacts}),
        config=dict(min_spots=1,hvg_count=12,pca_components=6,hvg_batch_key='batch',technical_covariates=['log1p_total_counts'],harmony=dict(enabled=False)),output_directory=str(output)))
    from app.adapters.bio_analysis_process import validate_engine_result,validate_processed_arrays
    assert validate_engine_result(result,output,mode='compute') is result
    assert validate_processed_arrays(result['outputs'])['observations']==80
    state=result['summary']['single_cell_integration']
    assert state['technical_covariates']['applied'] is True and state['hvg']['applied'] is True
    assert state['downstream_representation']=='X_pca' and state['harmony']['status']=='not_requested'
    outputs={m['key']:m for m in result['outputs']}
    assert {'integration_x_pca','integration_x_pca_unadjusted','integration_coordinates','integration_covariates_png','integration_diagnostics','integration_design','integration_summary'}<=outputs.keys()
    obj=ad.read_h5ad(outputs['processed']['path'])
    assert set(obj.obsm)>={'X_pca','X_pca_unadjusted'} and 'X_pca_harmony' not in obj.obsm
    assert (obj.layers['counts']!=counts).nnz==0
    np.testing.assert_allclose(obj.X.toarray(),logged.toarray())
    assert json.loads(obj.uns['paperassist_integration_json'])['downstream_representation']=='X_pca'
    assert 'X_pca' in Path(outputs['methods']['path']).read_text()
