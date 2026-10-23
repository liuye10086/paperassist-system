"""Waiting generations and capability reads; no network or implicit execution."""
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.core.errors import PUBLIC_CODES
from app.domain.tasks.wait_contracts import WaitView


def input_version(task):
    if task['task_type']=='school_template_parse':
        from app.domain.school_templates.service import input_version as school_input_version
        return school_input_version(task)
    if task['task_type']=='manuscript_writing':
        from app.domain.manuscript_writing.service import input_version as writing_input_version
        return writing_input_version(task)
    if task['task_type']=='layout_docx':
        from app.domain.layout_exports.service import input_version as layout_input_version
        return layout_input_version(task)
    if task['task_type']=='pdf_export':
        from app.domain.pdf_exports.service import input_version as pdf_input_version
        return pdf_input_version(task)
    if task['task_type'] in ('manuscript_draft','manuscript_docx'):
        from app.domain.manuscripts.service import input_version as manuscript_input_version
        return manuscript_input_version(task)
    if task['task_type'] == 'literature_assistance':
        from app.domain.literature_assistance.service import input_version as assistance_input_version
        return assistance_input_version(task)
    if task['task_type'] == 'literature_search':
        from app.domain.literature.service import input_version as literature_input_version
        return literature_input_version(task)
    if task['task_type'] == 'statistics_compute':
        from app.domain.statistics_execution.service import input_version as statistics_input_version
        return statistics_input_version(task)
    if 'input_version' in task:
        return task['input_version']
    if task['task_type'] == 'analysis_recommendation':
        from app.domain.analysis_recommendation.service import input_version as recommendation_input_version
        return recommendation_input_version(task)
    if task['task_type'] == 'review_ocr':
        from app.domain.ocr_review.service import review_input_version
        return review_input_version(task)
    if task['task_type'] == 'analysis_plan':
        from app.domain.analysis_plan.service import plan_input_version
        return plan_input_version(task)
    if task['task_type'] == 'prepare_dataset':
        from app.domain.dataset_preparation.service import preparation_input_version
        return preparation_input_version(task)
    if task['task_type'] == 'extract_dataset':
        from app.domain.datasets.snapshots import structure_input_version
        return structure_input_version(task)
    if task['task_type'] == 'parse_file':
        from app.domain.file_parsing import parse_input_version
        return parse_input_version(task)
    snapshot = task['input_snapshot']
    if task['task_type'] == 'collection_word_report':
        from app.domain.report_collections.service import input_version as collection_input_version
        return collection_input_version(task)
    if task['task_type'] in ('figure_projection','figure_workbench','figure_explanation'):
        from app.domain.tasks.contracts import DatasetAnalysisInputVersion
        from app.adapters.task_store import source_conflict
        try:
            if snapshot['source'] != snapshot['result']['source']:
                raise source_conflict()
            return DatasetAnalysisInputVersion(kind='dataset_analysis',
                setup_revision=snapshot['result']['setup_revision'], output_language=snapshot['output_language'],
                source=snapshot['source']).model_dump(mode='json')
        except (TypeError, ValueError, KeyError) as exc:
            raise source_conflict() from exc
    if 'source' in snapshot or 'source' in snapshot['result']:
        if snapshot.get('source') != snapshot['result'].get('source') or snapshot.get('schema_version') != 2:
            from app.adapters.task_store import source_conflict
            raise source_conflict()
    version = {'setup_revision': snapshot['result']['setup_revision'], 'output_language': snapshot['output_language']}
    if 'source' in snapshot:
        version.update(kind='dataset_analysis', source=snapshot['source'])
        from app.domain.tasks.contracts import DatasetAnalysisInputVersion
        try:
            return DatasetAnalysisInputVersion.model_validate(version).model_dump(mode='json')
        except (TypeError, ValueError) as exc:
            from app.adapters.task_store import source_conflict
            raise source_conflict() from exc
    return version


