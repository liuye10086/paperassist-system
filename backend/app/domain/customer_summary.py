"""Where a customer lands on opening a project: the first matching rule.

Research rules read in one transaction; paper rules see customer_summary_paper."""

from app.adapters.research_intake_store import latest_confirmed_requirement
from app.auth.project_access import read_current_assignment
from app.domain.customer_workspace import confirmed_progress, read_published_deliveries, read_submissions


TARGET = ('delivery_id', 'snapshot_id', 'manuscript_id', 'revision', 'round_id', 'item_id', 'template_version_id', 'view', 'mode')
_PROGRESS = {
    'needs_materials': ('supplement_needed', 'customer', 'upload'),
    'materials_submitted': ('supplement_submitted', 'analyst', 'progress'),
    'delivered': ('delivery_ready', 'none', 'deliveries'),
    'pending_assignment': ('waiting_assignment', 'admin', 'progress'),
    'assigned': ('in_analysis', 'analyst', 'progress'),
    'analyzing': ('in_analysis', 'analyst', 'progress'),
}


def landing(project, kind, actor, step, updated_at, params=None, **target):
    return dict(project_id=project['id'], project_type=project['project_type'], kind=kind, actor=actor, step=step,
                target={key: target.get(key) for key in TARGET}, message_key='summary.' + kind,
                message_params=params or {}, updated_at=updated_at)


def summarize(db, project, owner_id, assets):
    if project['project_type'] in ('sci', 'thesis'):
        from app.domain.customer_summary_paper import summarize_paper
        return summarize_paper(db, project, owner_id, assets)
    if project['project_type'] != 'research':
        return landing(project, 'details', 'none', 'details', project['updated_at'])
    material_filter = assets.material_filter
    requirement = latest_confirmed_requirement(db, project['id'])
    if requirement is None:
        uploaded = db.execute('SELECT max(uploaded_at) AS at FROM files WHERE project_id=%s' + material_filter,
                              (project['id'],)).fetchone()['at']
        if uploaded is None:
            return landing(project, 'upload_needed', 'customer', 'upload', project['updated_at'])
        return landing(project, 'requirements_needed', 'customer', 'requirements', uploaded)

    progress = confirmed_progress(db, project['id'], owner_id, requirement, read_current_assignment(db, project['id']))
    rule, updated_at = _PROGRESS[progress['status']], progress['updated_at']
    if progress['status'] == 'needs_materials':
        return landing(project, *rule, updated_at, mode='supplement')
    if progress['status'] == 'materials_submitted':
        latest = read_submissions(db, project['id'], requirement)
        return landing(project, *rule, updated_at, {'count': len(latest[0]['file_ids']) if latest else 0})
    if progress['status'] == 'delivered':
        published = next(row for row in read_published_deliveries(db, project['id'], owner_id)
                         if row['requirement_version_id'] == requirement['id'])
        return landing(project, *rule, published['published_at'],
                       delivery_id=published['delivery_id'], snapshot_id=published['id'])
    return landing(project, *rule, updated_at)
