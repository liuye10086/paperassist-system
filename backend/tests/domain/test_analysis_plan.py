"""Checks reuse the prepared scan and retain explicit unresolved decisions."""
import pytest
from app.domain.analysis import AnalysisSelection
from app.domain.dataset_preparation.contracts import PreparedSheet
from app.core.exceptions import StorageError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def sample(values=('1','3','5','7','9',None), unit=None, groups=('A',None,'A','B','B',None)):
    cells=[]
    for row,(value,group) in enumerate(zip(values,groups),5):
        if group is not None: cells.append(dict(row=row,column=3,coordinate=f'C{row}',kind='text',value=group))
        if value is not None: cells.append(dict(row=row,column=4,coordinate=f'D{row}',kind='number',value=value))
    return PreparedSheet(index=0,name='研究',data_range=f'C5:D{4+len(values)}',merged_ranges=[],
        fields=[dict(column=3,name='分组',unit=dict(status='unconfirmed',value=None)),
            dict(column=4,name='体重',unit=dict(status='confirmed' if unit is not None else 'unconfirmed',value=unit))],cells=cells)


def selection(**changes):
    return AnalysisSelection(task_type='descriptive_boxplot',sheet_name='研究',numeric_column='D',
        group_column=changes.pop('group_column','C'),unit=changes.pop('unit',''),missing_policy='exclude_selected_missing',**changes)


def test_full_prepared_range_observed_bounds_missing_and_declared_units():
    from app.domain.analysis_plan.checks import build_check, validate_resolutions
    check=build_check(sample(unit='mg'),selection(unit='mg'))
    assert (check['data_range'],check['row_count'])==('C5:D10',6)
    assert (check['selection_check']['valid_count'],check['selection_check']['excluded_count'])==(4,2)
    field=check['selected_fields'][0]
    assert (field['letter'],field['name'],field['observed_min'],field['observed_max'])==('D','体重',1.,9.)
    assert field['prepared_unit']=={'status':'confirmed','value':'mg'}
    assert field['declared_unit']=={'status':'label','value':'mg'}
    missing=next(i for i in check['issues'] if i['code']=='selected_missing')
    assert missing['count']==2 and missing['coordinates']==['C6','D10','C10']
    with pytest.raises(StorageError): validate_resolutions(check,{})
    resolutions={i['id']:i['allowed_resolutions'][0] for i in check['issues']}
    validate_resolutions(check,resolutions)
    with pytest.raises(StorageError): validate_resolutions(check,{**resolutions,'acknowledged':'true'})


@pytest.mark.parametrize('damage,code',[('type','numeric_type'),('precision','numeric_precision'),('unit','unit_conflict'),('empty','no_complete_records')])
def test_blocking_checks_remain_readable_and_cannot_be_approved(damage,code):
    from app.domain.analysis_plan.checks import build_check,validate_resolutions
    sheet=sample(unit='mg')
    if damage=='type': sheet.cells[1].kind='text'
    if damage=='precision': sheet.cells[1].value='9007199254740992'
    if damage=='empty': sheet=sample(values=(None,None),groups=('A','B'),unit='mg')
    check=build_check(sheet,selection(unit='g' if damage=='unit' else 'mg'))
    issue=next(i for i in check['issues'] if i['code']==code)
    assert issue['severity']=='blocking' and issue['allowed_resolutions']==[]
    assert len(issue['coordinates'])<=5 and issue['message']
    with pytest.raises(StorageError): validate_resolutions(check,{})


def test_iqr_candidates_are_retained_and_small_samples_require_partial_metrics():
    from app.domain.analysis_plan.checks import build_check,validate_resolutions
    check=build_check(sample(values=('1','1','1','1','100'),groups=('A',)*5),selection())
    issue=next(i for i in check['issues'] if i['code']=='outlier')
    assert issue['coordinates']==['D9'] and issue['allowed_resolutions']==['retain']
    one=build_check(sample(values=('1',),groups=('A',)),selection())
    assert next(i for i in one['issues'] if i['code']=='small_sample')['allowed_resolutions']==['accept_partial_metrics']
    assert next(i for i in one['issues'] if i['field']=='D' and i['code']=='unit_unconfirmed')['allowed_resolutions']==['unknown']
    validate_resolutions(one,{i['id']:i['allowed_resolutions'][0] for i in one['issues']})


def test_label_is_a_declaration_and_unknown_is_not_silently_converted():
    from app.domain.analysis_plan.checks import build_check
    check=build_check(sample(),selection(unit='mg'))
    field=check['selected_fields'][0]
    assert field['prepared_unit']['status']=='unconfirmed' and field['declared_unit']=={'status':'label','value':'mg'}
    assert next(i for i in check['issues'] if i['field']=='D' and i['code']=='unit_unconfirmed')['allowed_resolutions']==['declare_label']
    assert any('不转换' in s for s in check['limitations'])


def test_group_limit_mixed_groups_invalid_fields_and_no_issue_approval():
    from app.domain.analysis_plan.checks import build_check,validate_resolutions
    check=build_check(sample(values=('1',)*21,groups=tuple(str(i) for i in range(21))),selection())
    assert any(i['code']=='too_many_groups' and i['severity']=='blocking' for i in check['issues'])
    sheet=sample(unit='mg');sheet.cells[0].kind='boolean';sheet.cells[0].value=True
    assert any(i['code']=='group_type' for i in build_check(sheet,selection(unit='mg'))['issues'])
    invalid=selection();invalid.numeric_column='Z'
    assert any(i['code']=='invalid_column' for i in build_check(sample(),invalid)['issues'])
    clean=build_check(sample(values=('1','2'),groups=('A','A'),unit='mg'),selection(group_column=None,unit='mg'))
    assert clean['issues']==[]
    validate_resolutions(clean,{})


@pytest.mark.parametrize('with_missing',[False,True])
def test_missing_issue_counts_missing_rows_not_invalid_types(with_missing):
    from app.domain.analysis_plan.checks import build_check
    sheet=sample(values=('1','2',None if with_missing else '3'),groups=('A',)*3)
    sheet.cells[1].kind='text'
    check=build_check(sheet,selection())
    issues=[i for i in check['issues'] if i['code']=='selected_missing']
    assert check['selection_check']['excluded_count']==1+int(with_missing)
    assert len(issues)==int(with_missing)
    if with_missing:
        assert issues[0]['count']==1 and issues[0]['coordinates']==['D7']


def test_group_limit_reports_exact_complete_case_groups():
    from app.domain.analysis_plan.checks import build_check
    sheet=sample(values=('1',)*30+(None,),groups=tuple(str(i) for i in range(31)))
    check=build_check(sheet,selection())
    assert next(i for i in check['issues'] if i['code']=='too_many_groups')['count']==30
