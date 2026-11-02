"""Frozen-result projection only: never recompute seven old statistical methods."""
from copy import deepcopy
import csv, io
import pytest
from app.domain.research_results.contracts import FrozenResearchSource

@pytest.fixture(autouse=True)
def postgres_schema(): yield None

def frozen(method='welch_t', verified=False):
    result=dict(id='run',file_id='file',source_sha256='a'*64,setup_revision=2,completed_at='2026-11-01',
        selection=dict(task_type='group_comparison',method=method,unit='kg'),
        check=dict(row_count=8,valid_count=6,excluded_count=2),
        statistics=dict(method=method,n=6,p_value=dict(value=0.0),confidence_interval=dict(low=None,high=None,reason='not_implemented')),
        row_audit=dict(included_rows=list(range(2,8)),excluded_rows=[dict(row=8,reason='selected_missing')]),engine=dict(id='fixed'))
    return FrozenResearchSource(source_kind='analysis_run',source_id='run',project_id='project',sha256='b'*64,provenance='system_computed',
        content=dict(result=result,execution_verification='verified' if verified else 'legacy_unverified',output_language='zh-CN'))

@pytest.mark.parametrize('method', ['descriptive','pearson','welch_t','ols','logistic','roc_auc','kaplan_meier'])
def test_seven_methods_preserve_exact_leaves_n_missing_and_method_identity(method):
    from app.domain.research_results.statistics_projection import project_statistics_facts,statistics_tables
    source=frozen(method); before=deepcopy(source.model_dump())
    catalog=project_statistics_facts(source)
    facts={f.locator.field_path:f for f in catalog.facts}
    assert facts['statistics.n'].raw_value==6
    assert facts['statistics.p_value.value'].raw_value==0.0
    assert facts['statistics.p_value.value'].verification_status=='unverified'
    assert facts['statistics.confidence_interval.low'].verification_status=='missing'
    assert catalog.methods[0].parameters['selection']['method']==method
    assert '重新计算' in catalog.methods[0].description
    assert '多重比较' in ' '.join(catalog.limitations)
    tables,raws=statistics_tables(source)
    assert any(t['key'].endswith('row_audit') for t in tables)
    assert b'selected_missing' in b''.join(raws)
    assert source.model_dump()==before

def test_receipt_status_is_preserved_and_units_only_on_outcome_metrics():
    from app.domain.research_results.statistics_projection import project_statistics_facts
    source=frozen(verified=True);source.content['result']['statistics']['estimate']={'value':2.0,'unit':'outcome'}
    facts={f.locator.field_path:f for f in project_statistics_facts(source).facts}
    assert facts['statistics.p_value.value'].unit==''
    assert facts['statistics.estimate.value'].unit=='kg'
    assert facts['statistics.n'].verification_status=='verified'

def test_complete_export_does_not_use_catalog_fact_limit_or_preview_rows():
    from app.domain.research_results.statistics_projection import statistics_tables
    source=frozen(); source.content['result']['statistics']['points']=[{'threshold':i,'tpr':i/1100} for i in range(1101)]
    tables,raws=statistics_tables(source)
    table,raw=next((t,r) for t,r in zip(tables,raws) if t['key'].endswith('statistics'))
    rows=list(csv.DictReader(io.StringIO(raw.decode()),delimiter='\t'))
    assert any(r['field_path']=='points[1100].threshold' and r['raw_value']=='1100' for r in rows)

def test_exact_field_selection_does_not_silently_return_other_facts():
    from app.domain.research_results.statistics_projection import project_statistics_facts
    source=frozen(); source.locator.kind='field';source.locator.field_path='statistics.n'
    assert [f.raw_value for f in project_statistics_facts(source).facts]==[6]
    source.locator.field_path='statistics.missing'
    with pytest.raises(ValueError): project_statistics_facts(source)


