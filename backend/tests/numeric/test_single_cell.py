import io
import numpy as np
import pytest
from scipy import sparse
import h5py


def h5ad(tmp_path,encoding='csr_matrix',values=None):
    path=tmp_path/'cells.h5ad'
    with h5py.File(path,'w') as f:
        for axis,ids in [('obs',[b'c1',b'c2']),('var',[b'g1',b'g2'])]:
            f.create_group(axis).create_dataset('_index',data=ids)
        for name,data in [('X',[[1,0],[2,3]]),('raw/X',[[4,0,5],[0,6,0]])]:
            m=sparse.csr_matrix(data) if encoding=='csr_matrix' else sparse.csc_matrix(data)
            g=f.create_group(name);g.attrs['encoding-type']=encoding;g.attrs['shape']=m.shape
            g.create_dataset('data',data=np.asarray(values if values is not None and name=='X' else m.data,dtype=float));g.create_dataset('indices',data=m.indices);g.create_dataset('indptr',data=m.indptr)
        f['raw'].create_group('var').create_dataset('_index',data=[b'r1',b'r2',b'r3'])
    return path


@pytest.mark.parametrize('encoding',['csr_matrix','csc_matrix'])
def test_h5ad_counts_axes_are_selected_not_inferred(tmp_path,encoding):
    from app.adapters.bio_engine.hdf5_checks import read_h5ad_counts
    path=h5ad(tmp_path,encoding)
    m,features,barcodes,a=read_h5ad_counts(path,dict(matrix='raw.X',obs_index='_index',var_index='_index',symbol_column=None))
    assert features['feature_ids']==['r1','r2','r3']
    assert barcodes==['c1','c2']
    np.testing.assert_array_equal(m.toarray(),[[4,0,5],[0,6,0]])
    assert a['float_integer_counts_converted']


def test_h5ad_invalid_layer_and_fractional_values_rejected(tmp_path):
    from app.adapters.bio_engine.hdf5_checks import read_h5ad_counts
    path=h5ad(tmp_path,values=[1,2.5,3])
    selection=dict(matrix='X',obs_index='_index',var_index='_index',symbol_column=None)
    with pytest.raises(ValueError,match='count'):read_h5ad_counts(path,selection)
    with pytest.raises(ValueError,match='selected'):read_h5ad_counts(path,{**selection,'matrix':'layers/counts'})


def test_cell_aggregation_conserves_counts_and_missing_donor_blocks_only_inference():
    from app.adapters.bio_engine.single_cell import aggregate_cells
    counts=sparse.csr_matrix([[1,2],[3,0],[4,5]])
    rows=[dict(barcode='c'+str(i),sample_id=s,donor=d,group='A',cluster='0') for i,(s,d) in enumerate([('s1','d1'),('s1','d1'),('s2','d2')])]
    matrix,units,state=aggregate_cells(counts,rows,design_confirmed=True)
    np.testing.assert_array_equal(matrix.toarray(),[[4,2],[4,5]])
    assert matrix.sum()==counts.sum() and state['donors']==2 and state['cells']==3
    rows[2]['donor']=None
    _,_,state=aggregate_cells(counts,rows,design_confirmed=True)
    assert state['status']=='blocked' and state['exploration_allowed']


def test_qc_and_normalization_have_independent_hand_calculation():
    from app.adapters.bio_engine.qc import quality_control
    from app.adapters.bio_engine.preprocess import normalize
    raw=sparse.csr_matrix([[2,0,2],[0,0,0],[1,3,0]])
    features=dict(feature_ids=['g1','g2','g3'],feature_symbols=['a','b','c'],feature_types=['Gene Expression']*3)
    q=quality_control(raw,features,['a','b','c'],[],dict(min_gene_spots=1))
    assert q['obs_mask'].tolist()==[True,False,True]
    normalized,logged=normalize(q['filtered_counts'],target_sum=100)
    np.testing.assert_allclose(normalized.toarray(),[[50,0,50],[25,75,0]])
    np.testing.assert_allclose(logged.toarray(),np.log1p([[50,0,50],[25,75,0]]),rtol=1e-6)


def test_standard_anndata_written_h5ad_utf8_axes(tmp_path):
    import anndata as ad
    import pandas as pd
    from app.adapters.bio_engine.hdf5_checks import read_h5ad_counts
    obj=ad.AnnData(sparse.csr_matrix([[1.,0.],[2.,3.]]),obs=pd.DataFrame(index=['cell-α','cell-β']),var=pd.DataFrame(index=['g1','g2']))
    path=tmp_path/'standard.h5ad';obj.write_h5ad(path)
    matrix,features,cells,_=read_h5ad_counts(path,dict(matrix='X',obs_index='_index',var_index='_index'))
    assert cells==['cell-α','cell-β'] and features['feature_ids']==['g1','g2']
    np.testing.assert_array_equal(matrix.toarray(),[[1,0],[2,3]])


