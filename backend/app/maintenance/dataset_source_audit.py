"""Read-only relational checks for JSON dataset references; never reads assets."""
import json

from app.core.exceptions import StorageError
from app.domain.analysis_sources import DATASET_ENGINE, prepared_dataset_source, source_dict, statistics_engine
from app.domain.dataset_preparation.contracts import PreparationSummary
from app.domain.dataset_preparation.service import (
    CandidateReference, PreparationDecisionRequest, PreparationState,
    preparation_input_version, candidate_id, request_digest, state_model, decision_model, validate_snapshot,
)


def object_json(value):
    try:
        result = value if isinstance(value, dict) else json.loads(value)
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        # The general JSON audit reports malformed legacy TEXT independently.
        return {}


def validate_projection_v2_source(db, task, snapshot, result):
    """Bind the new frozen request to persisted config/run facts, without math."""
    from app.adapters.figure_workbench_store import projection_request_digest, validate_projection_checkpoint
    from app.domain.external_processing import digest
    binding = snapshot['figure_workbench']
    if not isinstance(binding, dict) or not isinstance(binding.get('version_id'), str):
        raise ValueError('Projection configuration reference malformed')
    config = db.execute('''SELECT v.*,c.project_id,c.analysis_run_id FROM figure_config_versions v
        JOIN figure_configurations c ON c.id=v.configuration_id WHERE v.id=%s''', (binding['version_id'],)).fetchone()
    if not config:
        raise ValueError('Projection configuration missing')
    expected_source = dict(source=result['source'], result_sha256=digest(result), analysis_plan=result['analysis_plan'])
    if 'figure_contract' in config['source_json']:
        if type(config['source_json']['figure_contract']) is not int or config['source_json']['figure_contract'] not in (2,3):
            raise ValueError('Projection contract differs')
        expected_source['figure_contract'] = config['source_json']['figure_contract']
    if (type(snapshot.get('projection_execution')) is not int or snapshot['projection_execution'] != 2
            or snapshot['result'] != result or config['project_id'] != task['project_id']
            or config['analysis_run_id'] != result['id'] or config['created_by'] != task['user_id']
            or snapshot['output_language'] != config['config_json']['language']
            or config['source_json'] != expected_source
            or config['sha256'] != digest(dict(config=config['config_json'], source=config['source_json']))
            or binding['configuration_sha256'] != config['sha256']
            or task['input_digest'] != projection_request_digest(config)):
        raise ValueError('Projection frozen source differs')
    checkpoint = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',
                            (task['id'],)).fetchone()
    validate_projection_checkpoint(task, checkpoint)


