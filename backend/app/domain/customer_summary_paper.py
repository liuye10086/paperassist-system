"""Paper-project landing rules (B01 interface design, sections 1.4 and 1.5).

The summary reads in the caller's transaction where it can. ReviewRoundService and
ManuscriptService open their own connections for their checks, so a paper summary is
not a single-transaction read; it is advisory and every target page re-reads its state.
"""

from app.core.exceptions import StorageError

OPEN_ITEM_STATES = ('pending', 'waiting_confirmation', 'waiting_material')
ADOPTED_PROVENANCE = ('review_provenance', 'review_revision_provenance', 'user_return_provenance',
                      'journal_adaptation_provenance', 'school_change_provenance')
RUNNING = ('queued', 'running')
WAITING = ('waiting_confirmation', 'waiting_input')
UNKNOWN_SUBMISSION = ('submission_unknown', 'model_submission_unknown')
# Customers cannot recover these waits themselves; support or an admin has to act.
ADMIN_WAITS = ('budget_exceeded', 'model_budget_missing', 'model_budget_exceeded')


def open_review_item(assets, project_id):
    """The newest visible round, if it has not continued and still has open items."""
    from app.domain.review_rounds.service import ReviewRoundService

    service = ReviewRoundService(assets)
    with service.store.connection() as db:
        service.project(db, project_id)
        rows = db.execute('SELECT id FROM review_rounds WHERE project_id=%s AND user_id=%s ORDER BY round_number DESC',
                          (project_id, service.store.user_id)).fetchall()
        latest = next(service.visible_records(rows, lambda item: service.view(db, service.round_row(db, project_id, item['id']))), None)
    if latest is None or latest['next_round_ids']:
        return None
    items = [item for item in latest['items'] if item['status'] in OPEN_ITEM_STATES]
    if not items:
        return None
    return dict(round=latest, item=items[0], count=len(items))


def current_manuscript(assets, project_id):
    """D2: the project's most recently updated manuscript and the version the customer sees."""
    from app.domain.manuscripts.service import ManuscriptService

    service = ManuscriptService(assets)
    with service.store.connection() as db:
        root = db.execute('SELECT * FROM manuscripts WHERE project_id=%s AND user_id=%s ORDER BY updated_at DESC,id LIMIT 1',
                          (project_id, service.store.user_id)).fetchone()
        if root is None:
            return None
        try:
            version = service.version(db, project_id, root['id'], root['current_revision'])
        except StorageError as exc:
            if exc.code != 'manuscript_source_not_visible':
                raise
            version = None
        if version is None:
            # Rare: the newest version uses material this customer cannot see. Fall back to
            # the same visible version the manuscript page shows.
            visible = service.get(project_id, root['id'])['versions']
            if not visible:
                return None
            version = service.version(db, project_id, root['id'], visible[0]['revision'])
        task = service.store.require_task(db, version['task_id'])
        exports = service.export_views(db, version)
    return dict(root=root, version=version, task=task, exports=exports)


def latest_writing_task(db, version):
    """Select this version's next writing action, newest first within each landing rule."""
    return db.execute('''SELECT r.task_id, r.candidate_json IS NOT NULL AS has_candidate, r.published_revision,
            t.status, t.reason_code, t.error_code, t.updated_at
        FROM manuscript_writing_requests r JOIN tasks t ON t.id=r.task_id
        WHERE r.manuscript_id=%s AND r.base_version_id=%s AND r.user_id=%s
          AND (t.status IN ('queued','running','waiting_confirmation','waiting_input')
               OR (t.status='succeeded' AND r.candidate_json IS NOT NULL AND r.published_revision IS NULL))
        ORDER BY CASE WHEN t.status IN ('queued','running') THEN 1
                      WHEN t.status IN ('waiting_confirmation','waiting_input') AND
                           (t.reason_code='submission_unknown' OR t.error_code IN ('submission_unknown','model_submission_unknown')) THEN 2
                      WHEN t.status IN ('waiting_confirmation','waiting_input') THEN 3
                      ELSE 4 END, r.created_at DESC, r.task_id LIMIT 1''',
                      (version['manuscript_id'], version['id'], version['user_id'])).fetchone()


def is_adopted(row):
    """The version carries written text, or text derived from adopted writing."""
    from app.domain.manuscripts.service import ManuscriptService

    snapshot = row['snapshot_json']
    return ManuscriptService.is_written_version(row) or any(snapshot.get(key) for key in ADOPTED_PROVENANCE)


def word_ready(exports):
    return next((item for item in exports if item['status'] == 'succeeded'
                 and item.get('presentation', {}).get('binding', {}).get('review_mode', 'identified') == 'identified'), None)