def get_open_wait(db, task):
    row = db.execute("SELECT * FROM task_waits WHERE task_id=%s AND status='open'", (task['id'],)).fetchone()
    if row is None:
        return None
    values = {key: row[key] for key in WaitView.model_fields}
    code = values['error_code']
    values['error_code'] = code if code in PUBLIC_CODES else ('internal_error' if code else None)
    return WaitView(**values).model_dump(mode='json')


def resolve_open_wait(db, task, *, status='resolved'):
    if status not in ('resolved', 'superseded'):
        raise ValueError('Invalid waiting resolution.')
    db.execute('''UPDATE task_waits SET status=%s,resolved_at=%s,resolved_task_revision=%s
        WHERE task_id=%s AND status='open' AND task_revision<%s''',
        (status, task['updated_at'], task['revision'], task['id'], task['revision']))


def persist_wait(db, task):
    if task['status'] not in ('waiting_input', 'waiting_confirmation'):
        raise ValueError('Only waiting tasks have pending requests.')
    existing = get_open_wait(db, task)
    if existing and existing['task_revision'] == task['revision']:
        return
    resolve_open_wait(db, task, status='superseded')
    kind = ('unsupported_input' if task['status'] == 'waiting_input' else
        {'budget_exceeded': 'budget_confirmation', 'submission_unknown': 'submission_unknown', 'observation_expired': 'remote_observation'}.get(
            task['reason_code'], 'unsupported_confirmation'))
    if task['task_type'] == 'literature_assistance' and task['reason_code'] == 'confirmation_required':
        kind = 'literature_model_authorization'
    if task['task_type'] == 'literature_search' and task['reason_code'] == 'confirmation_required':
        kind = 'literature_configuration'
    if task['task_type'] == 'prepare_dataset' and task['reason_code'] == 'confirmation_required':
        kind = 'dataset_preparation_confirmation'
    if task['task_type'] == 'review_ocr' and task['reason_code'] == 'confirmation_required':
        kind = 'ocr_review_confirmation'
    if task['task_type'] == 'figure_projection' and task['reason_code'] == 'confirmation_required':
        kind = 'figure_projection_confirmation'
    if task['task_type'] == 'analysis_plan' and task['reason_code'] == 'confirmation_required':
        kind = 'analysis_plan_confirmation'
    if task['task_type'] == 'analysis_plan' and task['status'] == 'waiting_input' and task['reason_code'] == 'input_required':
        kind = 'analysis_plan_input'
    db.execute('''INSERT INTO task_waits
        (id,task_id,user_id,project_id,kind,status,task_revision,input_version,reason_code,error_code,created_at)
        VALUES (%s,%s,%s,%s,%s,'open',%s,%s,%s,%s,%s)''',
        (str(uuid4()), task['id'], task['user_id'], task['project_id'], kind, task['revision'],
         Jsonb(input_version(task)), task['reason_code'], task.get('error_code'), task['updated_at']))


