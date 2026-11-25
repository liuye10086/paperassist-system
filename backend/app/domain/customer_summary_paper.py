"""Choose a customer paper project step from saved requirements, materials and drafts."""

from app.core.exceptions import StorageError
from app.domain.research_intake.sci_templates import selected_template


def sci_settings_for_landing(db, project_id):
    row = db.execute('SELECT sci_settings_json FROM research_intakes WHERE project_id=%s', (project_id,)).fetchone()
    return (row['sci_settings_json'] if row else None) or {}


def saved_thesis_target(db, project_id, owner_id, assets):
    """With no active draft request, open the last visible adopted body or existing Word."""
    from app.domain.manuscripts.service import ManuscriptService
    from app.domain.manuscripts.sources import require_visible_snapshot

    active = db.execute("""SELECT 1 FROM manuscript_writing_requests r JOIN tasks t ON t.id=r.task_id
        WHERE r.project_id=%s AND r.user_id=%s AND r.published_revision IS NULL
        AND r.request_json->>'mode'='full_draft' AND t.status NOT IN ('failed','cancelled') LIMIT 1""",
        (project_id, owner_id)).fetchone()
    if active:
        return {}
    versions = db.execute("""SELECT v.manuscript_id,v.revision,v.parent_version_id,v.snapshot_json,
        EXISTS(SELECT 1 FROM manuscript_exports e JOIN tasks et ON et.id=e.task_id
               WHERE e.version_id=v.id AND et.status='succeeded') AS has_word
        FROM manuscript_versions v JOIN tasks t ON t.id=v.task_id
        WHERE v.project_id=%s AND v.user_id=%s AND t.status='succeeded' ORDER BY v.created_at DESC,v.id""",
        (project_id, owner_id))
    derived = ('review_provenance','review_revision_provenance','user_return_provenance',
               'journal_adaptation_provenance','school_change_provenance')
    for version in versions:
        snapshot = version['snapshot_json']
        if not (version['has_word'] or ManuscriptService.is_written_version(version) or any(snapshot.get(k) for k in derived)):
            continue
        try:
            require_visible_snapshot(assets, db, project_id, snapshot)
        except StorageError as exc:
            if exc.code != 'manuscript_source_not_visible':
                raise
            continue
        return dict(manuscript_id=version['manuscript_id'], revision=version['revision'], view='saved')
    return {}


def thesis_template_landing(db, project, assets):
    """Open the newest visible template when the project still needs a binding."""
    from app.domain.customer_summary import landing
    from app.domain.school_templates.service import SchoolTemplateService
    from app.domain.school_templates.thesis_requirements import bound_template

    schools = SchoolTemplateService(assets)
    profile = schools.profile_view(db, project['id'])
    try:
        template, _ = bound_template(schools, db, project['id'], profile)
    except StorageError as exc:
        if exc.code not in ('source_conflict', 'task_source_conflict', 'manuscript_source_not_visible', 'not_found'):
            raise
        template = None
    if template is not None:
        return None
    versions = db.execute('''SELECT v.*, c.id AS confirmation_id
        FROM school_template_versions v LEFT JOIN school_template_confirmations c ON c.template_version_id=v.id
        WHERE v.project_id=%s AND v.user_id=%s ORDER BY v.created_at DESC,v.id''', (project['id'], schools.store.user_id))
    for latest in versions:
        try:
            _, task = schools.require_current(db, latest)
            if task['status'] == 'succeeded' and latest['analysis_json'] and not latest['confirmation_id']:
                count = len(latest['analysis_json']['conflicts']) + len(schools.text_options(db, latest))
                if count:
                    return landing(project, 'template_conflicts', 'customer', 'school', latest['created_at'],
                                   {'count': count}, template_version_id=latest['id'], view='detail')
            return landing(project, 'template_needed', 'customer', 'school', latest['created_at'],
                           template_version_id=latest['id'], view='detail')
        except StorageError as exc:
            if exc.code not in ('source_conflict', 'task_source_conflict', 'manuscript_source_not_visible', 'not_found'):
                raise
    return landing(project, 'template_needed', 'customer', 'school', project['updated_at'], view='upload')


def summarize_paper(db, project, owner_id, assets):
    from app.domain.customer_summary import landing

    thesis = project['project_type'] == 'thesis'
    started = db.execute('SELECT 1 FROM manuscripts WHERE project_id=%s AND user_id=%s LIMIT 1',
                         (project['id'], owner_id)).fetchone()
    if thesis:
        if started:
            target = saved_thesis_target(db, project['id'], owner_id, assets)
            return landing(project, 'continue_writing', 'customer', 'manuscripts', project['updated_at'], **target)
        stored = db.execute('SELECT school,requirements_json FROM thesis_profiles WHERE project_id=%s AND user_id=%s',
                            (project['id'], owner_id)).fetchone()
        if not stored or not stored['school'].strip() or not ((stored['requirements_json'] or {}).get('title') or '').strip():
            return landing(project, 'requirements_needed', 'customer', 'details', project['updated_at'])
    elif not (sci := sci_settings_for_landing(db, project['id'])):
        return landing(project, 'settings_needed', 'customer', 'details', project['updated_at'])

    # A template or a supplementary school guideline alone is not project research material.
    exclude_templates = ''' AND NOT EXISTS (
        SELECT 1 FROM school_template_sources s WHERE s.project_id=files.project_id
        AND s.file_id=files.id AND s.role IN ('template','supplement'))''' if thesis else ''
    uploaded = db.execute('SELECT 1 FROM files WHERE project_id=%s' + assets.material_filter
                          + exclude_templates + ' LIMIT 1', (project['id'],)).fetchone()
    if not uploaded and not started:
        return landing(project, 'materials_needed', 'customer', 'materials', project['updated_at'])
    if thesis:
        school_step = thesis_template_landing(db, project, assets)
        if school_step:
            return school_step
    elif not started and selected_template(sci.get('article_type'), sci.get('template_id')) is None:
        return landing(project, 'sci_template_needed', 'customer', 'sci-template', project['updated_at'])
    return landing(project, 'continue_writing', 'customer', 'manuscripts', project['updated_at'])
