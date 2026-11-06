import csv
import json
from pathlib import Path

import numpy as np
from scipy import sparse


def test_annotation_exports_full_ordered_candidates_scores_and_reference(tmp_path,monkeypatch):
    from app.adapters.bio_engine.annotation import run
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.single_cell_r import bridge
    from app.adapters.bio_analysis_process import validate_engine_result
    source=tmp_path/'source';source.mkdir();writer=Writer(source)
    writer.json('raw_axes',dict(barcodes=['excluded','c1','c2'],feature_ids=['g1','g2','g3'],feature_symbols=['G1','G2','G3'],feature_types=['Gene Expression']*3))
    writer.array('observation_mask',np.array([False,True,True]));writer.array('feature_mask',np.array([True,True,False]))
    logged=sparse.csr_matrix(np.array([[1.,2.],[3.,4.]],dtype='float32'));writer.matrix('log1p',logged)
    class Bridge:
        versions={'SingleR':'2.8.0','R':'4.4.3'}
        def classify(self,expression,cells,genes,config,seed):
            assert (expression!=logged).nnz==0 and cells==['c1','c2'] and genes==['g1','g2'] and seed==7
            return dict(status='completed',reason=None,cells=cells,candidate_labels=['B','T'],pruned_labels=['B','unknown'],label_status=['candidate','unknown'],
                scores=np.array([[.9,.2],[.4,.5]]),score_labels=['B','T'],delta_next=np.array([.7,.1]),delta_median=np.array([.35,.05]),
                candidate_ranks=[['B','T'],['T','B']],score_semantics='initial_Spearman_not_probability',
                reference=dict(reference_id='reference',version='1',gene_ids=['g1','g2'],sha256='a'*64,source='official'),
                matching=dict(matched_test_genes=2,common_gene_ids=['g1','g2']),logs=['SingleR complete'])
        def release_temporaries(self):pass
    monkeypatch.setattr(bridge,'get_bridge',lambda:Bridge())
    output=tmp_path/'output';output.mkdir()
    result=run(dict(mode='annotation',processed=dict(manifest={'assay':'single_cell'},members={m['key']:m for m in writer.artifacts}),
        config=dict(reference_id='reference',species='Homo sapiens',gene_id_type='ensembl_gene_id',label_level='main',seed=7),identity={},output_directory=str(output)))
    validate_engine_result(result,output,mode='annotation')
    members={m['key']:m for m in result['outputs']}
    def rows(key):return list(csv.DictReader(Path(members[key]['path']).read_text().splitlines(),delimiter='\t'))
    candidates=rows('annotation_candidates');scores=rows('annotation_scores')
    assert [r['barcode'] for r in candidates]==['c1','c2']
    assert candidates[1]['pruned_label']=='unknown' and candidates[1]['status']=='unknown'
    assert float(scores[0]['B'])==.9 and len(scores)==2
    assert result['manifest']['algorithm']=='SingleR' and result['manifest']['tool_version']=='2.8.0'
    assert 'gene_ids' not in result['manifest']['reference'] and 'common_gene_ids' not in result['manifest']['matching']
    full=json.loads(Path(members['annotation_reference']['path']).read_text())
    assert full['reference']['gene_ids']==['g1','g2'] and full['matching']['common_gene_ids']==['g1','g2']
    assert 'SingleR complete' in Path(members['annotation_tool_logs']['path']).read_text()
    assert not any(m['format']=='pdf' for m in result['outputs'])
