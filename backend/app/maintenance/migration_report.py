"""Privacy preserving verification of original columns and relational provenance."""

from app.maintenance.legacy_import import TABLE_COLUMNS, JOB_TABLES, _digest, _inventory


def build_import_verification(snapshot, target_rows):
    tables, identities, sequences = {}, {}, {}
    for table, columns in TABLE_COLUMNS.items():
        source, target = snapshot.rows[table], target_rows[table]
        source_hash, target_hash = _digest(source), _digest(target)
        tables[table] = {'source_count': len(source), 'target_count': len(target),
                         'source_sha256': source_hash, 'target_sha256': target_hash,
                         'matches': len(source) == len(target) and source_hash == target_hash}
        indexed = {row[columns[0]]: row for row in target}
        identities[table] = [{'source_id': row[columns[0]],
                              'target_id': row[columns[0]] if row[columns[0]] in indexed else None,
                              'matches': row[columns[0]] in indexed} for row in source]
        if table in JOB_TABLES:
            sequences[table] = [{'id': row['id'], 'source_rowid': row['seq'],
                                 'target_seq': indexed.get(row['id'], {}).get('seq'),
                                 'matches': indexed.get(row['id'], {}).get('seq') == row['seq']} for row in source]
    indexes = {table: {row[columns[0]]: row for row in target_rows[table]}
               for table, columns in TABLE_COLUMNS.items()}
    relationships = {}

    def edge(name, table, predicate):
        rows = target_rows[table]
        valid = sum(bool(predicate(row)) for row in rows)
        relationships[name] = {'checked': len(rows), 'valid': valid, 'matches': valid == len(rows)}

    for name, table, column, parent in [
        ('files_project', 'files', 'project_id', 'projects'),
        ('setups_file', 'analysis_setups', 'file_id', 'files'),
        ('runs_file', 'analysis_runs', 'file_id', 'files'),
        ('figures_run', 'figures', 'analysis_run_id', 'analysis_runs'),
        ('figure_jobs_run', 'figure_jobs', 'analysis_run_id', 'analysis_runs'),
        ('explanations_run', 'explanations', 'analysis_run_id', 'analysis_runs'),
        ('explanation_jobs_run', 'explanation_jobs', 'analysis_run_id', 'analysis_runs'),
        ('reports_run', 'reports', 'analysis_run_id', 'analysis_runs'),
    ]:
        edge(name, table, lambda row, c=column, p=parent: row[c] in indexes[p])
    for table in ('explanations', 'explanation_jobs'):
        edge(table + '_figure_run', table, lambda row: row['figure_id'] in indexes['figures']
             and indexes['figures'][row['figure_id']]['analysis_run_id'] == row['analysis_run_id'])
    edge('reports_explanation_run', 'reports', lambda row: row['explanation_id'] in indexes['explanations']
         and indexes['explanations'][row['explanation_id']]['analysis_run_id'] == row['analysis_run_id'])
    actual_assets = _inventory(snapshot.data_directory)
    assets = {relative: {'expected': snapshot.assets.get(relative), 'actual': actual_assets.get(relative),
                         'exists': relative in actual_assets,
                         'matches': snapshot.assets.get(relative) == actual_assets.get(relative)}
              for relative in sorted(snapshot.assets.keys() | actual_assets.keys())}
    return {'matches': all(item['matches'] for group in (tables, relationships, assets) for item in group.values()),
            'tables': tables, 'identity_mappings': identities, 'job_sequence_mappings': sequences,
            'relationships': relationships, 'assets': assets,
            'scope': {'verified': 'original column values and JSON syntax; relational fields and cross-run references; asset bytes and SHA-256',
                      'not_verified': 'unknown JSON business semantics',
                      'historical_setup_revisions': 'preserved; no latest-revision or setup-existence requirement'}}
