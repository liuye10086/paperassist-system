from tests.helpers.projection import check_projection,confirm_projection
from tests.helpers.statistics import statistics_post
import pytest
from tests.api.test_analysis import client
from tests.helpers.tasks import task_owner
from app.adapters.storage import ProjectStore
from app.adapters.figure_workbench_store import FigureWorkbenchStore
from app.core.config import get_data_dir
from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection

@pytest.mark.parametrize('kind',['boxplot','scatter','correlation_heatmap','forest','roc_curve','kaplan_meier','group_boxplot','paired_connected'])
def test_original_methods_reuse_verified_material_without_baked_number(client,kind):
    from tests.integration.test_correlation_plan import prepared_correlations,create_correlation
    from tests.integration.test_comparison_plan import make_plan,approve,selection,independent_rows
    if kind in ('forest','roc_curve','kaplan_meier'):
        from tests.integration.test_modeling_artifact_chain import result_for
        base,_,result=result_for(client,{'forest':'ols','roc_curve':'roc_auc','kaplan_meier':'kaplan_meier'}[kind])
    elif kind=='boxplot':
        from tests.helpers.analysis_plan import confirmed_sample
        base,_,_,_=confirmed_sample(client)
        result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    elif kind in ('group_boxplot','paired_connected'):
        rows=independent_rows() if kind=='group_boxplot' else [['ID','Before','After'],['a',8,2],['b',9,3],['c',7,4],['d',10,6],['e',11,8]]
        base,_,prepared=prepared_correlations(client,rows=rows)
        from tests.domain.test_correlation_plan_contracts import research
        declaration=research()
        if kind=='paired_connected':declaration.update(observation_structure='paired',relationship_description='Same participant before and after')
        task,_=make_plan(client,base,prepared,selection(prepared['source']['sheet_name'],'welch_t' if kind=='group_boxplot' else 'paired_t'),declaration);approve(client,task)
        result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    else:
        base,_,prepared=prepared_correlations(client)
        changes=None
        if kind=='correlation_heatmap':
            from tests.domain.test_correlation_plan_contracts import selection as cs
            chosen=cs();chosen.update(mode='matrix',columns=['A','B','C'],units={'A':'','B':'','C':''});chosen['sheet_name']=prepared['source']['sheet_name'];changes={'selection':chosen}
        task,_=create_correlation(client,base,prepared,changes=changes);approve(client,task)
        result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    from app.domain.artifact_contracts import artifact_language
    store=FigureWorkbenchStore(ProjectStore(get_data_dir(),owner_id=task_owner(client)));args=(base.split('/')[4],result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config={'figure_kind':'boxplot' if kind in ('group_boxplot','paired_connected') else kind,'language':artifact_language(result)}))
    check=check_projection(store,*args,saved['version']['id']);confirm_projection(store,*args,saved['version']['id'],ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
    payload=store.external_preview(*args,saved['version']['id'])['payload']
    assert payload['schema_version']==5
    assert payload['figure_kind']==kind
    assert not payload['labels']['title'].startswith(('Figure 1','图 1'))
    assert payload['plot_config']['numbering_mode']=='external'
