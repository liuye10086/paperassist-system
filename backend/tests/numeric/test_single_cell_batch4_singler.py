"""SingleR boundary contracts; numerical tests require the pinned Linux runtime."""
import json
from pathlib import Path

from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import numpy as np
import pytest
from scipy import sparse

from app.adapters.single_cell_r import annotation


def test_log_expression_rejects_shifted_duplicate_axes_and_nonfinite_values():
    x=sparse.csr_matrix([[0.,1.],[2.,0.]])
    annotation.validate_expression(x,['b','a'],['ENSG1','ENSG2'])
    for cells,genes in [(['a'],['ENSG1','ENSG2']),(['a','a'],['ENSG1','ENSG2']),(['a','b'],['ENSG1','ENSG1'])]:
        with pytest.raises(ValueError,match='axis'):annotation.validate_expression(x,cells,genes)
    for bad in [np.nan,np.inf,-.1]:
        y=x.copy();y.data[0]=bad
        with pytest.raises(ValueError,match='expression'):annotation.validate_expression(y,['a','b'],['ENSG1','ENSG2'])


def test_reference_never_guesses_species_or_gene_identifier_namespace(tmp_path):
    config=dict(reference_id='monaco_immune_1.0.0',species='Homo sapiens',gene_id_type='ensembl_gene_id',label_level='main')
    for missing in ['species','gene_id_type']:
        bad=config.copy();bad.pop(missing)
        with pytest.raises(ValueError,match='reference'):annotation.resolve_reference(bad,tmp_path)
    for key,value in [('species','Mus musculus'),('gene_id_type','symbol'),('reference_id','../../ref')]:
        with pytest.raises(ValueError,match='reference'):annotation.resolve_reference({**config,key:value},tmp_path)
    with pytest.raises(ValueError,match='reference_unavailable'):annotation.resolve_reference(config,tmp_path)


def test_pruned_na_is_unknown_and_initial_rank_is_distinct_from_tuned_label():
    actual=annotation.validate_result(['c2','c1'],['T','B'],['','B'],np.array([[.9,.8],[.2,.7]]),['B','T'],[.1,.2],[.05,.3])
    assert actual['pruned_labels']==['unknown','B']
    assert actual['candidate_labels']==['T','B']
    assert actual['candidate_ranks']==[['B','T'],['T','B']]
    assert actual['label_status']==['unknown','candidate']
    with pytest.raises(ValueError,match='result'):annotation.validate_result(['c'],['B'],['invented'],np.array([[.1,.2]]),['B','T'],[.1],[.2])


def test_reference_manifest_checks_content_and_exposes_matching_policy(tmp_path):
    config=dict(reference_id='monaco_immune_1.0.0',species='Homo sapiens',gene_id_type='ensembl_gene_id',label_level='main')
    reference=tmp_path/config['reference_id'];reference.mkdir()
    ref=reference/'reference.rds';ref.write_bytes(b'fixed reference')
    import hashlib
    meta=dict(reference_id=config['reference_id'],species='Homo sapiens',gene_id_type='ensembl_gene_id',version='1.0.0',source='celldex::MonacoImmuneData',license='CC0-1.0',sha256=hashlib.sha256(ref.read_bytes()).hexdigest(),gene_ids=['ENSG1','ENSG2'],samples=114,labels_main=['B','T'],labels_fine=['B1','T1'])
    (reference/'reference.json').write_text(json.dumps(meta),encoding='utf-8')
    result=annotation.resolve_reference(config,tmp_path)
    assert result['path']==ref
    assert result['metadata']['sha256']==meta['sha256']
    matching=annotation.match_genes(['ENSG2','ENSG3','ENSG1'],result['metadata'])
    assert matching['common_gene_ids']==['ENSG2','ENSG1']
    assert matching['matched_test_genes']==2 and matching['unmatched_test_genes']==1
    ref.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):annotation.resolve_reference(config,tmp_path)