def test_mtx_10xh5_h5ad_equivalent_singlecell_intake(tmp_path):
    import hashlib
    from app.adapters.bio_engine.single_cell import import_counts
    from app.adapters.bio_engine.hdf5_checks import compare
    raw=sparse.csr_matrix([[1,0],[2,3]])
    mtx=tmp_path/'matrix.mtx';mtx.write_bytes(b'%%MatrixMarket matrix coordinate integer general\n2 2 3\n1 1 1\n1 2 2\n2 2 3\n')
    feature=tmp_path/'features.tsv';feature.write_bytes(b'g1\tg1\tGene Expression\ng2\tg2\tGene Expression\n')
    barcode=tmp_path/'barcodes.tsv';barcode.write_bytes(b'c1\nc2\n')
    h5=tmp_path/'matrix.h5'
    with h5py.File(h5,'w') as f:
        g=f.create_group('matrix');m=raw.T.tocsc()
        for k,v in dict(data=m.data.astype(float),indices=m.indices,indptr=m.indptr,shape=m.shape,barcodes=np.array([b'c1',b'c2'],dtype='S2')).items():g.create_dataset(k,data=v)
        fg=g.create_group('features')
        for k,v in dict(id=[b'g1',b'g2'],name=[b'g1',b'g2'],feature_type=[b'Gene Expression']*2).items():fg.create_dataset(k,data=np.array(v,dtype='S20'))
    h5ad_path=h5ad(tmp_path)
    versions=[]
    for rep,paths in [('mtx',[mtx,feature,barcode]),('10x_h5',[h5]),('h5ad',[h5ad_path])]:
        files=[dict(id=str(i),filename=p.name,path=str(p),size_bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for i,p in enumerate(paths)]
        config=dict(workflow_version='bio_import_v4',assay='single_cell',file_ids=[f['id'] for f in files],name='cells',expected_dataset_revision=0,matrix_representation=rep)
        if rep=='h5ad':config['h5ad']=dict(matrix='X',obs_index='_index',var_index='_index')
        result=import_counts(dict(files=files,single_cell_config=config,output_directory=str(tmp_path/rep)))
        leaves={m['key']:m for m in result['outputs']}
        matrix=sparse.csr_matrix(tuple(np.load(leaves[k]['path'],allow_pickle=False) for k in ['matrix_data','matrix_indices','matrix_indptr']),shape=(2,2))
        np.testing.assert_array_equal(matrix.toarray(),raw.toarray())
        assert not any(m['key']=='positions_index' for m in result['outputs'])
        assert result['manifest']['observation_level']=='cell'
        versions.append(result)


def test_single_cell_offline_probe_and_parent_receipt(tmp_path):
    from app.adapters.bio_engine.single_cell_probe import exercise
    from app.adapters.bio_single_cell_validation import validate_single_cell_probe
    result=exercise(tmp_path)
    assert validate_single_cell_probe(result)['counts']['cells']==4


def test_single_cell_real_mtx_integer_counts_and_fractional_rejection():
    from app.adapters.bio_engine.importer import _mtx
    from app.adapters.bio_parser.archive import Member
    from app.domain.bioinformatics.settings import BioLimits
    features=dict(feature_ids=['g1'],feature_symbols=['g1'],feature_types=['Gene Expression'])
    member=Member('matrix.mtx',b'%%MatrixMarket matrix coordinate real general\n1 2 2\n1 1 2.0\n1 2 3e0\n')
    matrix,attestation=_mtx(member,features,['c1','c2'],BioLimits(),allow_real_integer=True)
    assert matrix.toarray().tolist()==[[2],[3]] and attestation['real_integer_counts_converted']
    member.content=member.content.replace(b'2.0',b'2.5')
    with pytest.raises(Exception,match='integer_counts_required'):_mtx(member,features,['c1','c2'],BioLimits(),allow_real_integer=True)


def test_cell_aggregation_preserves_paired_donor_conditions():
    from app.adapters.bio_engine.single_cell import aggregate_cells
    counts=sparse.csr_matrix([[1,2],[3,0],[4,5],[2,1]])
    rows=[dict(sample_id=s,donor='d1',group=g,cluster='0') for s,g in [('pre','A'),('pre-tech','A'),('post','B'),('post','B')]]
    matrix,units,state=aggregate_cells(counts,rows,design_confirmed=True)
    np.testing.assert_array_equal(matrix.toarray(),[[4,2],[6,6]])
    assert [(u['donor'],u['group']) for u in units]==[('d1','A'),('d1','B')]
    assert state['donors']==1 and state['samples']==3 and matrix.sum()==counts.sum()
    rows[-1]['sample_id']='pre'
    matrix,units,state=aggregate_cells(counts,rows,design_confirmed=True)
    assert matrix is None and units==[]
    assert state['status']=='blocked' and state['reason']=='sample_donor_assignment_conflict' and state['exploration_allowed']


def test_h5_vlen_text_is_checked_one_value_at_a_time(tmp_path,monkeypatch):
    from app.adapters.bio_engine.hdf5_checks import inspect_hdf5
    path=tmp_path/'text.h5'
    with h5py.File(path,'w') as f:
        f.create_dataset('axis',data=['cell-α','cell-β'],dtype=h5py.string_dtype('utf-8'))
    reads=[];original=h5py.Dataset.__getitem__
    def tracked(dataset,key,*args,**kwargs):
        if dataset.name=='/axis':reads.append(key)
        return original(dataset,key,*args,**kwargs)
    monkeypatch.setattr(h5py.Dataset,'__getitem__',tracked)
    with h5py.File(path,'r') as f:
        _,logical=inspect_hdf5(f)
        assert logical==sum(len(v.encode('utf-8')) for v in ['cell-α','cell-β'])+2*f['axis'].dtype.itemsize
    assert reads==[0,1]