def sci_settings_saved(db, project_id):
    row = db.execute('SELECT sci_settings_json FROM research_intakes WHERE project_id=%s', (project_id,)).fetchone()
    return bool(row and row['sci_settings_json'])


def thesis_landing(db, project, assets):
    """Thesis rules 1-3: requirements, then an adopted (bound) school template."""
    from app.domain.customer_summary import landing
    from app.domain.school_templates.service import SchoolTemplateService
    from app.domain.school_templates.thesis_requirements import bound_template

    schools = SchoolTemplateService(assets)
    stored = db.execute('SELECT school,requirements_json FROM thesis_profiles WHERE project_id=%s AND user_id=%s',
                        (project['id'], schools.store.user_id)).fetchone()
    if not stored or not stored['school'].strip() or not ((stored['requirements_json'] or {}).get('title') or '').strip():
        return landing(project, 'requirements_needed', 'customer', 'details', project['updated_at'])
    profile = schools.profile_view(db, project['id'])
    try:
        template, _ = bound_template(schools, db, project['id'], profile)
    except StorageError as exc:
        if exc.code not in ('source_conflict', 'task_source_conflict', 'manuscript_source_not_visible', 'not_found'):
            raise
        template = None
    if template is not None:
        return None
    latest = db.execute('SELECT * FROM school_template_versions WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id LIMIT 1',
                        (project['id'], schools.store.user_id)).fetchone()
    if latest and latest['analysis_json'] and not db.execute(
            'SELECT 1 FROM school_template_confirmations WHERE template_version_id=%s', (latest['id'],)).fetchone():
        # Only the newest unconfirmed version pays for the source check.
        try:
            _, task = schools.require_current(db, latest)
            if task['status'] == 'succeeded':
                count = len(latest['analysis_json']['conflicts']) + len(schools.text_options(db, latest))
                if count:
                    return landing(project, 'template_conflicts', 'customer', 'school', latest['created_at'],
                                   {'count': count}, template_version_id=latest['id'], view='confirm')
        except StorageError as exc:
            if exc.code not in ('source_conflict', 'task_source_conflict', 'manuscript_source_not_visible', 'not_found'):
                raise
    return landing(project, 'template_needed', 'customer', 'school', latest['created_at'] if latest else project['updated_at'])


def summarize_paper(db, project, owner_id, assets):
    from app.domain.customer_summary import landing

    if project['project_type'] == 'thesis':
        first = thesis_landing(db, project, assets)
        if first is not None:
            return first

    review = open_review_item(assets, project['id'])
    if review:
        rnd, item = review['round'], review['item']
        updated_at = getattr(rnd['task'], 'updated_at', None) or rnd['created_at']
        return landing(project, 'review_open', 'customer', 'reviews', updated_at,
                       {'round': rnd['round_number'], 'count': review['count']}, round_id=rnd['id'], item_id=item['id'])

    current = current_manuscript(assets, project['id'])
    if current is None:
        if project['project_type'] == 'sci' and not sci_settings_saved(db, project['id']):
            return landing(project, 'settings_needed', 'customer', 'details', project['updated_at'])
        return landing(project, 'materials_needed', 'customer', 'materials', project['updated_at'])

    version = current['version']
    revision = version['revision']
    params = {'revision': revision}

    def at(kind, actor, step, view, updated_at, extra=None):
        return landing(project, kind, actor, step, updated_at, params | (extra or {}),
                       manuscript_id=version['manuscript_id'], revision=revision, view=view)

    writing = latest_writing_task(db, version)
    if writing:
        status, reason, code = writing['status'], writing['reason_code'], writing['error_code']
        if status in RUNNING:
            return at('writing_running', 'none', 'manuscripts', 'writing', writing['updated_at'])
        if status in WAITING and (reason == 'submission_unknown' or code in UNKNOWN_SUBMISSION):
            return at('submission_unknown', 'admin', 'manuscripts', 'writing', writing['updated_at'])
        if status in WAITING:
            actor = 'admin' if reason in ADMIN_WAITS or code in ADMIN_WAITS else 'customer'
            return at('writing_waiting', actor, 'manuscripts', 'writing', writing['updated_at'], {'reason': code or reason or ''})
        if status == 'succeeded' and writing['has_candidate'] and writing['published_revision'] is None:
            return at('review_needed', 'customer', 'manuscripts', 'writing', writing['updated_at'])

    word = word_ready(current['exports'])
    if word:
        return at('word_ready', 'none', 'word', 'exports', word['created_at'])
    if is_adopted(version):
        return at('word_needed', 'customer', 'word', 'exports', version['created_at'])
    if writing is None:
        return at('writing_needed', 'customer', 'manuscripts', 'writing', version['created_at'])
    return at('writing_in_progress', 'customer', 'manuscripts', 'body', current['task']['updated_at'])
