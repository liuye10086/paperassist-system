"""Track uploaded originals through customer figure creation and revision."""
from collections import defaultdict

from app.adapters.project_images import IMAGE_MEDIA_TYPES
from app.adapters.research_results_store import invalid
from app.core.exceptions import StorageError


def _active_versions(db, project_id, owner_id, entrypoint):
    return db.execute('''WITH versions AS (
        SELECT v.root_id, v.revision, v.config_json, v.created_at, v.id, t.status,
            max(v.revision) OVER versions_by_root AS latest_revision,
            max(v.revision) FILTER (WHERE t.status='succeeded') OVER versions_by_root AS completed_revision
        FROM research_figure_versions v
        JOIN tasks t ON (t.id, t.project_id, t.user_id) = (v.task_id, v.project_id, v.user_id)
        WHERE v.project_id=%s AND v.user_id=%s AND t.task_type='research_figure'
            AND t.input_snapshot->>'entrypoint'=%s
            AND NOT EXISTS (SELECT 1 FROM paper_figure_cancellations c WHERE c.root_id=v.root_id)
        WINDOW versions_by_root AS (PARTITION BY v.root_id)
    ) SELECT * FROM versions WHERE revision=completed_revision OR status IN ('queued', 'running')
      ORDER BY created_at DESC, id''', (project_id, owner_id, entrypoint)).fetchall()


def _original_ids(version):
    return [panel['source']['source_id'] for panel in version['config_json']['panels']]


def assembly_cancelled(db, root_id):
    return db.execute('SELECT 1 FROM paper_figure_cancellations WHERE root_id=%s', (root_id,)).fetchone() is not None


def require_available_originals(db, project_id, owner_id, entrypoint, file_ids, root_id):
    """Check reservations in the same serialized transaction as creation or retry."""
    if root_id is not None and assembly_cancelled(db, root_id):
        raise StorageError('paper_figure_assembly_cancelled', '这张正图已取消拼版，请选择原图重新拼版。', 409)
    own = set()
    used = set()
    for version in _active_versions(db, project_id, owner_id, entrypoint):
        if version['root_id'] == root_id:
            if version['status'] != 'succeeded':
                raise invalid('research_revision_conflict')
            own.update(_original_ids(version))
        else:
            used.update(_original_ids(version))
    # Existing overlapping groups can retain their own panels when edited.
    conflicts = [file_id for file_id in file_ids if file_id in used and file_id not in own]
    if conflicts:
        raise StorageError('paper_figure_original_in_use', '所选原图已用于其他正图或正在拼版，请重新选择。',
                           409, params={'file_ids': conflicts})


def _group(versions, originals):
    completed = next((row for row in versions if row['status'] == 'succeeded'), None)
    running = [row for row in versions if row['status'] != 'succeeded']
    current = None
    if completed:
        config = completed['config_json']
        current = dict(revision=completed['revision'], title=config['title'], columns=config['columns'],
                       originals=[originals.get(file_id, {'id': file_id}) for file_id in _original_ids(completed)])
    pending_files = dict.fromkeys(file_id for row in running for file_id in _original_ids(row))
    return dict(root_id=versions[0]['root_id'], latest_revision=versions[0]['latest_revision'], current=current,
                pending_title=running[0]['config_json']['title'] if running else None,
                pending_originals=[originals.get(file_id, {'id': file_id}) for file_id in pending_files])


def assembly_library(db, assets, project_id, entrypoint, page, group_page, page_size):
    rows = _active_versions(db, project_id, assets.owner_id, entrypoint)
    groups = defaultdict(list)
    used = set()
    for row in rows:
        groups[row['root_id']].append(row)
        used.update(_original_ids(row))
    group_offset = (group_page - 1) * page_size
    grouped_page = list(groups.values())[group_offset:group_offset + page_size]
    group_files = {file_id for group in grouped_page for version in group for file_id in _original_ids(version)}

    fields = 'SELECT id, filename, file_type FROM files'
    scope = ' WHERE project_id=%s AND file_type=ANY(%s)' + assets.material_filter
    visible = (project_id, list(IMAGE_MEDIA_TYPES))
    originals = {row['id']: dict(row) for row in db.execute(fields + scope + ' AND id=ANY(%s)', (*visible, list(group_files)))}
    unused_scope = scope + ' AND id<>ALL(%s)'
    unused = (*visible, list(used))
    total = db.execute('SELECT count(*) AS total FROM files' + unused_scope, unused).fetchone()['total']
    available = db.execute(fields + unused_scope + ' ORDER BY uploaded_at DESC, id LIMIT %s OFFSET %s',
                           (*unused, page_size, (page - 1) * page_size)).fetchall()
    return dict(available=dict(items=[dict(row) for row in available], total=total, page=page, page_size=page_size),
                groups=dict(items=[_group(group, originals) for group in grouped_page], total=len(groups),
                            page=group_page, page_size=page_size),
                has_pending=any(row['status'] != 'succeeded' for row in rows))
