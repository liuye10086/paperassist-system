from copy import deepcopy
import pytest
from app.domain.bioinformatics import single_cell_robustness as mod


def result(identifier='a', raw='raw', seed=1):
    return dict(source=dict(processed_dataset_version_id=identifier,raw_source={'dataset_version_id':raw},analysis_run_id='run-'+identifier),task_id='task-'+identifier,manifest=dict(assay='single_cell',params={'seed':seed}),observations=[dict(barcode=str(i),kept='True',cluster=str(i//2),donor='d1',donor_status='known',sample_id='s1') for i in range(4)],markers=[{'feature_id':'g1'}])


def compare(a,b):
    assert hasattr(mod,'compare_results'), 'Missing immutable result comparison'
    return mod.compare_results(a,b)


def test_labels_are_permutation_invariant_and_identity_preserved():
    a=result();b=result('b',seed=2);original=deepcopy(a)
    for row in b['observations']:row['cluster']='label-'+row['cluster']
    value=compare(a,b)
    assert value['clusters']['adjusted_rand_index']==1
    assert value['parameter_changes']=={'seed':{'baseline':1,'comparison':2}}
    assert value['baseline']['task_id']=='task-a'
    assert value['independence']['status']=='same_source'
    assert a==original


def test_subset_keeps_denominator_and_no_independent_cohort_claim():
    a=result();b=result('b');b['observations'][3]['kept']='False'
    value=compare(a,b)
    assert value['cells']=={'baseline':4,'comparison':3,'common':3,'jaccard':0.75}
    assert value['independence']['status']=='same_source'


@pytest.mark.parametrize('donor,expected',[('d1','overlapping_donors'),('','unknown_donors'),('other','independence_unverified')])
def test_different_source_never_matches_barcodes_or_certifies_independence(donor,expected):
    a=result();b=result('b','other')
    for row in b['observations']:row['donor']=donor
    value=compare(a,b)
    assert value['clusters']['adjusted_rand_index'] is None
    assert value['cells']['common'] is None
    assert value['independence']['status']==expected
    assert value['independence']['independent_validation'] is False


def test_missing_labels_and_empty_markers_are_not_perfect_stability():
    a=result();b=result('b');a['markers']=[];b['markers']=[]
    for row in b['observations']:row['cluster']=''
    value=compare(a,b)
    assert value['clusters']['adjusted_rand_index'] is None
    assert value['markers']['jaccard'] is None


def test_same_result_is_not_a_repeat():
    with pytest.raises(ValueError,match='distinct_results_required'):compare(result(),result())

def test_repeat_context_retains_mapping_design_and_blocks_subset():
    recipe=dict(params_json={'seed':2},observation_map_version_id='m1',design_version_id='d1')
    value=mod.repeat_context(recipe,{'subset':{'parent':'p'}})
    assert value==dict(params={'seed':2},observation_map_version_id='m1',design_version_id='d1',repeat_allowed=False)

def test_nontrivial_partition_disagreement():
    a=result();b=result('b')
    for i,row in enumerate(b['observations']):row['cluster']=str(i%2)
    assert compare(a,b)['clusters']['adjusted_rand_index']==pytest.approx(-0.5)


def test_saved_result_reader_rejects_unfinished_task(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.adapters.bio_analysis_store import BioAnalysisStore
    from app.core.exceptions import StorageError
    fake=SimpleNamespace(store=SimpleNamespace(connection=lambda:nullcontext(None),require_project=lambda *a:None,require_task=lambda *a:{'status':'cancelled'}),processed_record=lambda *a:({'run_id':'r'}, {}, []),require=lambda *a:{'task_id':'t'})
    monkeypatch.setattr('app.adapters.bio_analysis_store.BioAnalysisStore',lambda _:fake)
    with pytest.raises(StorageError):mod.load_comparison(None,'p','a','b')


def test_saved_result_reader_does_not_swallow_owner_denial(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    def deny(*args):raise PermissionError('wrong owner')
    fake=SimpleNamespace(store=SimpleNamespace(connection=lambda:nullcontext(None),require_project=deny))
    monkeypatch.setattr('app.adapters.bio_analysis_store.BioAnalysisStore',lambda _:fake)
    with pytest.raises(PermissionError):mod.load_comparison(None,'p','a','b')
