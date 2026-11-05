"""Display-only dependency counts from persisted metadata, never deletion proofs.

No artifact bytes or service validators are read here. Deletion/reparse continue
to use references.read_references, including its full integrity checks.
"""
from app.db.schema import metadata
from .references import DIRECT, file_ids, frozen_references, nodes
from .contracts import ACTIVE
from app.domain.tasks.legacy import job_data, mapped_status


# These records carry fixed source identities or reverse producer references.
# Root/current-version pointers are deliberately not used for version resolution.
PROJECT_TABLES = (
    'tasks', 'external_evidence_versions', 'research_finding_versions',
    'research_figure_versions', 'research_report_versions', 'research_manuscript_candidates',
    'manuscript_research_sources', 'research_source_bindings', 'delivery_snapshots',
    'manuscript_versions', 'manuscript_figure_language_versions', 'manuscript_school_changes',
    'manuscript_writing_language_reviews', 'school_template_versions', 'school_rule_suggestions',
    'school_template_sources', 'journal_material_refs', 'journal_recommendations',
    'journal_format_checks', 'journal_adaptations', 'review_rounds', 'review_round_events',
    'review_revision_runs', 'review_documents', 'review_document_exports',
    'review_round_user_returns', 'review_round_continuations', 'project_review_progress_events',
    'review_opinion_task_links', 'review_analysis_adoptions', 'review_figure_adoptions', 'pdf_exports',
)
SOURCE_TABLES = {
    'original_file': 'files', 'research_finding_version': 'research_finding_versions',
    'research_figure_version': 'research_figure_versions', 'research_report_version': 'research_report_versions',
    'bio_processed_dataset_version': 'bio_processed_dataset_versions', 'bio_dataset_version': 'bio_dataset_versions',
}
FIXED_VERSION_KEYS = {
    'manuscript_version_id': 'manuscript_versions', 'base_version_id': 'manuscript_versions',
    'round_id': 'review_rounds', 'revision_id': 'review_revision_runs',
}


