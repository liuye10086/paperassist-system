import pytest
from app.domain.bio_insights.task_contracts import INSIGHT_TASKS


@pytest.fixture(autouse=True)
def postgres_schema():yield None


@pytest.mark.parametrize('kind',INSIGHT_TASKS)
def test_each_new_task_has_independent_storage_scope_and_public_identity(kind):
    from app.domain.storage_governance.bio_manifest import _scope
    from app.domain.tasks.contracts import TaskView
    assert _scope({'task_type':kind})==kind
    # Type-level acceptance is independent of a worker or installed science.
    assert kind in str(TaskView.model_fields['task_type'].annotation)


def test_frozen_input_version_reaches_task_workspace_contract():
    from app.domain.tasks.waits import input_version
    from app.domain.bioinformatics.contracts import digest
    snapshot=dict(schema_version=1,kind='bio_comparison',workflow_version='bio_comparison_v1',project_id='p',
        plan_version_id='v',run_id='r',source_digest='a'*64,output_language='zh-CN',real_model_calls=False,real_network_calls=False)
    task=dict(task_type='bio_comparison',workflow_version='bio_comparison_v1',project_id='p',input_snapshot=snapshot,input_digest=digest(snapshot))
    assert input_version(task)['kind']=='bio_comparison'


def test_results_use_the_same_stable_identity_as_publication():
    from app.domain.bio_insights.execution import result_identifier
    from app.adapters.bio_insights_store import identity
    assert result_identifier({'project_id':'p','task_type':'bio_comparison','input_snapshot':{'run_id':'r'}})==identity('p','result','r')
    assert result_identifier({'project_id':'p','task_type':'bio_resource_import','input_snapshot':{'resource_version_id':'v'}})=='v'
