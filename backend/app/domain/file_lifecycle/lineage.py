"""Safe lifecycle-only source projections; historical tasks stay executable."""
from app.domain.file_lifecycle.references import frozen_references
from app.domain.tasks.legacy import public_legacy_task


def task_sources(task, references):
    if not task['_integrity_valid']:
        return []
    indexes = references['public_indexes']
    refs = set(frozen_references(task['input_snapshot']))
    for kind in ('parse_versions', 'structure_versions', 'prepared_dataset_versions', 'ocr_review_versions', 'confirmed_plans'):
        refs.update((kind, row['id']) for row in references['public_groups'][kind] if row.get('task_id') == task['id'])
    result = []
    for kind, identifier in sorted(refs):
        row = indexes[kind].get(identifier)
        if row is None:
            continue  # Never publish an unvalidated foreign/missing identity.
        entry = dict(kind=kind, id=identifier, version=row.get('version', row.get('setup_revision')))
        if 'sheet_index' in row:
            entry['sheet_index'] = row['sheet_index']
        result.append(entry)
    return result


def newer_source(source, references):
    kind = source['kind']
    row = references['public_indexes'][kind][source['id']]
    version = source['version']
    if version is None:
        return None
    candidates = references['public_groups'][kind]
    tasks = {task['id']: task for task in references['tasks']}
    newer = []
    for other in candidates:
        if other.get('version', other.get('setup_revision', 0)) <= version:
            continue
        if kind == 'dataset_versions' and other['sheet_index'] != row['sheet_index']:
            continue
        if kind == 'prepared_dataset_versions' and other['parent_dataset_id'] != row['parent_dataset_id']:
            continue
        if kind == 'ocr_review_versions' and other['parent_parse_id'] != row['parent_parse_id']:
            continue
        if kind == 'parse_versions':
            old_task, new_task = tasks.get(row['task_id']), tasks.get(other['task_id'])
            if not old_task or not new_task:
                continue
            old, new = old_task['input_snapshot'], new_task['input_snapshot']
            if old.get('kind') != new.get('kind') or old.get('page_numbers') != new.get('page_numbers'):
                continue
        newer.append(other)
    if not newer:
        return None
    # A newer task attempt is distinct from a successfully published equivalent
    # source. Neither state says an older immutable asset is invalid or lost.
    def published(item):
        if kind == 'parse_versions':
            return item.get('result_json') is not None and tasks.get(item['task_id'], {}).get('status') == 'succeeded'
        if kind == 'structure_versions':
            return item.get('manifest_json') is not None and tasks.get(item['task_id'], {}).get('status') == 'succeeded'
        return True
    return 'newer_published_version' if any(published(item) for item in newer) else 'newer_attempt_available'


def task_views(references):
    views = []
    for task in references['tasks']:
        if not task['_public']:
            continue
        sources = task_sources(task, references)
        reasons = sorted({reason for source in sources if (reason := newer_source(source, references))})
        status = ('integrity_unknown' if not task['_integrity_valid'] else
                  'newer_published_version' if 'newer_published_version' in reasons else
                  'newer_attempt_available' if reasons else 'frozen_source')
        views.append(dict(id=task['id'], origin='task', task_type=task['task_type'], status=task['status'],
                          created_at=task['created_at'].isoformat(), sources=sources,
                          has_newer_version=bool(reasons), source_status=status, stale_reasons=reasons))
    for row in references['legacy']:
        task = public_legacy_task(row)
        valid = row['analysis_run_id'] in references['public_indexes']['analysis_runs']
        views.append(dict(id=task['id'], origin='legacy', task_type=task['task_type'], status=task['status'],
                          created_at=task['created_at'], sources=[dict(kind='analysis_runs', id=row['analysis_run_id'],
                          version=row['setup_revision'])] if valid else [], has_newer_version=False,
                          source_status='frozen_source' if valid else 'integrity_unknown', stale_reasons=[]))
    # Stable created DESC / id ASC, including legacy rows with textual timestamps.
    from datetime import datetime
    views.sort(key=lambda item: item['id'])
    views.sort(key=lambda item: datetime.fromisoformat(item['created_at'].replace('Z','+00:00')), reverse=True)
    return views
