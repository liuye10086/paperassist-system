"""Central file-scoped reads of persisted FKs and frozen source identities.

No lineage rows are backfilled or copied. All reads use the caller's transaction.
Only registered candidates are counted; storage directories are never scanned.
"""
import json
from datetime import datetime

from app.domain.file_lifecycle.contracts import ACTIVE, digest
from app.domain.tasks.legacy import job_data, mapped_status, public_legacy_task
from app.core.exceptions import StorageError

DIRECT = {
    'parse_versions': 'file_parse_results', 'structure_versions': 'file_structure_versions',
    'dataset_versions': 'dataset_versions', 'prepared_dataset_versions': 'prepared_dataset_versions',
    'ocr_review_versions': 'ocr_review_versions', 'confirmed_plans': 'confirmed_analysis_plans',
    'analysis_setups': 'analysis_setups', 'analysis_runs': 'analysis_runs',
}
SOURCE_TABLES = {
    'parse_id': 'parse_versions', 'parent_parse_id': 'parse_versions',
    'structure_id': 'structure_versions', 'parent_dataset_id': 'dataset_versions',
    'prepared_dataset_id': 'prepared_dataset_versions', 'base_prepared_dataset_id': 'prepared_dataset_versions',
    'plan_id': 'confirmed_plans', 'analysis_run_id': 'analysis_runs',
    'figure_id': 'figures', 'explanation_id': 'explanations', 'report_id': 'reports',
    'configuration_id': 'figure_configurations', 'figure_config_version_id': 'figure_config_versions',
    'config_version_id': 'figure_config_versions', 'projection_id': 'figure_projection_results',
    'collection_id': 'report_collections', 'collection_version_id': 'report_collection_versions',
    'build_request_id': 'report_build_requests',
    'evidence_version_id': 'external_evidence_versions',
}