def allowed_recovery_actions(db, task):
    if task['task_type']=='manuscript_writing' and task.get('reason_code')!='observation_expired':
        from app.domain.manuscript_writing.service import recovery_actions
        return recovery_actions(db,task)
    if task['task_type'] == 'literature_assistance' and task.get('reason_code') != 'observation_expired':
        from app.domain.literature_assistance.service import recovery_actions
        return recovery_actions(db,task)
    if task['task_type'] == 'literature_search':
        from app.domain.literature.service import configuration
        if not configuration()['available']: return []
        if task['status'] == 'waiting_confirmation':
            wait = get_open_wait(db, task)
            return ['resume'] if wait and wait['kind'] == 'literature_configuration' and wait['task_revision'] == task['revision'] else []
        return ['retry'] if task['status'] == 'failed' and task.get('error_code') in ('ncbi_unavailable','storage_unavailable','task_worker_interrupted') else []
    if task.get('reason_code') == 'observation_expired':
        from app.domain.model_usage.observation import resumable_call
        wait = get_open_wait(db, task)
        return ['resume'] if resumable_call(db, task) and wait and wait['kind'] == 'remote_observation' and wait['task_revision'] == task['revision'] else []
    if task['task_type'] == 'statistics_compute':
        return ['retry'] if task['status']=='failed' and task.get('error_code') in ('storage_unavailable','task_worker_interrupted') else []
    if task['task_type'] in ('figure_projection','figure_workbench','figure_explanation'):
        from app.domain.figure_workbench.tasks import allowed_recovery_actions as configured_actions
        return configured_actions(db, task)
    if task['task_type'] in ('prepare_dataset','review_ocr','analysis_plan'):
        if task['task_type']=='analysis_plan' and task['status']=='waiting_input':
            wait=get_open_wait(db,task)
            if wait and wait['kind']=='analysis_plan_input' and wait['task_revision']==task['revision']:
                return ['revise']
        if task['status'] == 'waiting_confirmation':
            wait = get_open_wait(db, task)
            expected_kind = {'review_ocr': 'ocr_review_confirmation', 'prepare_dataset': 'dataset_preparation_confirmation', 'analysis_plan': 'analysis_plan_confirmation'}[task['task_type']]
            if wait and wait['kind'] == expected_kind and wait['task_revision'] == task['revision']:
                return ['approve', 'revise']
        return ['retry'] if task['status'] == 'failed' and task.get('error_code') in ('storage_unavailable','task_worker_interrupted') else []
    if task['status'] not in ('failed', 'waiting_confirmation'):
        return []
    if task['status'] == 'waiting_confirmation':
        wait = get_open_wait(db, task)
        if (task['reason_code'] != 'budget_exceeded' or not wait
                or wait['kind'] != 'budget_confirmation' or wait['task_revision'] != task['revision']):
            return []
    budget_wait = task['status'] == 'waiting_confirmation'
    if task['task_type'] in ('parse_file','extract_dataset'):
        from app.domain.file_parsing import RETRYABLE_CODES
        if task['task_type'] == 'extract_dataset':
            from app.domain.datasets.snapshots import validate_snapshot
            snapshot = validate_snapshot(task)
            if db.execute('''SELECT id FROM file_structure_versions WHERE file_id=%s AND version>
                (SELECT version FROM file_structure_versions WHERE id=%s)''',
                (snapshot['file']['id'],snapshot['structure_id'])).fetchone():
                return []
        if task['task_type'] == 'parse_file':
            from app.domain.file_parsing import validate_snapshot
            snapshot = validate_snapshot(task)
            if db.execute('SELECT id FROM file_parse_results WHERE file_id=%s AND version>%s',
                (snapshot['file']['id'],snapshot.get('parse_version',1))).fetchone():
                return []
        return ['retry'] if not budget_wait and task.get('error_code') in RETRYABLE_CODES else []
    if task['task_type'] in ('word_report','collection_word_report','manuscript_draft','manuscript_docx','school_template_parse'):
        return ['retry'] if not budget_wait else []
    if task['task_type'] == 'boxplot':
        from app.domain.plot_tasks import _can_resume, _last_call, _unknown_submission
    elif task['task_type'] == 'explanation':
        from app.domain.explanation_tasks import _can_resume, _last_call
        def _unknown_submission(call):
            return call and not call.get('provider_response_id') and call['status'] in ('submitting', 'submission_unknown')
    elif task['task_type'] == 'analysis_recommendation':
        from app.domain.analysis_recommendation.service import last_call as _last_call
        def _unknown_submission(call):
            return call and not call.get('provider_response_id') and call['status'] in ('submitting','submission_unknown')
        def _can_resume(task,call):
            return task.get('error_code') in ('model_provider_unavailable','storage_unavailable','task_worker_interrupted') and (not call or bool(call.get('provider_response_id')))
    else:
        return []
    call = _last_call(db, task['id'])
    if _unknown_submission(call) or not (budget_wait or _can_resume(task, call)):
        return []
    return ['resume' if budget_wait else 'retry']