def audit_preparations(db, datasets, tasks):
    """Validate persisted local lineage only; candidate bytes remain out of scope."""
    checks, versions, valid_states, valid_decisions = [], {}, {}, {}
    published_rows = db.execute('SELECT * FROM prepared_dataset_versions ORDER BY version,id').fetchall()
    available = dict(datasets)
    for published in published_rows:
        try:
            project, root = datasets[published['parent_dataset_id']]
            version = {'dataset_preparation_v1':1,'dataset_preparation_v2':2,'dataset_preparation_v3':3}[tasks[published['task_id']]['workflow_version']]
            available[published['id']] = (project, prepared_dataset_source(published, root, schema_version=version))
        except (KeyError, TypeError, ValueError, StorageError):
            pass
    checkpoints = {row['id']: row for row in db.execute("SELECT c.* FROM task_checkpoints c JOIN tasks t ON t.id=c.task_id WHERE t.task_type='prepare_dataset'")}
    latest = {}
    for row in checkpoints.values():
        if row['task_id'] not in latest or row['seq'] > latest[row['task_id']]['seq']:
            latest[row['task_id']] = row
    invalid = 0
    for row in checkpoints.values():
        try:
            task = tasks[row['task_id']]
            state = state_model(task).model_validate(row['state_json']).model_dump(mode='json')
            expected_input = preparation_input_version(task)
            project, parent = available[expected_input['source']['dataset_id']]
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
            request = decision_model(task).model_validate(row['request_json']).model_dump(mode='json')
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

    rows = published_rows
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
            if task['workflow_version'] in ('dataset_preparation_v2','dataset_preparation_v3'):
                from app.domain.dataset_preparation.quality_service import audit_published
                v3=task['workflow_version']=='dataset_preparation_v3'
                if v3:
                    from app.domain.dataset_preparation.derivation_service import audit_published
                from app.domain.dataset_preparation.quality_contracts import QualitySummary
                from app.domain.file_lifecycle.quality_references import valid_derivation,valid_derivation_v3
                from app.domain.dataset_preparation.filter_contracts import FilterSummary
                source = audit_published(db, task, row)
                snapshot = validate_snapshot(task)
                if (snapshot['root_source'] != parent or versions[snapshot['source']['dataset_id']] != (project,snapshot['source'])
                        or row['decision_id'] not in valid_decisions or final['id'] not in valid_states):
                    raise ValueError('Quality parent chain mismatch')
                summary = (FilterSummary if v3 and snapshot['operation']=='population_filter' else QualitySummary).model_validate(row['summary_json'])
                base = next(r for r in rows if r['id'] == snapshot['source']['dataset_id'])
                count = base['summary_json'].get('retained_record_count',base['summary_json'].get('record_count'))
                relation = db.execute('SELECT * FROM '+('prepared_dataset_derivations_v3' if v3 else 'prepared_dataset_derivations')+' WHERE prepared_dataset_id=%s',(row['id'],)).fetchone()
                if (summary.base_record_count != count or not summary.retained_record_count
                        or not (valid_derivation_v3 if v3 else valid_derivation)(relation,{'prepared_dataset_versions':{r['id']:r for r in rows}})
                        or relation['manifest_entry_count'] != summary.impact_count):
                    raise ValueError('Quality receipt summary mismatch')
                versions[row['id']] = (project, source)
                continue
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
    derivations = db.execute('SELECT * FROM prepared_dataset_derivations').fetchall()
    invalid = sum(r['prepared_dataset_id'] not in versions or versions[r['prepared_dataset_id']][1].get('schema_version') != 2 for r in derivations)
    checks.append(dict(table='prepared_dataset_derivations',column='dataset_source',rows=len(derivations),invalid=invalid))
    derivations = db.execute('SELECT * FROM prepared_dataset_derivations_v3').fetchall()
    invalid = sum(r['prepared_dataset_id'] not in versions or versions[r['prepared_dataset_id']][1].get('schema_version') != 3 for r in derivations)
    checks.append(dict(table='prepared_dataset_derivations_v3',column='dataset_source',rows=len(derivations),invalid=invalid))
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
                if source.get('schema_version') in (2,3) and (table == 'reports' or table == 'tasks' and row['task_type'] == 'word_report'):
                    processing=relational_processing(db,datasets,source)
                    frozen = object_json(row['input_json']) if table == 'reports' else value
                    if frozen.get('processing') != processing:
                        raise ValueError('Frozen report quality receipt mismatch')
                if table == 'tasks' and row['task_type']=='analysis_recommendation':
                    from app.domain.analysis_recommendation.service import validate_snapshot
                    frozen=validate_snapshot(row)
                    if frozen['source']!=source or row['project_id']!=project_id: raise ValueError('Recommendation source mismatch')
                elif table == 'tasks' and row['task_type'] == 'prepare_dataset':
                    version = preparation_input_version(row)
                    expected_kind = 'prepared_dataset_version' if row['workflow_version'] in ('dataset_preparation_v2','dataset_preparation_v3') else 'dataset_version'
                    if source['kind'] != expected_kind or row['project_id'] != project_id or version['source'] != source:
                        raise ValueError('Preparation task source mismatch')
                elif table in ('analysis_setups', 'analysis_runs'):
                    if (row['file_id'] != source['file_id'] or value['file_id'] != source['file_id']
                            or value['source_sha256'] != source['source_sha256']
                            or value['selection']['sheet_name'] != source['sheet_name']):
                        raise ValueError('Analysis source mismatch')
                    if table == 'analysis_runs' and (row['engine_version'] != statistics_engine(value)
                                                     or value['engine']['id'] != row['engine_version']):
                        raise ValueError('Dataset engine mismatch')
                else:
                    if run[0] != source['file_id'] or run[1].get('source') != source:
                        raise ValueError('Predecessor source mismatch')
                    if table == 'tasks':
                        configured = row['task_type'] in ('figure_projection','figure_workbench','figure_explanation')
                        workflows = (('figure_projection_v1','figure_projection_v2') if row['task_type']=='figure_projection'
                                     else (row['task_type'] + ('_v1' if configured else '_v2'),))
                        if (row['project_id'] != project_id or type(value['schema_version']) is not int
                                or value['schema_version'] != 2 or value['result']['source'] != source
                                or (not configured and (value['file']['id'] != source['file_id']
                                or value['file']['sha256'] != source['source_sha256']))
                                or row['workflow_version'] not in workflows):
                            raise ValueError('Task source mismatch')
                        if row['workflow_version'] == 'figure_projection_v2':
                            validate_projection_v2_source(db, row, value, run[1])
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


def relational_processing(db,datasets,source):
    """Rebuild frozen processing identities from audited rows, without asset IO."""
    def one(current):
        row=db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s',(current['dataset_id'],)).fetchone()
        v3=current['schema_version']==3
        table='prepared_dataset_derivations_v3' if v3 else 'prepared_dataset_derivations'
        relation=db.execute('SELECT * FROM '+table+' WHERE prepared_dataset_id=%s',(current['dataset_id'],)).fetchone()
        value=dict(schema_version=current['schema_version'],recipe=row['recipe_json'],receipt=row['summary_json'],
            manifest={key:relation['manifest_'+key] for key in ('object_key','sha256','size_bytes','entry_count')},
            base_source=datasets[relation['base_prepared_dataset_id']][1])
        if v3:value['operation']=relation['operation']
        return value
    processing=one(source)
    if source['schema_version']==3:
        parent=processing['base_source'];ancestors=[];seen={source['dataset_id']}
        while parent['schema_version'] in (2,3):
            if parent['dataset_id'] in seen:raise ValueError('Cyclic processing')
            seen.add(parent['dataset_id']);previous=one(parent)
            ancestors.append(dict(source=parent,operation=previous.get('operation','quality'),recipe=previous['recipe'],receipt=previous['receipt'],manifest=previous['manifest']))
            parent=previous['base_source']
        processing['ancestors']=ancestors
    return processing
