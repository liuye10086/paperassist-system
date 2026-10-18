"""Pure boundary tests; no database, process or provider is needed."""
from types import SimpleNamespace
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_projection_calculation_routes_through_fixed_linux_contract(monkeypatch):
    from app.domain.figure_workbench import sources
    rows=[{'row':1,'x':1.,'y':2.},{'row':2,'x':2.,'y':3.}]
    calls=[]
    def fixed(kind,values,rules):
        calls.append((kind,values,rules));return {'schema_version':1,'tool_version':'figure_projection_v1','method':{},'audit':{'population_n':2,'valid_n':2,'excluded_n':0,'missing_y_n':0,'excluded':[]},'series':[]}
    def forbidden(*args,**kwargs):raise AssertionError('Projection kernel executed in HTTP/parent process')
    monkeypatch.setattr(sources,'compute_bounded',fixed,raising=False)
    monkeypatch.setattr(sources,'compute_projection',forbidden)
    monkeypatch.setattr(sources,'projection_rows',lambda *a,**k:rows)
    monkeypatch.setattr(sources,'population_rows',lambda *a:({1,2},[]))
    monkeypatch.setattr(sources,'fields_for',lambda *a:[])
    result={'analysis_context':{'plan':{'research_request':{'output_language':'en'}}}}
    config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'B'}}
    computed,_,_=sources.calculate(None,'p','f',result,SimpleNamespace(row_count=2),config)
    assert calls[0][0]=='figure_projection' and calls[0][1]==rows
    assert calls[0][2]['figure_kind']=='line' and calls[0][2]['projection']['x_column']=='A'
    assert computed['audit']['valid_n']==2