@pytest.mark.skipif(not Path('/opt/paperassist-single-cell-r/lib/R').is_dir(),reason='pinned Linux R runtime required')
def test_single_r_real_scoring_matches_native_and_preserves_shuffled_cell_axis(tmp_path,monkeypatch):
    from app.adapters.single_cell_r.bridge import initialize
    bridge=initialize(tmp_path);ro=bridge.ro
    cells=['z','a','b','y'];genes=[f'ENSG{i:011}' for i in range(80)]
    rng=np.random.default_rng(27)
    ref=rng.poisson(2,(80,12)).astype(float);ref[:35,:6]+=10;ref[35:70,6:]+=10;ref=np.log1p(ref)
    x=sparse.csr_matrix(ref[:,[8,1,2,9]].T)
    folder=tmp_path/annotation.REFERENCE_ID;folder.mkdir()
    path=folder/'reference.rds'
    ro.r('''function(values,genes,path) {
      mat <- matrix(values,nrow=length(genes),dimnames=list(genes,paste0("r",1:12)))
      saveRDS(list(logcounts=mat,labels_main=rep(c("B","T"),each=6),labels_fine=rep(c("B","T"),each=6)),path)
    }''')(ro.FloatVector(ref.ravel(order='F')),ro.StrVector(genes),str(path))
    import hashlib
    meta=dict(reference_id=annotation.REFERENCE_ID,species='Homo sapiens',gene_id_type='ensembl_gene_id',version='1.0.0',source='synthetic_validation_only',license='CC0-1.0',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),gene_ids=genes,samples=12)
    (folder/'reference.json').write_text(json.dumps(meta),encoding='utf-8')
    monkeypatch.setattr(annotation,'REFERENCE_ROOT',tmp_path)
    config=dict(reference_id=annotation.REFERENCE_ID,species='Homo sapiens',gene_id_type='ensembl_gene_id',label_level='main')
    actual=bridge.classify(x,cells,genes,config,27)
    assert actual['status']=='completed',actual
    expected=ro.r('''function(values,cells,genes,path) {
      ref <- readRDS(path)
      test <- matrix(values,nrow=length(genes),dimnames=list(genes,cells))
      as.list(SingleR::SingleR(test,ref$logcounts,labels=ref$labels_main,genes="de",de.method="classic",
        quantile=.8,fine.tune=TRUE,tune.thresh=.05,prune=TRUE,
        BPPARAM=BiocParallel::SerialParam(progressbar=FALSE),BNPARAM=BiocNeighbors::KmknnParam()))
    }''')(ro.FloatVector(x.toarray().T.ravel(order='F')),ro.StrVector(cells),ro.StrVector(genes),str(path))
    assert actual['cells']==cells
    assert actual['candidate_labels']==list(map(str,expected.rx2('labels')))
    np.testing.assert_allclose(actual['scores'],np.asarray(expected.rx2('scores')),atol=1e-12)
    np.testing.assert_allclose(actual['delta_next'],np.asarray(expected.rx2('delta.next')),atol=1e-12)
    assert actual['matching']['matched_test_genes']==80
    assert bridge.versions['SingleR']=='2.8.0'
    missing=bridge.classify(x,cells,[gene+'.1' for gene in genes],config,27)
    assert missing['status']=='not_computable' and missing['reason']=='insufficient_common_genes'
    zeros=bridge.classify(sparse.csr_matrix(x.shape),cells,genes,config,27)
    assert zeros['status']=='not_computable' and zeros['reason']=='no_expression_on_common_genes'


def test_reference_catalog_reads_only_operator_published_metadata(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPERASSIST_SINGLE_CELL_REFERENCE_ROOT',str(tmp_path))
    assert annotation.reference_catalog()[0]['available'] is False
    folder=tmp_path/annotation.REFERENCE_ID;folder.mkdir()
    metadata=dict(reference_id=annotation.REFERENCE_ID,species='Homo sapiens',version='1.0.0',gene_id_type='ensembl_gene_id',sha256='a'*64,samples=114,source='synthetic validation only',license='CC0-1.0')
    (folder/'reference.json').write_text(json.dumps(metadata),encoding='utf-8')
    entry=annotation.reference_catalog()[0]
    assert entry['available'] and entry['sha256']=='a'*64
    assert entry['availability_scope'].startswith('published_metadata')
    assert entry['species_taxon_id']==9606
