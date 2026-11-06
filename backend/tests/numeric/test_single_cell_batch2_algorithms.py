import numpy as np
import pytest
from scipy import sparse


def test_sparse_bridge_rejects_double_precision_loss():
    from app.adapters.single_cell_r.bridge import validate_counts
    with pytest.raises(ValueError,match='r_counts_precision'):
        validate_counts(sparse.csr_matrix([[2**53]],dtype='int64'),['a'],['g'])


@pytest.mark.parametrize('reason,logs,expected',[
    ('tool_failed',['error: cannot allocate vector of size 103.0 Mb'],'resource_insufficient'),
    ('tool_failed',['error: cannot allocate memory block of size 512 Mb'],'resource_insufficient'),
    ('tool_failed',['error: Permission denied'],'tool_failed'),
    ('insufficient_model_conditions',['not enough cells'],'insufficient_model_conditions'),
])
def test_r_allocation_failure_has_explicit_narrow_resource_reason(reason,logs,expected):
    from app.adapters.single_cell_r.bridge import classify_failure_reason
    assert classify_failure_reason(reason,logs)==expected


def test_algorithm_axes_library_separation_filter_and_partial_layer(monkeypatch):
    from app.adapters.single_cell_r import algorithms
    calls=[]
    class Bridge:
        versions={'R':'4.4.3','scDblFinder':'1.20.2','decontX':'1.4.0'}
        releases=0
        def release_temporaries(self):self.releases+=1
        def run(self,counts,cells,genes,tool,seed,expected_rate=None):
            calls.append((tool,cells,list(genes),counts.copy()))
            if tool=='scdblfinder':return dict(status='completed',reason=None,score=[.1,.9],prediction=['singlet','doublet'],logs=['real bridge replaced only for axis orchestration test'])
            if cells[0]=='c':return dict(status='not_computable',reason='insufficient_cells',logs=[])
            return dict(status='completed',reason=None,contamination=[.1,.2],counts=counts.astype('float64')*.75,logs=[])
    bridge=Bridge()
    monkeypatch.setattr(algorithms,'get_bridge',lambda:bridge)
    raw=sparse.csr_matrix([[1,2],[3,4],[5,6],[7,8]],dtype='int64')
    config=dict(seed=3,doublet=dict(enabled=True,exclude_predicted=True),decontx=dict(enabled=True))
    result=algorithms.run_algorithms(raw,['a','b','c','d'],['g2','g1'],['L1','L1','L2','L2'],config)
    assert [c[1] for c in calls]==[['a','b'],['a','b'],['c','d'],['c','d']]
    assert result['keep'].tolist()==[True,False,True,False]
    assert result['decontx_counts'] is None
    assert result['summary']['decontx']['status']=='partial'
    assert result['summary']['doublet']['predicted_doublets']==2
    assert result['observations'][1]['doublet_excluded'] is True
    assert bridge.releases>=4
    np.testing.assert_array_equal(raw.toarray(),[[1,2],[3,4],[5,6],[7,8]])


def test_disabled_tools_do_not_initialize_r(monkeypatch):
    from app.adapters.single_cell_r import algorithms
    monkeypatch.setattr(algorithms,'get_bridge',lambda:pytest.fail('disabled tools initialized R'))
    value=algorithms.run_algorithms(sparse.eye(2,format='csr',dtype='int64'),['a','b'],['g1','g2'],[None,None],{})
    assert value['summary']['doublet']['status']=='not_requested'
    assert value['summary']['decontx']['corrected_cells']==0


def test_zero_qc_library_is_reported_instead_of_silently_dropped(monkeypatch):
    from app.adapters.single_cell_r import algorithms
    class Bridge:
        versions={}
        def release_temporaries(self):pass
        def run(self,*args):pytest.fail('empty library must not run')
    monkeypatch.setattr(algorithms,'get_bridge',lambda:Bridge())
    value=algorithms.run_algorithms(sparse.csr_matrix((0,3),dtype='int64'),[],['a','b','c'],[],dict(decontx=dict(enabled=True)),all_libraries=['empty'])
    assert value['library_algorithms'][-1]['reason']=='no_preliminary_qc_cells'
    assert value['summary']['decontx']['not_computable_libraries']==1


def test_all_libraries_memory_failure_preserves_specific_summary_reason(monkeypatch):
    from app.adapters.single_cell_r import algorithms
    class Bridge:
        versions={}
        def run(self,*args):return dict(status='failed',reason='resource_insufficient',logs=['cannot allocate vector of size 103.0 Mb'])
        def release_temporaries(self):pass
    monkeypatch.setattr(algorithms,'get_bridge',lambda:Bridge())
    value=algorithms.run_algorithms(sparse.eye(4,format='csr',dtype='int64'),['a','b','c','d'],['g1','g2','g3','g4'],['L1']*4,dict(decontx=dict(enabled=True)))
    assert value['summary']['decontx']['status']=='failed'
    assert value['summary']['decontx']['reason']=='resource_insufficient'