def object_value(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def frozen_references(snapshot):
    """Enumerate typed source identities, including nested result/artifact sources."""
    for node in nodes(snapshot):
        for key, group in SOURCE_TABLES.items():
            if isinstance(node.get(key), str):
                yield group, node[key]
        if isinstance(node.get('dataset_id'), str):
            yield ('prepared_dataset_versions' if node.get('kind') == 'prepared_dataset_version'
                   else 'dataset_versions'), node['dataset_id']
        for key, group in (('result', 'analysis_runs'), ('figure', 'figures'),
                           ('explanation', 'explanations')):
            child = node.get(key)
            if isinstance(child, dict) and isinstance(child.get('id'), str):
                yield group, child['id']


def file_ids(snapshot):
    result = set()
    for node in nodes(snapshot):
        if isinstance(node.get('file_id'), str):
            result.add(node['file_id'])
        if isinstance(node.get('file'), dict) and isinstance(node['file'].get('id'), str):
            result.add(node['file']['id'])
    return result


def source_identity_valid(snapshot, indexes, file, producers):
    """Resolve each frozen version/hash against the same file's saved rows."""
    if not isinstance(snapshot, dict):
        return False
    if not file_ids(snapshot) <= {file['id']}:
        return False
    for node in nodes(snapshot):
        # Persisted JSON only has an object constraint. Validate every identity
        # before lookup, including untyped/nested artifact source nodes.
        for key in (*SOURCE_TABLES, 'dataset_id', 'file_id'):
            if key in node and (not isinstance(node[key], str) or not node[key]):
                return False
        for key in ('result', 'figure', 'explanation'):
            child = node.get(key)
            if isinstance(child, dict) and 'id' in child and (
                    not isinstance(child['id'], str) or not child['id']):
                return False
        if node.get('kind') in ('dataset_version','prepared_dataset_version'):
            from app.domain.analysis_sources import source_dict
            try:
                source_dict(node)
            except StorageError:
                return False
        if node.get('project_id', file['project_id']) != file['project_id']:
            return False
        original = node.get('file')
        if 'file' in node and (not isinstance(original, dict)
                or not isinstance(original.get('id'), str) or not original['id']):
            return False
        if isinstance(original, dict) and any(original.get(k, file[k]) != file[k]
                for k in ('id','sha256','size_bytes','file_type')):
            return False
        if 'source_sha256' in node and node['source_sha256'] != file['sha256']:
            return False
        if 'dataset_id' in node:
            kind = 'prepared_dataset_versions' if node.get('kind')=='prepared_dataset_version' else 'dataset_versions'
            row = indexes[kind].get(node['dataset_id'])
            if row is None:
                return False
            for source_key,row_key in (('dataset_version','version'),('dataset_sha256','sha256'),('dataset_size_bytes','size_bytes')):
                if source_key in node and node[source_key] != row[row_key]:
                    return False
            parent = indexes['dataset_versions'].get(row['parent_dataset_id']) if kind=='prepared_dataset_versions' else row
            if parent is None:
                return False
            for source_key,row_key in (('structure_id','structure_id'),('sheet_index','sheet_index'),('sheet_name','sheet_name')):
                if source_key in node and node[source_key] != parent[row_key]:
                    return False
            if kind=='prepared_dataset_versions' and (
                    node.get('parent_dataset_id',parent['id']) != parent['id']
                    or node.get('parent_dataset_version',parent['version']) != parent['version']):
                return False
        if 'parse_id' in node:
            row = indexes['parse_versions'].get(node['parse_id'])
            if row is None or node.get('parse_version',row['version']) != row['version']:
                return False
            if 'document_sha256' in node:
                document = (row.get('result_json') or {}).get('object')
                if not isinstance(document, dict) or node['document_sha256'] != document.get('sha256'):
                    return False
            if 'parser_version' in node and node['parser_version'] != row['parser_version']:
                return False
            if 'selected_pages' in node and node['selected_pages'] != producers.get(row['task_id'],{}).get('page_numbers'):
                return False
        if 'plan_id' in node:
            row = indexes['confirmed_plans'].get(node['plan_id'])
            if row is None or node.get('sha256',row['sha256']) != row['sha256']:
                return False
    return all(identifier in indexes[kind] for kind, identifier in frozen_references(snapshot))


def public_source_groups(groups, indexes, tasks, file, user_id, producers, proofs=None):
    """Keep internal rows intact; expose only proved producer/parent chains.

    Removing unsafe dependencies to a fixed point also handles consumers of an
    otherwise valid row whose ancestor/producer has corrupt scope or sources.
    """
    by_task = {task['id']: task for task in tasks}
    rows, dependencies, safe = {}, {}, set()
    producer_types = dict(parse_versions='parse_file', structure_versions='extract_dataset',
        prepared_dataset_versions='prepare_dataset', ocr_review_versions='review_ocr',
        confirmed_plans='analysis_plan', figure_projection_decisions='figure_projection',
        report_build_requests='collection_word_report')
    for kind, members in groups.items():
        for row in members:
            key = (kind, row['id'] if 'id' in row else row['file_id'])
            rows[key] = row
            refs = set()
            if kind in ('manuscript_figure_language_versions','school_template_versions','manuscript_school_changes','journal_material_refs'):
                if row.get('_integrity_valid') and row['project_id']==file['project_id'] and row['user_id']==user_id:
                    safe.add(key)
                dependencies[key]=set()
                continue
            valid = row.get('file_id', file['id']) == file['id'] and row.get('created_by', user_id) == user_id
            valid &= row.get('project_id',file['project_id']) == file['project_id']
            from app.domain.file_lifecycle.figure_report_references import parent_links
            refs.update(parent_links(kind,row))
            if 'source_sha256' in row:
                valid &= row['source_sha256'] == file['sha256']
            for column, target in SOURCE_TABLES.items():
                if column in row and row[column] is not None:
                    refs.add((target, row[column]))
            if row.get('parent_id') is not None:
                refs.add((kind, row['parent_id']))
            for column, target in (('figure_id','figures'), ('explanation_id','explanations')):
                if row.get(column) is not None:
                    parent = indexes[target].get(row[column])
                    valid &= parent is not None and parent['analysis_run_id'] == row.get('analysis_run_id')
            if kind == 'external_evidence_versions':
                valid &= row.get('_integrity_valid',False)
                if row.get('previous_version_id') is not None:
                    refs.add((kind,row['previous_version_id']))
                if row.get('document_version_id') is not None:
                    refs.add(('parse_versions',row['document_version_id']))
                if row.get('ocr_review_version_id') is not None:
                    refs.add(('ocr_review_versions',row['ocr_review_version_id']))
            if kind == 'prepared_dataset_derivations_v3':
                from app.domain.file_lifecycle.quality_references import valid_derivation_v3
                valid &= valid_derivation_v3(row,indexes)
            if kind == 'prepared_dataset_derivations':
                from app.domain.file_lifecycle.quality_references import valid_derivation
                valid &= valid_derivation(row, indexes)
            producing = []
            if row.get('task_id') is not None:
                producer = by_task.get(row['task_id'])
                valid &= producer is not None and producer['_integrity_valid']
                if producer is not None:
                    producing.append(producer)
                    valid &= producer['task_type'] == producer_types.get(kind)
                    source = object_value(producer['input_snapshot'].get('source'))
                    if kind == 'prepared_dataset_versions':
                        if producer.get('workflow_version') in ('dataset_preparation_v2','dataset_preparation_v3'):
                            relation_kind='prepared_dataset_derivations_v3' if producer['workflow_version']=='dataset_preparation_v3' else 'prepared_dataset_derivations'
                            derivation = indexes[relation_kind].get(row['id'])
                            valid &= derivation is not None
                            refs.add((relation_kind, row['id']))
                            if derivation is not None:
                                valid &= source.get('dataset_id') == derivation['base_prepared_dataset_id']
                        else:
                            valid &= source.get('dataset_id') == row['parent_dataset_id']
                    if kind == 'ocr_review_versions':
                        valid &= source.get('parse_id') == row['parent_parse_id']
            if kind in ('figures', 'explanations', 'reports'):
                singular = dict(figures='figure', explanations='explanation', reports='report')[kind]
                producing.extend(t for t in tasks if t.get('result_'+singular+'_id') == row['id'])
            for producer in producing:
                valid &= producer['_integrity_valid']
                refs.update(frozen_references(producer.get('_scoped_snapshot',producer['input_snapshot'])))
            for column in ('setup_json', 'result_json', 'input_json', 'plan_json',
                           'figure_json', 'explanation_json', 'report_json', 'source_json',
                           'content_json', 'item_json'):
                if row.get(column) is not None:
                    source = object_value(row[column])
                    from app.domain.file_lifecycle.research_references import scoped_snapshot
                    source = scoped_snapshot(source,file['id'],proofs or {})
                    valid &= source_identity_valid(source, indexes, file, producers)
                    refs.update(frozen_references(source))
            dependencies[key] = refs
            if valid:
                safe.add(key)
    while True:
        retained = {key for key in safe if dependencies[key] <= safe}
        if retained == safe:
            break
        safe = retained
    for task in tasks:
        refs = set(frozen_references(task.get('_scoped_snapshot',task['input_snapshot'])))
        refs.update(key for key, row in rows.items() if row.get('task_id') == task['id'])
        task['_integrity_valid'] &= refs <= safe
    return {kind: [row for key, row in rows.items() if key[0] == kind and key in safe]
            for kind in groups}


def facts(row):
    """Stable identity/state only; no raw document text, paths or credentials."""
    result = {}
    for key, value in row.items():
        if key in ('created_at', 'completed_at', 'updated_at', 'uploaded_at', 'finished_at',
                   'heartbeat_at', 'lease_expires_at', 'available_at', 'publish_attempts'):
            continue
        if key.startswith('_'):
            continue
        if key.endswith('_json') or key.endswith('object_key') or key in ('input_snapshot', 'figure_candidate'):
            result[key + '_digest'] = digest(value) if value is not None else None
        elif key == 'published_at':
            result['published'] = value is not None
        else:
            result[key] = value.isoformat() if isinstance(value,datetime) else value
    return result


def task_contract_valid(task):
    try:
        if task['task_type']=='parse_file':
            from app.domain.file_parsing import validate_snapshot
        elif task['task_type']=='extract_dataset':
            from app.domain.datasets.snapshots import validate_snapshot
        elif task['task_type']=='prepare_dataset':
            from app.domain.dataset_preparation.service import validate_snapshot
        elif task['task_type']=='review_ocr':
            from app.domain.ocr_review.service import validate_snapshot
        elif task['task_type']=='analysis_plan':
            from app.domain.analysis_plan.service import validate_snapshot
        else:
            return True
        validate_snapshot(task)
        return True
    except (StorageError,KeyError,ValueError,TypeError):
        return False


def read_references(db, file, user_id):
    file_id, project_id = file['id'], file['project_id']
    groups = {kind: [dict(row) for row in db.execute(f'SELECT * FROM {table} WHERE file_id=%s', (file_id,))]
              for kind, table in DIRECT.items()}
    groups['prepared_dataset_derivations'] = [dict(row) for row in db.execute(
        'SELECT d.*,d.prepared_dataset_id AS id,v.file_id FROM prepared_dataset_derivations d '
        'JOIN prepared_dataset_versions v ON v.id=d.prepared_dataset_id WHERE v.file_id=%s', (file_id,))]
    groups['prepared_dataset_derivations_v3']=[dict(row) for row in db.execute(
        'SELECT d.*,d.prepared_dataset_id AS id,v.file_id FROM prepared_dataset_derivations_v3 d '
        'JOIN prepared_dataset_versions v ON v.id=d.prepared_dataset_id WHERE v.file_id=%s',(file_id,))]
    from app.domain.file_lifecycle.research_references import valid_evidence,research_proofs,scoped_snapshot
    groups['external_evidence_versions']=[dict(row) for row in db.execute('SELECT * FROM external_evidence_versions WHERE file_id=%s',(file_id,))]
    for evidence in groups['external_evidence_versions']:
        evidence['_integrity_valid']=valid_evidence(db,evidence,file,user_id)
    runs = [row['id'] for row in groups['analysis_runs']]
    for kind in ('figures', 'explanations', 'reports'):
        groups[kind] = [dict(row) for row in db.execute(f'SELECT * FROM {kind} WHERE analysis_run_id=ANY(%s)', (runs,))]
    from app.domain.file_lifecycle.figure_report_references import read_groups
    groups.update(read_groups(db,file,runs))
    groups['manuscript_figure_language_versions']=[dict(r) for r in db.execute('SELECT * FROM manuscript_figure_language_versions WHERE file_id=%s OR replacement_file_id=%s',(file_id,file_id))]
    for version in groups['manuscript_figure_language_versions']:
        try:
            from app.domain.manuscripts.figure_language import FigureLanguageService
            from app.domain.report_collections.service import scoped_store
            FigureLanguageService(scoped_store(user_id,db.config)).row(db,project_id,version['id'])
            version['_integrity_valid']=version['user_id']==user_id
        except Exception: version['_integrity_valid']=False
    from app.domain.school_templates.service import SchoolTemplateService
    from app.domain.report_collections.service import scoped_store
    school_service=SchoolTemplateService(scoped_store(user_id,db.config))
    groups['school_template_versions']=[dict(r) for r in db.execute("""SELECT v.*,s.file_id,s.source_json,
        (SELECT to_jsonb(c) FROM school_template_confirmations c WHERE c.template_version_id=v.id) AS confirmation_json,
        (SELECT to_jsonb(p) FROM thesis_profiles p JOIN school_template_confirmations c ON c.id=p.bound_confirmation_id WHERE c.template_version_id=v.id) AS binding_json
        FROM school_template_versions v JOIN school_template_sources s ON s.template_version_id=v.id WHERE s.file_id=%s""",(file_id,))]
    for version in groups['school_template_versions']:
        try:
            school_service.row(db,project_id,version['id'])
            sources,_=school_service.validate(db,version)
            school_service.confirmation(db,version)
            version['_integrity_valid']=not bool(school_service.current_changes(db,version,sources))
        except Exception:version['_integrity_valid']=False
    from app.domain.manuscripts.school_changes import SchoolChangeService
    change_service=SchoolChangeService(scoped_store(user_id,db.config))
    groups['manuscript_school_changes']=[dict(r) for r in db.execute('SELECT * FROM manuscript_school_changes WHERE file_id=%s',(file_id,))]
    for change in groups['manuscript_school_changes']:
        try:
            change_service.row(db,project_id,change['manuscript_id'],change['id']);change['_integrity_valid']=True
        except Exception:change['_integrity_valid']=False
    from app.domain.journals.retention import read_refs
    groups['journal_material_refs']=read_refs(db,file,user_id)
    school_tasks={v['task_id']:v for v in groups['school_template_versions']}
    indexes = {kind: {row['id']: row for row in rows if 'id' in row} for kind, rows in groups.items()}
    output_tasks = {row['task_id'] for rows in groups.values() for row in rows if row.get('task_id')}
    project_files = {r['id'] for r in db.execute('SELECT id FROM files WHERE project_id=%s',(project_id,))}
    tasks, unknown = [], False
    # Project/date index bounds this scan. Recursive JSON inspection covers old
    # nested artifact snapshots without a brittle finite list of SQL paths.
    # Reverse result FKs also identify corrupt producers outside this project.
    # Their identities remain private, while their persisted impact is retained.
    project_tasks = db.execute('''SELECT * FROM tasks WHERE project_id=%s OR id=ANY(%s)
        OR result_figure_id=ANY(%s) OR result_explanation_id=ANY(%s) OR result_report_id=ANY(%s)
        ORDER BY created_at DESC,id''', (project_id, list(output_tasks),
        list(indexes['figures']), list(indexes['explanations']), list(indexes['reports']))).fetchall()
    producers = {row['id']:row['input_snapshot'] for row in project_tasks}
    proofs=research_proofs(db,project_tasks,user_id,project_id)
    for row in project_tasks:
        task = dict(row)
        snapshot = task['input_snapshot']
        if task['task_type'] in ('journal_recommendation','journal_format_check','journal_adaptation'):
            if file_id not in file_ids(snapshot):continue
            scoped=dict(materials=[n for n in nodes(snapshot) if n.get('file_id')==file_id])
        elif task['task_type']=='school_template_parse':
            version=school_tasks.get(task['id'])
            if version is None:continue
            scoped=dict(file=version['source_json']['file'])
        else:scoped=scoped_snapshot(snapshot,file_id,proofs)
        refs = set(frozen_references(scoped))
        ids = file_ids(scoped if task['task_type']=='school_template_parse' else snapshot)
        scoped_ids=file_ids(scoped)
        linked = (file_id in ids or task['id'] in output_tasks
                  or any(identifier in indexes[kind] for kind, identifier in refs)
                  or any(task.get('result_'+kind+'_id') in indexes[kind+'s']
                         for kind in ('figure', 'explanation', 'report')))
        # Malformed snapshots lacking every known source cannot safely count as
        # zero impact; retain the project task as an unknown dependency.
        if not ids and not refs and task['id'] not in output_tasks:
            linked = True
        if not ids <= project_files:
            linked = True
        if not linked:
            continue
        valid = task['user_id'] == user_id and task['project_id'] == project_id and scoped_ids <= {file_id}
        valid = valid and all(identifier in indexes[kind] for kind, identifier in refs)
        valid = valid and bool(ids or refs or task['id'] in output_tasks)
        valid = valid and source_identity_valid(scoped,indexes,file,producers)
        valid = valid and task_contract_valid(task)
        if task['task_type']=='school_template_parse':valid = valid and school_tasks[task['id']]['_integrity_valid']
        if task['task_type'] in ('journal_recommendation','journal_format_check','journal_adaptation'):
            try:
                from app.domain.journals.retention import validate_task
                validate_task(db,task)
            except Exception:valid=False
        for key,kind in (('parse_id','parse_versions'),('structure_id','structure_versions')):
            if key in snapshot:
                output = indexes[kind].get(snapshot[key]) if isinstance(snapshot[key], str) else None
                valid = valid and output is not None and output['task_id']==task['id']
        task['_scoped_snapshot']=scoped
        task['_integrity_valid'] = valid
        task['_public'] = task['user_id'] == user_id and task['project_id'] == project_id
        unknown |= not valid
        tasks.append(task)
    # Validate persisted output producer identities as well as snapshot consumers.
    task_ids = [task['id'] for task in tasks]
    unknown |= bool(output_tasks - set(task_ids))
    public_groups = public_source_groups(groups, indexes, tasks, file, user_id, producers, proofs)
    public_indexes = {kind: {row['id']: row for row in rows if 'id' in row}
                      for kind, rows in public_groups.items()}
    unknown |= any(len(public_groups[kind]) != len(rows) for kind, rows in groups.items())
    unknown |= any(not task['_integrity_valid'] for task in tasks)
    legacy = []
    for table, kind in (('figure_jobs', 'plot'), ('explanation_jobs', 'explanation')):
        for row in db.execute(f'SELECT j.*,r.setup_revision FROM {table} j JOIN analysis_runs r ON r.id=j.analysis_run_id WHERE r.file_id=%s', (file_id,)):
            legacy.append(dict(row, kind=kind, project_id=project_id))
    calls = [dict(row) for row in db.execute('SELECT id,task_id,status,usage_status,estimated_cost_micro_usd,actual_token_micro_usd,actual_tool_micro_usd,reconciliation_revision FROM model_calls WHERE task_id=ANY(%s)', (task_ids,))]
    reservations = [dict(row) for row in db.execute('SELECT call_id,budget_id,status,reserved_micro_usd,accounted_micro_usd FROM budget_reservations WHERE call_id=ANY(%s)', ([r['id'] for r in calls],))]
    outbox = [dict(row) for row in db.execute('SELECT id,task_id,task_revision,published_at FROM task_outbox WHERE task_id=ANY(%s)', (task_ids,))]
    checkpoints = [dict(row) for row in db.execute("SELECT id,task_id,seq,node,next_node,state_json->'candidate' AS candidate FROM task_checkpoints WHERE task_id=ANY(%s)", (task_ids,))]
    candidates = [dict(task_id=t['id'], kind='figure', identity_digest=digest(t['figure_candidate']))
                  for t in tasks if t.get('figure_candidate') is not None]
    candidates += [dict(task_id=c['task_id'], kind='checkpoint', checkpoint_id=c['id'],
                        seq=c['seq'], node=c['node'], next_node=c['next_node'], identity_digest=digest(c['candidate']))
                   for c in checkpoints if c['candidate'] is not None]
    counts = {kind: len(rows) for kind, rows in groups.items()}
    counts['school_template_sources']=len(groups['school_template_versions'])
    counts['school_template_confirmations']=sum(v['confirmation_json'] is not None for v in groups['school_template_versions'])
    counts['thesis_template_bindings']=sum(v['binding_json'] is not None for v in groups['school_template_versions'])
    counts.update(tasks=len(tasks), legacy_jobs=len(legacy),
                  active_tasks=sum(t['status'] in ACTIVE for t in tasks)+sum(mapped_status(job_data(j)) in ACTIVE for j in legacy),
                  registered_candidates=len(candidates), model_calls=len(calls), budget_reservations=len(reservations),
                  task_outbox=len(outbox), task_checkpoints=len(checkpoints))
    for table in ('task_events', 'task_attempts', 'task_waits', 'task_resume_requests'):
        counts[table] = db.execute(f'SELECT count(*) AS n FROM {table} WHERE task_id=ANY(%s)', (task_ids,)).fetchone()['n']
    counts['usage_events'] = db.execute('SELECT count(*) AS n FROM usage_events WHERE call_id=ANY(%s)', ([r['id'] for r in calls],)).fetchone()['n']
    decisions = {}
    for table in ('dataset_preparation_decisions','ocr_review_decisions','analysis_plan_decisions'):
        rows = [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE task_id=ANY(%s)',(task_ids,))]
        counts[table] = len(rows)
        decisions[table] = sorted([facts(row) for row in rows],key=digest)
    latest_checkpoints = {}
    for checkpoint in checkpoints:
        old = latest_checkpoints.get(checkpoint['task_id'])
        if old is None or old['seq'] < checkpoint['seq']:
            latest_checkpoints[checkpoint['task_id']] = checkpoint
    by_task = {t['id']: t for t in tasks}
    reasons = []
    if groups['journal_material_refs']:reasons.append('journal_history_retained')
    if groups['school_template_versions']:reasons.append('school_template_history_retained')
    if groups['manuscript_school_changes']:reasons.append('school_change_history_retained')
    if counts['active_tasks']:
        reasons.append('active_tasks')
    if any(r['status'] in ('waiting','queued','failed','blocked') for r in groups['report_build_requests']):
        reasons.append('report_build_pending')
    if unknown:
        reasons.append('integrity_unknown')
    if any(c['status'] in ('reserved', 'submitting', 'submitted', 'submission_unknown') for c in calls):
        reasons.append('external_work_unresolved')
    if any(r['status'] == 'held' for r in reservations):
        reasons.append('budget_reservations_held')
    if any(o['published_at'] is None and by_task[o['task_id']]['status'] in ACTIVE
           and o['task_revision'] == by_task[o['task_id']]['revision'] for o in outbox):
        reasons.append('outbox_pending')
    if any(by_task[c['task_id']]['status'] != 'succeeded' and
           (c['kind'] == 'figure' or c['next_node'] != 'done'
            and latest_checkpoints[c['task_id']]['id']==c['checkpoint_id']) for c in candidates):
        reasons.append('recoverable_candidates')
    if any(job_data(j).get('status') not in ('completed', 'failed', 'submitting', 'running', 'uncertain') for j in legacy):
        reasons.append('legacy_work_unknown')
    normalized = {kind: sorted([facts(row) for row in rows], key=digest) for kind, rows in groups.items()}
    normalized.update(tasks=sorted([facts(t) for t in tasks], key=digest),
                      legacy_jobs=sorted([facts(j) for j in legacy], key=digest),
                      model_calls=sorted(calls,key=digest), budget_reservations=sorted(reservations,key=digest),
                      outbox=sorted([facts(o) for o in outbox],key=digest), candidates=sorted(candidates,key=digest),
                      checkpoints=sorted([{k:v for k,v in c.items() if k!='candidate'} for c in checkpoints],key=digest))
    normalized.update(decisions)
    return dict(groups=groups, indexes=indexes, public_groups=public_groups, public_indexes=public_indexes,
                tasks=tasks, legacy=legacy, counts=counts,
                reasons=sorted(set(reasons)), facts=normalized)