def read_metadata_counts(db, file, user_id):
    project, file_id = file['project_id'], file['id']
    groups = {table: [dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE file_id=%s', (file_id,))]
              for table in DIRECT.values()}
    runs = [r['id'] for r in groups['analysis_runs']]
    for table in ('figures', 'explanations', 'reports'):
        groups[table] = [dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE analysis_run_id=ANY(%s)', (runs,))]
    from .figure_report_references import read_groups as figure_groups
    from .bio_references import read_groups as bio_groups
    from .bio_analysis_references import read_groups as bio_analysis_groups
    groups.update(figure_groups(db, file, runs))
    groups.update(bio_groups(db, file, user_id))
    groups.update(bio_analysis_groups(db, file, user_id))
    selected = {table: {r['id'] for r in rows if r.get('id')} for table, rows in groups.items()}
    selected['files'] = {file_id}
    for table in PROJECT_TABLES:
        groups[table] = [dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE project_id=%s', (project,))]
        selected.setdefault(table, set())
    groups['manuscript_sources'] = [dict(r) for r in db.execute(
        'SELECT s.* FROM manuscript_sources s JOIN manuscript_versions v ON v.id=s.version_id WHERE v.project_id=%s', (project,))]
    groups['manuscript_exports'] = [dict(r) for r in db.execute(
        'SELECT e.* FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id WHERE v.project_id=%s', (project,))]
    selected.update(manuscript_sources=set(), manuscript_exports=set())

    # Normalize file->version bridge records without validating the bytes they
    # refer to. A display count conveys a saved relation, not source validity.
    for table, columns in (
        ('manuscript_sources', {'version_id': 'manuscript_versions'}),
        ('school_template_sources', {'template_version_id': 'school_template_versions'}),
        ('research_source_bindings', {'finding_version_id': 'research_finding_versions',
                                    'figure_version_id': 'research_figure_versions', 'report_version_id': 'research_report_versions'}),
    ):
        for row in groups[table]:
            if row.get('file_id') == file_id:
                for column, target in columns.items():
                    if row.get(column):selected[target].add(row[column])

    # Only fixed foreign keys participate; project/account/root keys would join
    # unrelated versions. Foreign-key definitions are taken from the schema.
    links = {}
    for table in groups:
        model = metadata.tables.get(DIRECT.get(table, table))
        links[table] = [(fk.parent.name, fk.column.table.name) for fk in model.foreign_keys
                        if fk.column.table.name in groups and fk.parent.name not in
                        ('project_id', 'user_id', 'created_by', 'manuscript_id',
                         'parent_id', 'parent_version_id', 'root_id', 'parent_export_id') ] if model is not None else []
    versions = {(r['manuscript_id'], r['revision']): r['id'] for r in groups['manuscript_versions']}
    reference_cache = {}

    def linked_json(value):
        # Only reuse extracted metadata within this call/DB snapshot. This is
        # not a reusable content/integrity proof and never touches file bytes.
        key = id(value)
        if key not in reference_cache:
            refs = {('files', identifier) for identifier in file_ids(value)}
            try:
                refs.update((DIRECT.get(kind, kind), identifier) for kind, identifier in frozen_references(value))
            except (KeyError, TypeError, ValueError):
                pass  # Malformed identities are handled conservatively below.
            for node in nodes(value):
                source_kind = node.get('source_kind')
                kind = SOURCE_TABLES.get(source_kind) if isinstance(source_kind, str) else None
                identifier = node.get('source_id')
                if kind and isinstance(identifier, str):refs.add((kind, identifier))
                for field, target in FIXED_VERSION_KEYS.items():
                    identifier = node.get(field)
                    if isinstance(identifier, str):refs.add((target, identifier))
                manuscript = node.get('manuscript')
                if isinstance(manuscript, dict) and isinstance(manuscript.get('version_id'), str):
                    refs.add(('manuscript_versions', manuscript['version_id']))
                root = node.get('manuscript_id');revision = node.get('revision', node.get('base_revision'))
                if isinstance(root, str) and type(revision) is int:
                    version_id = versions.get((root, revision))
                    if version_id:refs.add(('manuscript_versions', version_id))
            reference_cache[key] = refs
        return any(identifier in selected.get(kind, set()) for kind, identifier in reference_cache[key])

    # Closure over persisted relationships; each iteration adds an ID, so cycles
    # in historical metadata terminate without recursive service calls.
    changed = True
    while changed:
        changed = False
        for table, rows in groups.items():
            selected.setdefault(table, set())
            for row in rows:
                identifier = row.get('id')
                if not identifier or identifier in selected[table]:continue
                linked = any(isinstance(row.get(key), str) and row[key] in selected.get(target, set()) for key, target in links[table])
                if not linked:linked = linked_json(row)
                if linked:
                    selected[table].add(identifier);changed = True
                    # Reverse producer links are part of the saved dependency.
                    if row.get('task_id'):selected['tasks'].add(row['task_id'])
                    if table == 'review_round_events':selected['review_rounds'].add(row['round_id'])

    # Keep the conservative unknown-source count. It does not grant permission
    # to delete or assert that a corrupted dependency belongs to this file.
    project_files = {r['id'] for r in db.execute('SELECT id FROM files WHERE project_id=%s', (project,))}
    known_producers = {r['task_id'] for rows in groups.values() for r in rows if r.get('task_id')}
    specialized = {'bio_import', 'bio_analysis', 'bio_figure', 'research_figure', 'research_report', 'research_fact_draft', 'delivery_package'}
    for task in groups['tasks']:
        if task['id'] in selected['tasks'] or task['task_type'] in specialized:continue
        snapshot = task['input_snapshot'];ids = file_ids(snapshot)
        try:
            refs = list(frozen_references(snapshot));malformed = False
        except (KeyError, TypeError, ValueError):
            refs = [];malformed = True
        # Typed manuscript/review tasks resolve through fixed metadata above.
        typed = task['task_type'] in {'manuscript_draft', 'manuscript_docx', 'manuscript_writing', 'review_round_plan', 'review_revision', 'review_document_export', 'pdf_export'}
        if malformed or not ids <= project_files or (not ids and not refs and (not typed or task['id'] not in known_producers)):
            selected['tasks'].add(task['id'])
    tasks = db.execute('SELECT id,status FROM tasks WHERE id=ANY(%s)', (list(selected['tasks']),)).fetchall()
    legacy = []
    for table, kind in (('figure_jobs', 'plot'), ('explanation_jobs', 'explanation')):
        legacy.extend(dict(r, kind=kind, project_id=project) for r in db.execute(
            'SELECT j.*,r.setup_revision FROM '+table+' j JOIN analysis_runs r ON r.id=j.analysis_run_id WHERE r.file_id=%s', (file_id,)))
    return dict(tasks=len(tasks), active_tasks=sum(t['status'] in ACTIVE for t in tasks)+sum(mapped_status(job_data(j)) in ACTIVE for j in legacy),
        external_evidence_versions=db.execute('SELECT count(*) AS n FROM external_evidence_versions WHERE file_id=%s', (file_id,)).fetchone()['n'],
        prepared_dataset_derivations_v3=db.execute('SELECT count(*) AS n FROM prepared_dataset_derivations_v3 d JOIN prepared_dataset_versions v ON v.id=d.prepared_dataset_id WHERE v.file_id=%s', (file_id,)).fetchone()['n'])
