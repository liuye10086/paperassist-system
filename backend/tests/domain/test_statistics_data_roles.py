import pytest
from pydantic import ValidationError
from app.core.exceptions import StorageError
@pytest.fixture(autouse=True)
def postgres_schema(): yield None

def test_absent_roles_serialize_exactly_as_old_selection():
    from tests.domain.test_analysis_plan import selection
    assert 'data_roles' not in selection().model_dump()

def test_repeated_individuals_cannot_be_independent_inference():
    from app.domain.statistics_roles import StatisticsDataRoles,validate_role_records
    roles=StatisticsDataRoles(individual_id='A',time='B',endpoint='C',structure='repeated_long')
    rows=[dict(row=2,A='p1',B='t1',C=1),dict(row=3,A='p1',B='t2',C=2)]
    with pytest.raises(StorageError,match='重复'): validate_role_records(rows,roles,inference=True)
    assert validate_role_records(rows,roles,inference=False)['individual_n']==1

def test_duplicate_individual_time_endpoint_rejected_without_averaging():
    from app.domain.statistics_roles import StatisticsDataRoles,long_pairs
    roles=StatisticsDataRoles(individual_id='A',time='B',endpoint='C',structure='paired_long',time_order=['t0','t1'])
    rows=[dict(row=2,A='p1',B='t0',C=1),dict(row=3,A='p1',B='t0',C=2)]
    with pytest.raises(StorageError,match='重复'): long_pairs(rows,roles)

def test_long_pairs_keep_complete_units_and_missing_audit():
    from app.domain.statistics_roles import StatisticsDataRoles,long_pairs
    roles=StatisticsDataRoles(individual_id='A',time='B',endpoint='C',structure='paired_long',time_order=['t0','t1'])
    rows=[dict(row=2,A='p1',B='t0',C=1),dict(row=3,A='p1',B='t1',C=4),dict(row=4,A='p2',B='t0',C=2)]
    result=long_pairs(rows,roles)
    assert result['groups']==[[1.0],[4.0]]
    assert result['group_rows']==[[2],[3]]
    assert result['excluded_rows'][0]['reason']=='incomplete_pair'
    assert result['individual_n']==1

def test_dictionary_rejects_unit_conflicts_and_duplicate_column_entries():
    from app.domain.statistics_roles import StatisticsDataRoles
    with pytest.raises(ValidationError): StatisticsDataRoles(dictionary=[dict(column='C',unit='kg'),dict(column='C',unit='cm')])


def long_sheet():
    from app.domain.dataset_preparation.contracts import PreparedSheet
    rows=[('p1','t0',1),('p1','t1',4),('p2','t0',2),('p2','t1',6),('p3','t0',3),('p3','t1',9),('p4','t0',5)]
    cells=[dict(row=r,column=c,coordinate=f'{chr(64+c)}{r}',kind='number' if c==3 else 'text',value=str(v)) for r,values in enumerate(rows,2) for c,v in enumerate(values,1)]
    return PreparedSheet(index=0,name='Long',data_range='A2:C8',merged_ranges=[],fields=[dict(column=c,name=name,unit=dict(status='confirmed',value='kg' if c==3 else '')) for c,name in enumerate(('ID','Time','BMI'),1)],cells=cells)

def long_selection():
    from app.domain.comparison.contracts import ComparisonSelection
    return ComparisonSelection(task_type='group_comparison',sheet_name='Long',design='paired',method='paired_t',numeric_column='C',group_column=None,groups=[],pair_id_column='A',before_column=None,after_column=None,unit='kg',missing_policy='complete_pairs',posthoc='none',assumptions=dict(independent_units=True,distribution='normal',inference_confirmed=True),data_roles=dict(individual_id='A',endpoint='C',time='B',structure='paired_long',time_order=['t0','t1']))

def test_real_comparison_precheck_freezes_two_timepoint_pairs_and_all_original_rows():
    from app.domain.comparison.checks import selected_records,build_comparison_check
    from app.domain.research_results.statistics_figures import render_statistics_figure
    groups,variables,audit,labels=selected_records(long_sheet(),long_selection())
    assert groups==[[1.,2.,3.],[4.,6.,9.]]
    assert audit['included_rows']==[2,3,4,5,6,7]
    assert audit['group_rows']==[[2,4,6],[3,5,7]]
    assert audit['excluded_rows'][0]['row']==8

@pytest.mark.skipif(__import__('sys').platform!='linux',reason='numeric_environment_unavailable: plan profile requires fixed Linux statistics sandbox')
def test_long_pair_plan_profile_has_correct_source_row_counts():
    from app.domain.comparison.checks import build_comparison_check
    research=dict(question='Synthetic paired comparison',output_language='en',population='synthetic',study_design='paired',observation_unit='person',observation_structure='paired',relationship_description='two times',output_requirements='')
    check=build_comparison_check(long_sheet(),long_selection(),research)
    assert check['selection_check']['valid_count']==6 and check['selection_check']['excluded_count']==1
    assert not any(i['severity']=='blocking' for i in check['issues'])

def test_declared_dictionary_cannot_contradict_frozen_measurement_unit():
    from app.domain.statistics_roles import validate_sheet_roles
    chosen=long_selection();chosen.data_roles.dictionary=[__import__('app.domain.statistics_roles',fromlist=['RoleField']).RoleField(column='C',unit='cm',unit_status='declared')]
    with pytest.raises(StorageError,match='单位'):validate_sheet_roles(long_sheet(),chosen)
