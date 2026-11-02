"""Regression checks for the final B05 review; no database or scientific rerun."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import importlib
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_analysis_run_newer_version_sql_compiles_imports_and_preserves_sql_quoting(monkeypatch):
    path=Path(__file__).parents[2]/'app/domain/research_results/source_changes.py'
    compile(path.read_text(encoding='utf-8-sig'),str(path),'exec')
    module=importlib.import_module('app.domain.research_results.source_changes')
    statements=[]
    class Result:
        def fetchone(self):return None
        def fetchall(self):return []
    class DB:
        def execute(self,sql,params=()):statements.append(sql);return Result()
    db=DB()
    class Reader:
        def __init__(self,assets):self.store=SimpleNamespace(connection=lambda:nullcontext(db),require_project=lambda *args:None,user_id='owner')
        def read_source(self,*args,**kwargs):return SimpleNamespace(source_kind='analysis_run',source_id='run',sha256='a'*64)
    monkeypatch.setattr(module,'ResearchSourceReader',Reader)
    result=module.check_changes(None,'project',[dict(source_kind='analysis_run',source_id='run')])
    query=next(q for q in statements if 'FROM analysis_runs old' in q)
    assert "nullif(n.completed_at,'') IS NOT NULL" in query
    assert "n.result_json::jsonb->>'completed_at'=n.completed_at" in query
    assert result['items'][0]['newer_version_id'] is None

@pytest.mark.parametrize('time_role',[None,'B'])
def test_optional_dictionary_or_endpoint_without_individual_id_does_not_imply_repeated_people(time_role):
    from app.domain.statistics_roles import StatisticsDataRoles,validate_role_records
    roles=StatisticsDataRoles(endpoint='C',time=time_role,dictionary=[dict(column='C',name='BMI')],structure='independent')
    rows=[dict(row=2,B='baseline',C=20),dict(row=3,B='baseline',C=25)]
    result=validate_role_records(rows,roles,inference=True)
    assert result==dict(individual_n=None,row_n=2,repeated=False)

def test_research_figure_task_audit_does_not_enter_statistics_source_branch(monkeypatch):
    from app.maintenance import research_results_audit as audit
    from app.domain.bioinformatics.contracts import digest
    expected=dict(id='figure',task_id='task',config_json={},config_sha256=digest({}))
    token=dict(kind='research_figure')
    class Result:
        def __init__(self,value):self.value=value
        def fetchone(self):return self.value
        def __iter__(self):return iter(())
    class DB:
        def execute(self,sql,params=()):
            if 'SELECT owner_id' in sql:return Result(dict(owner_id='owner'))
            if 'task_checkpoints' in sql:return Result(dict(state_json={'input_version':token},next_node='check'))
            if 'research_figure_versions' in sql:return Result(expected)
            if 'research_source_bindings' in sql:return Result(None)
            raise AssertionError(sql)
    monkeypatch.setattr(audit,'input_version',lambda task:token)
    task=dict(id='task',project_id='project',user_id='owner',task_type='research_figure',status='queued',input_snapshot={'figure_version_id':'figure','config':{}})
    assert audit.validate_research_task_source(DB(),task)==expected

def test_comparison_interval_metadata_does_not_inherit_outcome_units():
    from app.domain.research_results.statistics_projection import metric_unit
    from tests.domain.test_statistics_projection import frozen
    result=frozen().content['result'];result['statistics']['estimate']={'value':1.0,'unit':'outcome'}
    for column in ('low','high'):assert metric_unit(result,'statistics.confidence_interval.'+column)=='kg'
    for column in ('level','simultaneous'):assert metric_unit(result,'statistics.confidence_interval.'+column)==''

def test_paired_figure_title_reports_biological_pair_n_separately_from_source_rows(monkeypatch):
    from matplotlib.figure import Figure
    from app.domain.research_results.statistics_figures import render_statistics_figure
    from tests.domain.test_statistics_projection import frozen
    source=frozen('paired_t');source.content['output_language']='en'
    result=source.content['result'];result['selection']['design']='paired';result['statistics']={'sample_sizes':[3,3]};result['groups']=[{'label':'t0'},{'label':'t1'}]
    source.content['frozen_plot']={'groups':[[1,2,3],[4,5,7]]}
    captured=[]
    def save(figure,*args,**kwargs):captured.append(figure.axes[0].get_title())
    monkeypatch.setattr(Figure,'savefig',save)
    render_statistics_figure(source)
    assert 'complete pairs n=3' in captured[0] and 'included source rows=6' in captured[0]

def test_requested_statistics_figure_language_reaches_renderer(monkeypatch):
    from io import BytesIO
    from PIL import Image
    from app.domain.research_results.figure_members import read_figure_panel
    from app.domain.research_results.contracts import ResearchFigurePanel
    from tests.domain.test_statistics_projection import frozen
    source=frozen();captured=[]
    def render(value,*,language=None):
        captured.append(language);out=BytesIO();Image.new('RGB',(10,10)).save(out,format='PNG');return out.getvalue()
    monkeypatch.setattr('app.domain.research_results.statistics_figures.render_statistics_figure',render)
    reader=SimpleNamespace(_read_source_in_phase=lambda *args,**kwargs:source)
    panel=ResearchFigurePanel(source={'source_kind':'analysis_run','source_id':'run'})
    read_figure_panel(reader,None,'project',panel,phase=None,figure_language='en')
    assert captured==['en']

@pytest.mark.parametrize('column,row,expected',[
    ('effect_value',{'effect_unit':'log2 relative expression'},'log2 relative expression'),
    ('statistical_effect_value',{'statistical_scale':'delta_cq'},'Cq'),
    ('statistical_effect_value',{'statistical_scale':'log2_signal'},'log2'),
])
def test_qpcr_effect_units_survive_specific_projection_branch(column,row,expected):
    from app.domain.research_results.contracts import FrozenResearchSource
    from app.domain.research_results.insight_projection import project_insight_facts
    source=FrozenResearchSource(source_kind='bio_insight_result_member',source_id='member',project_id='project',sha256='a'*64,provenance='system_computed',
        locator=dict(kind='row',row_key={'row_key':'r'},column=column),content=dict(result_version_id='result',inference_scope='sample_exploratory',provenance='system_computed',
        config={'kind':'comparison','schema_version':3,'mode':'qpcr'},table_key='results',rows=[{'row_key':'r',column:1.5,**row}]))
    assert project_insight_facts(source).facts[0].unit==expected

@pytest.mark.parametrize('requested,expected',[('en','complete pairs n=3'),('original','完整对 n=3'),('unknown','完整对 n=3')])
def test_statistics_renderer_explicit_language_precedes_run_and_other_values_fallback(monkeypatch,requested,expected):
    from matplotlib.figure import Figure
    from app.domain.research_results.statistics_figures import render_statistics_figure
    from tests.domain.test_statistics_projection import frozen
    source=frozen('paired_t');source.content['output_language']='zh-CN'
    result=source.content['result'];result['selection']['design']='paired';result['statistics']={'sample_sizes':[3,3]};result['groups']=[{'label':'t0'},{'label':'t1'}]
    source.content['frozen_plot']={'groups':[[1,2,3],[4,5,7]]}
    captured=[];monkeypatch.setattr(Figure,'savefig',lambda figure,*args,**kwargs:captured.append(figure.axes[0].get_title()))
    render_statistics_figure(source,language=requested)
    assert expected in captured[0]

def test_estimate_only_numeric_value_inherits_outcome_unit():
    from app.domain.research_results.statistics_projection import metric_unit
    from tests.domain.test_statistics_projection import frozen
    result=frozen().content['result'];result['statistics']['estimate']={'value':None,'unit':'outcome','name':'mean_difference','reason':None}
    assert metric_unit(result,'statistics.estimate.value')=='kg'
    for column in ('name','reason','unit'):assert metric_unit(result,'statistics.estimate.'+column)==''
