"""Backend-owned submission origin. Historical observations never gain evidence."""
from dataclasses import dataclass, field

from app.core.exceptions import StorageError

_SEAL = object()
_FIELDS = {'version','kind','adapter','transport','task_id','input_digest','operation'}
_TEXT_FLOWS = {
    'school_rule_suggestion': {'school_rule_suggestion_v1'},
    'explanation': {'explanation_v1','explanation_v2'},
    'figure_explanation': {'figure_explanation_v1'},
    'analysis_recommendation': {'analysis_recommendation_v'+str(i) for i in range(1,6)},
}
_PLOT_FLOWS = {'boxplot': {'boxplot_v1','boxplot_v2'}, 'figure_workbench': {'figure_workbench_v1'}}


@dataclass(frozen=True)
class _AdmissionContext:
    task_id: str
    input_digest: str
    operation: str
    kind: str
    adapter: str
    transport: str
    seal: object = field(repr=False,compare=False)


def admission_context(provider, *, request, operation):
    """Classify constructors and approved Batch06 bindings, never arbitrary real flags."""
    from app.adapters.models.openai_responses import OpenAIResponsesProvider,provider_transport_origin
    from app.adapters.models.openai_plot import OpenAIPlotProvider
    from app.domain.literature_live.batch06 import Batch06ModelProvider
    kind,adapter,transport='unknown','unknown','unverified_injected'
    exact=type(provider)
    if exact in (OpenAIResponsesProvider,OpenAIPlotProvider,Batch06ModelProvider):
        transport=provider_transport_origin(provider)
        adapter={OpenAIResponsesProvider:'openai_responses',OpenAIPlotProvider:'openai_plot',Batch06ModelProvider:'batch06_responses'}[exact]
        if exact is Batch06ModelProvider:
            from app.domain.literature_live.policy import LivePolicyError
            provider._check(request.policy)
            if (provider.task_id!=request.task_id or provider._authorization['payload_digest']!=request.input_digest):
                raise LivePolicyError('batch06_input_mismatch')
        expected_operation='plot' if exact is OpenAIPlotProvider else ('text','frozen_writing') if exact is OpenAIResponsesProvider else 'text'
        matches=operation in expected_operation if isinstance(expected_operation,tuple) else operation==expected_operation
        if transport=='official_default' and matches:kind='openai_live'
    elif getattr(provider,'source_kind',None)=='synthetic_fixture':
        kind,adapter,transport='synthetic_fixture','synthetic_fixture','fixture'
    return _AdmissionContext(request.task_id,request.input_digest,operation,kind,adapter,transport,_SEAL)


def _live_flow(evidence,task):
    operation,adapter=evidence['operation'],evidence['adapter']
    task_type,workflow=task.get('task_type'),task.get('workflow_version')
    if evidence['transport']!='official_default':return False
    if adapter=='batch06_responses':
        return operation=='text' and task_type=='literature_assistance' and workflow=='literature_assistance_v1'
    if adapter=='openai_plot':
        return operation=='plot' and workflow in _PLOT_FLOWS.get(task_type,set())
    if adapter=='openai_responses':
        return (operation=='text' and workflow in _TEXT_FLOWS.get(task_type,set())
            or operation=='frozen_writing' and task_type=='manuscript_writing' and workflow=='manuscript_writing_v2')
    return False


def apply_admission_provenance(call,task,context):
    """Return merged state only after the caller's normal lease and admission checks."""
    if (type(context) is not _AdmissionContext or context.seal is not _SEAL
            or context.task_id!=call['task_id'] or context.task_id!=task['id']
            or context.input_digest!=call['input_digest']):
        raise StorageError('model_usage_input_invalid','模型调用来源与准入不一致。',422)
    state=dict(call.get('provider_state') or {})
    evidence=dict(version=1,kind=context.kind,adapter=context.adapter,transport=context.transport,
                  task_id=context.task_id,input_digest=context.input_digest,operation=context.operation)
    if evidence['kind']=='openai_live' and not _live_flow(evidence,task):evidence['kind']='unknown'
    # No overwrite: retries and later plot slices preserve the original admission.
    if 'submission_provenance' not in state:state['submission_provenance']=evidence
    return state


def _synthetic(call):
    for container in (call.get('input_snapshot'),call.get('provider_state'),call.get('policy_snapshot')):
        if not isinstance(container,dict):continue
        if any(container.get(key) is True for key in ('synthetic_fixture','synthetic','fixture','synthetic_scope')):return True
        if any(container.get(key)=='synthetic_fixture' for key in ('provider_provenance','writing_provider_provenance','source_kind','scope','provenance')):return True
    return False


def public_provider_provenance(call,task=None):
    """One nullable reader; unknown new evidence prevents legacy live fallback."""
    task=task or call
    state=call.get('provider_state') or {}
    if _synthetic(call):return 'synthetic_fixture'
    if 'submission_provenance' in state:
        evidence=state['submission_provenance']
        if (not isinstance(evidence,dict) or set(evidence)!=_FIELDS or type(evidence['version']) is not int
                or evidence['version']!=1 or evidence['task_id']!=call.get('task_id')
                or evidence['input_digest']!=call.get('input_digest')):return None
        if evidence['kind']=='synthetic_fixture' and evidence['adapter']=='synthetic_fixture' and evidence['transport']=='fixture':return 'synthetic_fixture'
        return 'openai_live' if evidence['kind']=='openai_live' and _live_flow(evidence,task) else None
    if (state.get('writing_provider_provenance')=='openai_live'
            and task.get('task_type')=='manuscript_writing' and task.get('workflow_version')=='manuscript_writing_v2'):
        return 'openai_live'
    return None
