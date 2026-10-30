"""Real dispatch/adapter contracts for the new explicitly versioned material."""
from types import SimpleNamespace
import pytest
from app.core.exceptions import StorageError
from app.domain.figure_workbench.tasks import prompt_version
from app.adapters.models.openai_plot import _policy
from app.adapters.models.openai_responses import ModelProviderError
from app.domain.model_usage.contracts import CallRequest
from app.domain.model_usage.gateway import ModelGateway,input_digest
from app.domain.admin_configuration.legacy import _affected


@pytest.mark.parametrize('contract,expected',[
    (1,'figure_explanation_v1'),(2,'figure_explanation_v2'),
    (3,'figure_explanation_v3'),(4,'figure_explanation_v4'),
    (5,'figure_explanation_v5'),
])
def test_each_frozen_explanation_contract_has_its_own_prompt(contract,expected):
    assert prompt_version({'figure_explanation_contract':contract},explanation=True)==expected


@pytest.mark.parametrize('schema,expected',[
    (1,'openai_figure_workbench_v2'),(2,'openai_figure_workbench_v3'),
    (3,'openai_figure_workbench_v4'),
])
def test_presentation_schema_never_follows_a_new_latest_alias(schema,expected):
    assert prompt_version({'presentation':{'schema_version':schema}})==expected


@pytest.mark.parametrize('contract',[0,6,True,'5',None])
def test_unknown_explanation_contract_is_rejected(contract):
    with pytest.raises(StorageError):
        prompt_version({'figure_explanation_contract':contract},explanation=True)


@pytest.mark.parametrize('schema',[0,4,True,'3',None])
def test_unknown_presentation_schema_is_rejected(schema):
    with pytest.raises(StorageError):
        prompt_version({'presentation':{'schema_version':schema}})


@pytest.mark.parametrize('version',[1,2,3,4])
def test_plot_adapter_accepts_each_installed_version(version):
    _policy(SimpleNamespace(tools=['code_interpreter'],output_format='text',
                            prompt_version='openai_figure_workbench_v'+str(version)))


@pytest.mark.parametrize('change',[
    {'tools':[]},{'output_format':'analysis_explanation_v2'},
    {'prompt_version':'openai_figure_workbench_v5'},
])
def test_new_plot_policy_does_not_relax_tools_format_or_unknown_versions(change):
    value={'tools':['code_interpreter'],'output_format':'text','prompt_version':'openai_figure_workbench_v4'}
    with pytest.raises(ModelProviderError):_policy(SimpleNamespace(**(value|change)))


def synthetic_execution(version,explanation=False):
    value={'policy':{'model':'synthetic-model','prompt_version':version,'max_output_tokens':10,
        'timeout_seconds':45,'tools':[] if explanation else ['code_interpreter'],
        'output_format':'analysis_explanation_v2' if explanation else 'text',
        'price':{'version':'synthetic-v1','currency':'USD','model':'synthetic-model',
                 'input_micro_usd_per_million':1,'cached_input_micro_usd_per_million':0,
                 'output_micro_usd_per_million':2}},
        'input_token_allowance':100,'task_limit_micro_usd':100}
    if not explanation:value.update(tool_reserve_micro_usd=1,tool_reserve_version='synthetic-v1')
    return value


@pytest.mark.parametrize('version',[1,2,3,4])
def test_gateway_reaches_local_reservation_for_each_supported_plot_version(version):
    class ReservedLocally(Exception):pass
    class Service:
        def reserve_call(self,request,**kwargs):raise ReservedLocally()
    instructions='Synthetic local contract';payload={'synthetic':True}
    policy=synthetic_execution('openai_figure_workbench_v'+str(version))
    policy.pop('task_limit_micro_usd')
    request=CallRequest(task_id='synthetic-task',expected_task_revision=2,call_key='synthetic-plot',
        input_digest=input_digest(instructions=instructions,payload=payload),**policy)
    with pytest.raises(ReservedLocally):
        ModelGateway(Service(),object()).submit_plot(request,instructions=instructions,payload=payload,execution_lease=object())


@pytest.mark.parametrize('explanation,version',[(False,n) for n in (1,2,3,4)]+[(True,n) for n in (1,2,3,4,5)])
def test_frozen_installed_versions_remain_compatible_with_future_preferences(explanation,version):
    prompt=('figure_explanation_v' if explanation else 'openai_figure_workbench_v')+str(version)
    task={'task_type':'figure_explanation' if explanation else 'figure_workbench',
          'input_snapshot':{('explanation_policy' if explanation else 'boxplot_policy'):synthetic_execution(prompt,explanation)}}
    assert _affected(task,['prompts.explanation_instruction' if explanation else 'prompts.plot_instruction']) is False


@pytest.mark.parametrize('explanation,version',[(False,5),(True,6)])
def test_uninstalled_frozen_versions_require_handling(explanation,version):
    prompt=('figure_explanation_v' if explanation else 'openai_figure_workbench_v')+str(version)
    task={'task_type':'figure_explanation' if explanation else 'figure_workbench',
          'input_snapshot':{('explanation_policy' if explanation else 'boxplot_policy'):synthetic_execution(prompt,explanation)}}
    assert _affected(task,['prompts.explanation_instruction' if explanation else 'prompts.plot_instruction']) is True
