"""Retain configured figures, report versions and pending local build intents.

All reads share the lifecycle transaction. No current pointer replaces a saved
version, and no physical asset is removed or historical receipt rewritten.
"""

TABLES = ('figure_configurations','figure_config_versions','figure_projection_decisions','figure_projection_results',
          'report_collections','report_collection_versions','report_collection_items','report_build_requests','collection_reports')


def read_groups(db, file, run_ids):
    from app.domain.file_lifecycle.references import file_ids
    groups={name:[] for name in TABLES}
    groups['figure_configurations']=[dict(r) for r in db.execute(
        'SELECT * FROM figure_configurations WHERE analysis_run_id=ANY(%s)', (run_ids,))]
    config_ids=[r['id'] for r in groups['figure_configurations']]
    groups['figure_config_versions']=[dict(r) for r in db.execute(
        'SELECT * FROM figure_config_versions WHERE configuration_id=ANY(%s)', (config_ids,))]
    version_ids=[r['id'] for r in groups['figure_config_versions']]
    for name in ('figure_projection_decisions','figure_projection_results'):
        groups[name]=[dict(r) for r in db.execute(f'SELECT * FROM {name} WHERE config_version_id=ANY(%s)',(version_ids,))]
    # Include reverse item FKs even if a corrupted collection claims another
    # project. Scope validation below withholds those rows from public lineage.
    versions=db.execute('''SELECT DISTINCT v.* FROM report_collection_versions v
        JOIN report_collections c ON c.id=v.collection_id LEFT JOIN report_collection_items i ON i.version_id=v.id
        WHERE c.project_id=%s OR i.analysis_run_id=ANY(%s) OR i.figure_config_version_id=ANY(%s)''',
        (file['project_id'],run_ids,version_ids)).fetchall()
    for row in versions:
        items=[dict(r) for r in db.execute('SELECT * FROM report_collection_items WHERE version_id=%s',(row['id'],))]
        linked=(file['id'] in file_ids(row['source_json']) or file['id'] in file_ids(row['content_json'])
                or any(i['analysis_run_id'] in run_ids or i.get('figure_config_version_id') in version_ids for i in items))
        if linked:
            groups['report_collection_versions'].append(dict(row))
            groups['report_collection_items'].extend(items)
    collection_ids=list({r['collection_id'] for r in groups['report_collection_versions']})
    groups['report_collections']=[dict(r) for r in db.execute('SELECT * FROM report_collections WHERE id=ANY(%s)',(collection_ids,))]
    collection_versions=[r['id'] for r in groups['report_collection_versions']]
    for name in ('report_build_requests','collection_reports'):
        groups[name]=[dict(r) for r in db.execute(f'SELECT * FROM {name} WHERE version_id=ANY(%s)',(collection_versions,))]
    return groups


def parent_links(kind,row):
    links=[]
    for column,target in (
            ('configuration_id','figure_configurations'),('config_version_id','figure_config_versions'),
            ('figure_config_version_id','figure_config_versions'),('parent_version_id','figure_config_versions'),
            ('collection_id','report_collections'),('build_request_id','report_build_requests')):
        if row.get(column): links.append((target,row[column]))
    if kind in ('report_collection_items','report_build_requests','collection_reports'):
        links.append(('report_collection_versions',row['version_id']))
    if kind=='figure_projection_results' and row.get('decision_id'):
        links.append(('figure_projection_decisions',row['decision_id']))
    return links
