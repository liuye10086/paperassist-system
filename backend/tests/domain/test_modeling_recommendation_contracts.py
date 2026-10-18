"""Approved new recommendations suggest roles, never research declarations."""
import pytest
from app.domain.analysis_recommendation.contracts import parse_request, validate_draft, request_version


def request():
    return dict(schema_version=3,dataset_id='prepared',sheet_name='Sheet1',candidate_columns=['A','B','C','D'],
                output_language='en',research_summary='An approved metadata summary.')


def draft(method='ols'):
    roles={key:None for key in ('numeric_column','group_column','pair_id_column','before_column','after_column',
        'outcome_column','score_column','id_column','time_column','status_column')}
    roles['covariate_columns']=[]
    if method in ('ols','logistic'):
        roles.update(outcome_column='A',covariate_columns=['B','C']);columns=['A','B','C'];mode='regression'
    elif method=='roc_auc':roles.update(outcome_column='A',score_column='B');columns=['A','B'];mode='roc'
    else:roles.update(id_column='A',time_column='B',status_column='C');columns=['A','B','C'];mode='survival'
    return dict(schema_version=3,method=method,mode=mode,columns=columns,roles=roles,output_language='en',
                rationale=['Research question determines the method.'],assumptions=['Confirm the declared roles and assumptions.'],missing_information=[])


@pytest.mark.parametrize('method',['ols','logistic','roc_auc','kaplan_meier'])
def test_v3_approved_role_drafts_have_separate_declaration_boundary(method):
    raw=request()
    assert parse_request(raw).model_dump()['schema_version']==3
    assert request_version(raw)=='analysis_recommendation_v3'
    assert validate_draft(draft(method),raw)==draft(method)


@pytest.mark.parametrize('change',['extra_role','outside_candidate','unapproved_method','encoding','empty_assumption'])
def test_v3_rejects_crossed_roles_or_unapproved_decisions(change):
    value=draft()
    if change=='extra_role':value['roles']['score_column']='D'
    elif change=='outside_candidate':value['roles']['covariate_columns']=['E'];value['columns']=['A','E']
    elif change=='unapproved_method':value['method']='cox'
    elif change=='encoding':value['roles']['positive']={'kind':'number','value':'1'}
    else:value['assumptions']=[]
    with pytest.raises(ValueError):validate_draft(value,request())


@pytest.mark.parametrize('version',[True,3.0,5])
def test_recommendation_rejects_unknown_or_noninteger_version(version):
    with pytest.raises(ValueError):parse_request({**request(),'schema_version':version})
