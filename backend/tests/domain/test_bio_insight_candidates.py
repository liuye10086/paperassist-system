import importlib
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def engine():return importlib.import_module('app.adapters.bio_insights_engine.candidates')


def sources():
    result={
        'a':{'G1':{'effect':2.,'q':0.01,'row_key':'a1'},'G2':{'effect':-2.,'q':0.02,'row_key':'a2'},'G3':{'effect':None,'q':None,'row_key':'a3'}},
        'b':{'G1':{'effect':1.,'q':0.03,'row_key':'b1'},'G2':{'effect':2.,'q':0.04,'row_key':'b2'},'G4':{'effect':0.,'q':0.,'row_key':'b4'}},
    }
    for rows in result.values():
        for row in rows.values():row.update(numerator='A',denominator='B',effect_name='log2fc',effect_unit='log2')
    return result


def test_set_recipe_keeps_step_counts_and_direction_conflicts():
    e=engine();recipe=[{'operation':'intersection','source_ids':['a','b']},{'operation':'same_direction','source_ids':['a','b']}]
    value=e.apply_recipe(sources(),recipe,{})
    assert value['selected']==['G1']
    assert [(r['before_count'],r['after_count'],r['removed_count']) for r in value['steps']]==[(4,2,2),(2,1,1)]
    assert any(r['feature_id']=='G2' and r['reason']=='direction_conflict_or_unknown' for r in value['exclusions'])


def test_threshold_source_membership_is_not_minimum_p_across_sources():
    e=engine();data=sources();data['a']['G1']['q']=0.5
    value=e.apply_recipe(data,[{'operation':'threshold','source_ids':['a'],'q_threshold':0.05,'minimum_absolute_effect':1.},
        {'operation':'intersection','source_ids':['a','b']}],{})
    assert value['selected']==['G2']
    assert 'G1' not in value['source_sets']['a'] and 'G1' in value['source_sets']['b']


def test_empty_intersection_is_valid_and_later_union_does_not_undo_exclusion():
    e=engine();value=e.apply_recipe(sources(),[{'operation':'exclude','feature_ids':['G1','G2','G3','G4']},
        {'operation':'union','source_ids':['a','b']}],{})
    assert value['selected']==[] and all(row['after_count']==0 for row in value['steps'])


def test_annotation_unknown_is_not_false_or_zero():
    e=engine();annotations={'G1':{'flag':{'value':False,'evidence_status':'provided'}},'G2':{'flag':{'value':None,'evidence_status':'unknown'}}}
    known=e.apply_recipe(sources(),[{'operation':'annotation','annotation_field':'flag','annotation_operator':'known'}],annotations)
    assert known['selected']==['G1']
    false=e.apply_recipe(sources(),[{'operation':'annotation','annotation_field':'flag','annotation_operator':'eq','annotation_value':False}],annotations)
    assert false['selected']==['G1']


def test_weighted_missing_required_component_remains_unknown():
    e=engine();weights=[{'item':'support_fraction','weight':0.5,'required':True},{'item':'primary_significance','weight':0.5,'required':True}]
    score=e.weighted_score({'support_fraction':1.,'primary_significance':None},weights)
    assert score['score'] is None and score['missing_required']==['primary_significance']
    optional=e.weighted_score({'support_fraction':1.,'primary_significance':None},[{**w,'required':False} for w in weights])
    assert optional['score']==1. and optional['available_weight']==0.5
    assert optional['score_status']=='partial'


def test_same_direction_rejects_incompatible_effect_or_comparison_definition():
    e=engine();data=sources();data['b']['G1']['effect_unit']='percentage'
    result=e.apply_recipe(data,[{'operation':'same_direction','source_ids':['a','b']}],{})
    assert result['selected']==[]
    assert any(r['feature_id']=='G1' and r['reason']=='direction_not_comparable' for r in result['exclusions'])


def test_source_dependency_groups_do_not_claim_independent_replication():
    e=engine();groups=e.dependency_groups({'a':['same'],'b':['same'],'c':['other'],'d':[]})
    assert groups['source_group']['a']==groups['source_group']['b']
    assert groups['unknown_sources']==['d'] and groups['independence_verified'] is False


def test_at_least_k_counts_each_source_once():
    e=engine();value=e.apply_recipe(sources(),[{'operation':'at_least_k','source_ids':['a','b'],'k':2}],{})
    assert value['selected']==['G1','G2']
    with pytest.raises(ValueError):e.apply_recipe(sources(),[{'operation':'at_least_k','source_ids':['a'],'k':2}],{})


def test_missing_requested_genes_are_listed_without_becoming_candidates():
    value=engine().apply_recipe(sources(),[{'operation':'include','feature_ids':['G1','absent']}],{})
    assert value['selected']==['G1']
    assert value['missing_requested_features']==[{'step':1,'feature_id':'absent','reason':'absent_from_input_evidence'}]


def test_weight_coverage_is_relative_to_total_and_partial_is_explicit():
    value=engine().weighted_score({'support_fraction':0.5,'primary_significance':None},[
        {'item':'support_fraction','weight':2,'required':False}, {'item':'primary_significance','weight':6,'required':False}])
    assert value['total_weight']==8 and value['weight_coverage']==0.25
    assert value['partial_score']==0.5 and value['complete_score'] is None


def test_default_ranking_prefers_same_direction_support_to_total_sources():
    rows=[dict(feature_id='mixed',same_direction_support_count=3,support_count=5,conflict_count=2,primary_q=.001,primary_effect=3),
          dict(feature_id='consistent',same_direction_support_count=4,support_count=4,conflict_count=0,primary_q=.01,primary_effect=2)]
    assert sorted(rows,key=engine().default_ranking_key)[0]['feature_id']=='consistent'