def test_existing_saved_six_method_bundles_project_every_selected_numeric_value_without_refitting(monkeypatch):
    from pathlib import Path
    import json
    from app.domain.research_results.statistics_projection import project_statistics_facts,leaves
    from app.domain.bioinformatics.contracts import digest
    def forbidden(*args,**kwargs):raise AssertionError('Projection must not recompute')
    monkeypatch.setattr('app.domain.fixed_statistics.summarize_bounded',forbidden)
    methods=set()
    for path in (Path(__file__).parents[1]/'fixtures/figure_b07/source-bundles').glob('*.json'):
        result=json.loads(path.read_text(encoding='utf8'))['bundle']['result']
        source=FrozenResearchSource(source_kind='analysis_run',source_id=result['id'],project_id='project',sha256=digest(result),
            provenance='system_computed',content=dict(result=result,execution_verification='legacy_unverified'))
        facts=project_statistics_facts(source).facts
        expected={p:v for top in ('check','overall','groups','statistics') for p,v in leaves(result.get(top,{}),top)}
        for fact in facts:
            assert fact.raw_value==expected[fact.locator.field_path]
            assert fact.source_sha256==digest(result)
        methods.add(result['selection'].get('method','descriptive'))
    assert {'descriptive','pearson','ols','logistic','roc_auc','kaplan_meier'}<=methods

def test_real_curve_and_effect_projection_figures_render_frozen_values():
    from pathlib import Path
    import json
    from app.domain.research_results.statistics_figures import render_statistics_figure
    from app.domain.bioinformatics.contracts import digest
    for name in ('7991caf8-33de-4e90-a9da-0ace3df6f2a7','a07372c8-318d-4fe2-8c8d-ce7db6b53189','010cd2e0-ef35-407c-a1aa-ed21d3902591'):
        result=json.loads((Path(__file__).parents[1]/'fixtures/figure_b07/source-bundles'/f'{name}.json').read_text(encoding='utf8'))['bundle']['result']
        source=FrozenResearchSource(source_kind='analysis_run',source_id=result['id'],project_id='project',sha256=digest(result),provenance='system_computed',content=dict(result=result))
        raw=render_statistics_figure(source)
        assert raw.startswith(b'\x89PNG') and len(raw)>5000


@pytest.mark.parametrize('column,unit',[('relative_quantity','fold'),('delta_cq','Cq'),('ci_log2_low','log2'),('original_value','fold')])
def test_qpcr_bridge_preserves_declared_scientific_units(column,unit):
    from app.domain.research_results.insight_projection import project_insight_facts
    source=FrozenResearchSource(source_kind='bio_insight_result_member',source_id='member',project_id='project',sha256='a'*64,provenance='system_computed',
        locator=dict(kind='row',row_key={'row_key':'r'},column=column),content=dict(result_version_id='result',inference_scope='sample_exploratory',provenance='system_computed',
        config={'kind':'comparison','schema_version':3,'mode':'qpcr'},table_key='results',rows=[{'row_key':'r',column:1.5,'unit':'fold'}]))
    assert project_insight_facts(source).facts[0].unit==unit


def test_statistics_reproduction_materials_rebuild_every_complete_table(tmp_path):
    import subprocess,sys,json
    from app.domain.research_results.statistics_package import statistics_reproduction_files
    from app.domain.research_results.statistics_projection import statistics_tables
    source=frozen();source.sha256=__import__('app.domain.bioinformatics.contracts',fromlist=['digest']).digest(source.content['result']);files=statistics_reproduction_files([source.model_dump(mode='json')])
    for item in files:
        path=tmp_path/item['name'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(item['raw'])
    folder=next(tmp_path.glob('statistics/*'))
    proc=subprocess.run([sys.executable,str(folder/'rebuild_projection.py')],cwd=folder,capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    tables,raws=statistics_tables(source)
    for table,raw in zip(tables,raws):assert (folder/'rebuilt'/f"{table['key']}.tsv").read_bytes()==raw
