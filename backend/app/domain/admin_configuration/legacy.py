"""Installed field-level compatibility classifiers; no research content in errors."""
from app.core.exceptions import StorageError

def changed_paths(before,after,prefix=''):
    paths=[]
    if isinstance(before,dict) and isinstance(after,dict):
        for key in sorted(set(before)|set(after)):
            paths.extend(changed_paths(before.get(key),after.get(key),prefix+'.'+key if prefix else key))
    elif before!=after:paths.append(prefix)
    return paths


def _affected(task,paths):
    name=task['task_type'];snap=task['input_snapshot'] or {}
    domains={
        'parse_file':('basic.',), 'extract_dataset':('basic.',), 'school_template_parse':('schools.',),
        'journal_recommendation':('journals.',),'journal_format_check':('journals.',),
        'journal_adaptation':('journals.',),'review_round_plan':('review.',),
        'review_revision':('review.',),'review_document_export':('review.',),
        'literature_search':('ncbi.',),
        'manuscript_writing':('models.writing.','models.batch_','models.max_corrections','prompts.writing_'),
        'explanation':('models.explanation.','prompts.explanation_'),
        'figure_explanation':('models.explanation.','prompts.explanation_'),
        'boxplot':('models.plot.','prompts.plot_'),
        'figure_workbench':('models.plot.','prompts.plot_'),
        'analysis_recommendation':('models.recommendation.','prompts.recommendation_'),
        'literature_assistance':('models.literature.','prompts.literature_')}
    affected=[p for p in paths if any(p.startswith(prefix) or p==prefix.rstrip('.') for prefix in domains.get(name,()))]
    if not affected:return False
    from .rule_legacy import TASKS,affected as rule_affected
    if name in TASKS:return rule_affected(task,affected)
    if name in ('parse_file','extract_dataset'):
        # Installed lazy dispatch is present in every activation process. A complete
        # old ParseSettings remains executable without consulting the new current.
        try:
            if name == 'parse_file':
                from app.domain.file_parsing import validate_snapshot
            else:
                from app.domain.datasets.snapshots import validate_snapshot
            validate_snapshot(task)
            return False
        except (ValueError,TypeError,KeyError,StorageError):
            return True
    if name == 'literature_search':
        # Legacy interval/cache/timeout have definite installed defaults. Identity
        # did not have a historical revision, so an identity change needs handling.
        return any(p == 'ncbi.identity' or p.startswith('ncbi.identity.') for p in affected)
    # Unbound tasks retain installed instructions, never current finite preferences.
    if name=='manuscript_writing':
        return False  # v1 stays offline; v2 validates its original frozen bundle.
    if name=='literature_assistance':
        # Unbound execution retains the installed/injected provider.policy,
        # installed allowance and original task budget; it never reads current.
        # Even disabling the future entry cannot change this legacy fallback.
        # Fixed Batch06 policy constraints are independently enforced by validation.
        return False
    if all(p.startswith(('models.','prompts.')) for p in affected):
        try:
            if name=='explanation':
                from app.domain.explanation_policy import validate_execution_policy
                validate_execution_policy(snap.get('explanation_policy'))
            elif name=='boxplot':
                from app.domain.plot_policy import validate_execution_policy
                validate_execution_policy(snap.get('boxplot_policy'))
            elif name=='analysis_recommendation':
                from app.domain.analysis_recommendation.policy import validate_execution_policy
                validate_execution_policy(snap.get('recommendation_policy'))
            elif name in ('figure_workbench','figure_explanation'):
                from app.domain.admin_configuration.contracts import Execution,PlotExecution
                from app.domain.model_usage.contracts import ModelPolicy
                explanation=name=='figure_explanation'
                frozen=(Execution if explanation else PlotExecution).model_validate(snap.get('explanation_policy' if explanation else 'boxplot_policy'))
                policy=ModelPolicy.model_validate(frozen.policy.model_dump())
                versions=tuple('figure_explanation_v'+str(n) for n in (1,2,3,4)) if explanation else tuple('openai_figure_workbench_v'+str(n) for n in (1,2,3))
                if policy.prompt_version not in versions or policy.tools!=([] if explanation else ['code_interpreter']):return True
            else:return True
        except (ValueError,TypeError,KeyError,StorageError):return True
        return False
    return True


def check(db,paths):
    # Process pool size never changes a task's frozen parse/model contract.
    paths=[path for path in paths if path!='basic.worker_concurrency']
    if not paths:return
    rows=db.execute('''SELECT t.id,t.task_type,t.input_snapshot,t.input_digest,t.workflow_version,t.project_id FROM tasks t
        LEFT JOIN admin_configuration_bindings b ON b.kind='task' AND b.object_id=t.id
        WHERE b.version_id IS NULL AND t.status IN ('queued','running','waiting_input','waiting_confirmation')''').fetchall()
    for task in rows:
        if _affected(dict(task),paths):
            raise StorageError('configuration_legacy_inflight','存在受本次字段变更影响且缺少冻结依据的旧任务，请先处理该任务。',409,
                params={'task_id':task['id'],'task_type':task['task_type']})
