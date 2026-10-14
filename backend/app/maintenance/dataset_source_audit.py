"""Read-only relational checks for JSON dataset references; never reads assets."""
import json

from app.core.exceptions import StorageError
from app.domain.analysis_sources import DATASET_ENGINE, prepared_dataset_source, source_dict
from app.domain.dataset_preparation.contracts import PreparationSummary
from app.domain.dataset_preparation.service import (
    CandidateReference, PreparationDecisionRequest, PreparationState,
    preparation_input_version, candidate_id, request_digest,
)


def object_json(value):
    try:
        result = value if isinstance(value, dict) else json.loads(value)
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        # The general JSON audit reports malformed legacy TEXT independently.
        return {}


def audit_preparations(db, datasets, tasks):
    """Validate persisted local lineage only; candidate bytes remain out of scope."""
    checks, versions, valid_states, valid_decisions = [], {}, {}, {}
    checkpoints = {row['id']: row for row in db.execute("SELECT c.* FROM task_checkpoints c JOIN tasks t ON t.id=c.task_id WHERE t.task_type='prepare_dataset'")}
    latest = {}
    for row in checkpoints.values():
        if row['task_id'] not in latest or row['seq'] > latest[row['task_id']]['seq']:
            latest[row['task_id']] = row
    invalid = 0
    for row in checkpoints.values():
        try:
            task = tasks[row['task_id']]
            state = PreparationState.model_validate(row['state_json']).model_dump(mode='json')
            expected_input = preparation_input_version(task)
            project, parent = datasets[expected_input['source']['dataset_id']]
            if (state['input_version'] != expected_input or expected_input['source'] != parent
                    or project != task['project_id']):
                raise ValueError('Checkpoint raw source mismatch')
            if state['candidate'] and (state['candidate']['id'] != candidate_id(task['id'])
                    or state['candidate']['object_key'] != f"prepared-datasets/{state['candidate']['id']}/{state['candidate']['sha256']}.json"):
                raise ValueError('Candidate reference mismatch')
            valid_states[row['id']] = state
        except (KeyError, TypeError, ValueError, StorageError):
            invalid += 1
    checks.append(dict(table='task_checkpoints', column='dataset_source', rows=len(checkpoints), invalid=invalid))

    waits = {row['id']: row for row in db.execute('SELECT * FROM task_waits')}
    decisions = {row['id']: row for row in db.execute('SELECT * FROM dataset_preparation_decisions')}
    invalid = 0
    for row in decisions.values():
        try:
            task = tasks[row['task_id']]
            request = PreparationDecisionRequest.model_validate(row['request_json']).model_dump(mode='json')
            checkpoint, state = checkpoints[row['checkpoint_id']], valid_states[row['checkpoint_id']]
            wait = waits[row['wait_id']]
            expected_input = preparation_input_version(task)
            if (row['user_id'] != task['user_id'] or row['project_id'] != task['project_id']
                    or checkpoint['task_id'] != task['id'] or checkpoint['next_node'] != 'await_confirmation'
                    or not state['candidate'] or request['checkpoint_id'] != checkpoint['id']
                    or request['wait_id'] != wait['id'] or request['operation'] != row['operation']
                    or request['input_version'] != expected_input or request_digest(request) != row['request_digest']
                    or wait['task_id'] != task['id'] or wait['user_id'] != task['user_id']
                    or wait['project_id'] != task['project_id'] or wait['kind'] != 'dataset_preparation_confirmation'
                    or wait['input_version'] != expected_input or wait['task_revision'] != request['expected_task_revision']
                    or wait['status'] != ('resolved' if row['operation'] == 'approve' else 'superseded')):
                raise ValueError('Decision wait/source mismatch')
            valid_decisions[row['id']] = row
        except (KeyError, TypeError, ValueError, StorageError):
            invalid += 1
    checks.append(dict(table='dataset_preparation_decisions', column='dataset_source', rows=len(decisions), invalid=invalid))

    rows = db.execute('SELECT * FROM prepared_dataset_versions').fetchall()
    invalid = 0
    for row in rows:
        try:
            task = tasks[row['task_id']]
            expected_input = preparation_input_version(task)
            project, parent = datasets[row['parent_dataset_id']]
            final = latest[task['id']]
            state = valid_states[final['id']]
            approval = valid_decisions[row['decision_id']]
            reviewed = valid_states[approval['checkpoint_id']]
            summary = PreparationSummary.model_validate(row['summary_json'])
            candidate = {key: row[key] for key in CandidateReference.model_fields}
            if (task['status'] != 'succeeded' or task['project_id'] != project or row['created_by'] != task['user_id']
                    or expected_input['source'] != parent or row['file_id'] != parent['file_id']
                    or final['node'] != 'done' or final['next_node'] != 'done'
                    or state['result_id'] != row['id'] or state['decision_id'] != approval['id']
                    or state['candidate'] != candidate or approval['task_id'] != task['id'] or approval['operation'] != 'approve'
                    or reviewed['candidate'] != candidate or reviewed['recipe'] != state['recipe']
                    or row['recipe_json'] != state['recipe']
                    or [(c.column, c.name, c.unit.model_dump()) for c in summary.columns]
                        != [(f['column'], f['name'], f['unit']) for f in state['recipe']['fields']]):
                raise ValueError('Published preparation mismatch')
            from app.domain.datasets.contracts import rectangle
            start, end = rectangle(state['recipe']['data_range'])
            if summary.record_count != end[0] - start[0] + 1:
                raise ValueError('Published rectangle summary mismatch')
            versions[row['id']] = (project, prepared_dataset_source(row, parent))
        except (KeyError, TypeError, ValueError, StorageError):
            invalid += 1
    checks.append(dict(table='prepared_dataset_versions', column='dataset_source', rows=len(rows), invalid=invalid))
    return versions, checks


