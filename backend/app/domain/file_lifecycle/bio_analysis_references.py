"""File retention through normalized B02 roots, versions and evidence."""
from app.db.bio_analysis_schema import TABLE_NAMES


def read_groups(db,file,user_id):
    raw=[r['dataset_version_id'] for r in db.execute('SELECT DISTINCT dataset_version_id FROM bio_dataset_members WHERE source_file_id=%s',(file['id'],))]
    # Cell label evidence retains the same immutable recipe and its downstream
    # roots even when the evidence file is not an expression-matrix original.
    for row in db.execute("SELECT raw_dataset_version_id FROM bio_analysis_recipe_versions WHERE project_id=%s AND recipe_code='single_cell_explore_v1' AND params_json->'cell_labels' @> %s::jsonb",(file['project_id'],__import__('json').dumps([{'evidence_file_ids':[file['id']]}]))):
        if row['raw_dataset_version_id'] not in raw:raw.append(row['raw_dataset_version_id'])
    groups={}
    for table in ('bio_observation_map_sets','bio_observation_map_versions','bio_analysis_setups','bio_analysis_recipe_versions','bio_analysis_runs','bio_processed_dataset_versions','bio_annotation_sets','bio_annotation_versions'):
        extra=' OR table_source_file_id=%s' if table=='bio_observation_map_versions' else ''
        params=(raw,file['id']) if extra else (raw,)
        groups[table]=[dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE raw_dataset_version_id=ANY(%s)'+extra,params)]
    processed=[r['id'] for r in groups['bio_processed_dataset_versions']]
    annotations=[r['id'] for r in groups['bio_annotation_versions']]
    groups['bio_analysis_artifacts']=[dict(r) for r in db.execute('SELECT * FROM bio_analysis_artifacts WHERE processed_dataset_version_id=ANY(%s)',(processed,))]
    groups['bio_annotation_evidence']=[dict(r) for r in db.execute('SELECT * FROM bio_annotation_evidence WHERE annotation_version_id=ANY(%s) OR file_id=%s',(annotations,file['id']))]
    groups['bio_figure_versions']=[dict(r) for r in db.execute('SELECT * FROM bio_figure_versions WHERE processed_dataset_version_id=ANY(%s)',(processed,))]
    groups['bio_figure_members']=[dict(r) for r in db.execute('SELECT * FROM bio_figure_members WHERE figure_version_id=ANY(%s)',([r['id'] for r in groups['bio_figure_versions']],))]
    project=db.execute('SELECT owner_id FROM projects WHERE id=%s',(file['project_id'],)).fetchone()
    for rows in groups.values():
        for row in rows:row['_integrity_valid']=bool(project and project['owner_id']==user_id and row['created_by']==user_id and row['project_id']==file['project_id'])
    return groups