def audit_dataset_sources(db):
    datasets = {}
    rows = db.execute('''SELECT d.*, s.parser_version, s.source_sha256,
        f.project_id, f.sha256 AS file_sha256, s.manifest_json
        FROM dataset_versions d JOIN file_structure_versions s ON s.id=d.structure_id
        JOIN files f ON f.id=d.file_id JOIN tasks t ON t.id=s.task_id
        WHERE s.file_id=d.file_id AND s.version=d.version AND t.status='succeeded'
        AND t.project_id=f.project_id AND s.manifest_json IS NOT NULL''').fetchall()
    for row in rows:
        manifest = row['manifest_json']
        if (not isinstance(manifest, dict) or not isinstance(manifest.get('dataset_ids'), list)
                or row['id'] not in manifest['dataset_ids']
                or row['source_sha256'] != row['file_sha256']):
            continue
        datasets[row['id']] = (row['project_id'], {
            'kind': 'dataset_version', 'schema_version': 1, 'dataset_id': row['id'],
            'structure_id': row['structure_id'], 'dataset_version': row['version'],
            'file_id': row['file_id'], 'source_sha256': row['source_sha256'],
            'dataset_sha256': row['sha256'], 'dataset_size_bytes': row['size_bytes'],
            'dataset_schema_version': row['schema_version'], 'sheet_index': row['sheet_index'],
            'sheet_name': row['sheet_name'], 'parser_version': row['parser_version'],
        })
    runs = {row['id']: (row['file_id'], object_json(row['result_json']))
            for row in db.execute('SELECT id,file_id,result_json FROM analysis_runs')}
    tasks = {row['id']: row for row in db.execute('SELECT * FROM tasks')}
    prepared, preparation_checks = audit_preparations(db, datasets, tasks)
    datasets.update(prepared)
    checks = []
    for table, column in (('analysis_setups', 'setup_json'), ('analysis_runs', 'result_json'),
                           ('figures', 'figure_json'), ('explanations', 'explanation_json'),
                           ('reports', 'report_json'), ('tasks', 'input_snapshot')):
        total = invalid = 0
        for row in (tasks.values() if table == 'tasks' else db.execute('SELECT * FROM ' + table)):
            if table == 'tasks' and row['task_type'] in ('review_ocr','analysis_plan'):
                continue
            value = object_json(row[column])
            run_id = (value.get('result', {}).get('id') if isinstance(value.get('result'), dict) else None)
            if table in ('figures', 'explanations', 'reports'):
                run_id = row['analysis_run_id']
            run = runs.get(run_id, (None, {}))
            requires_source = ('source' in value or 'source' in run[1]
                or table == 'analysis_runs' and row['engine_version'] == DATASET_ENGINE
                or table == 'tasks' and (row['workflow_version'].endswith('_v2') or row['task_type'] == 'prepare_dataset'))
            if not requires_source:
                continue
            total += 1
            try:
                source = source_dict(value.get('source'))
                project_id, expected = datasets[source['dataset_id']]
                if source != expected:
                    raise ValueError('Dataset reference mismatch')
                if table == 'tasks' and row['task_type'] == 'prepare_dataset':
                    version = preparation_input_version(row)
                    if source['kind'] != 'dataset_version' or row['project_id'] != project_id or version['source'] != source:
                        raise ValueError('Preparation task source mismatch')
                elif table in ('analysis_setups', 'analysis_runs'):
                    if (row['file_id'] != source['file_id'] or value['file_id'] != source['file_id']
                            or value['source_sha256'] != source['source_sha256']
                            or value['selection']['sheet_name'] != source['sheet_name']):
                        raise ValueError('Analysis source mismatch')
                    if table == 'analysis_runs' and (row['engine_version'] != DATASET_ENGINE
                                                     or value['engine']['id'] != DATASET_ENGINE):
                        raise ValueError('Dataset engine mismatch')
                else:
                    if run[0] != source['file_id'] or run[1].get('source') != source:
                        raise ValueError('Predecessor source mismatch')
                    if table == 'tasks':
                        if (row['project_id'] != project_id or type(value['schema_version']) is not int
                                or value['schema_version'] != 2 or value['result']['source'] != source
                                or value['file']['id'] != source['file_id']
                                or value['file']['sha256'] != source['source_sha256']
                                or row['workflow_version'] != row['task_type'] + '_v2'):
                            raise ValueError('Task source mismatch')
                    elif value['analysis_run_id'] != row['analysis_run_id']:
                        raise ValueError('Artifact run mismatch')
                    if table == 'reports':
                        from app.adapters.report_store import digest
                        snapshot = object_json(row['input_json'])
                        if snapshot.get('source') != source or value['input_sha256'] != digest(snapshot):
                            raise ValueError('Report input mismatch')
            except (KeyError, TypeError, ValueError, StorageError):
                invalid += 1
        checks.append({'table': table, 'column': 'dataset_source', 'rows': total, 'invalid': invalid})
    return checks + preparation_checks
