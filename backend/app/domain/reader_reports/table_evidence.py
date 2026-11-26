"""Project scientific evidence from verified native tables and source metadata."""

import csv
import io
import json
from itertools import islice


MAX_BULK_EXAMPLES = 12
MAX_TRAJECTORY_ROWS = 24


def _rows(entry):
    table, raw = entry
    delimiter = '\t' if table['format'] == 'tsv' else ','
    return csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter=delimiter)


def _input_counts(tables, version, features):
    counts = next((entry for entry in tables if entry[0]['key'] == 'model_counts'
                   and entry[0]['source'].get('result_version_id') == version), None)
    if counts is None or not features:
        return {}
    rows = _rows(counts)
    if 'model_id' not in rows.fieldnames:
        return {}
    totals = {}
    for row in rows:
        feature = row['feature_id']
        if feature not in features:
            continue
        values = [value for column, value in row.items() if column not in ('model_id', 'feature_id')]
        if not values or not all(values):
            continue
        try:
            totals[feature] = sum(map(int, values))
        except ValueError:
            continue
        if totals.keys() == features:
            break
    return totals


def _bulk_testing_limits(scientific, tables):
    selected = {contrast['contrast_id'] for contrast in scientific.get('summary', {}).get('contrasts', [])}
    comparison = next((entry for entry in tables if entry[0]['key'] == 'comparison_results'), None)
    if comparison is None or not selected:
        return []
    rows = (row for row in _rows(comparison) if row['contrast_id'] in selected and row.get('reason'))
    examples = [dict(contrast=row['contrast_id'], feature=row['feature_id'], status=row['test_status'], reason=row['reason'])
                for row in islice(rows, MAX_BULK_EXAMPLES)]
    needed = {row['feature'] for row in examples if row['reason'] == 'minimum_total_counts'}
    version = comparison[0]['source'].get('result_version_id')
    totals = _input_counts(tables, version, needed)
    for row in examples:
        if row['reason'] == 'minimum_total_counts' and row['feature'] in totals:
            row['model_input_total_count'] = totals[row['feature']]
            row['model_input_count_scope'] = 'model_cohort'
    return examples


def _trajectory(tables):
    trajectory = next((entry for entry in tables if entry[0]['key'] == 'trajectory_results'), None)
    if trajectory is None:
        return {}
    count = trajectory[0]['expected_rows']
    evidence = {'row_count': count}
    if count <= MAX_TRAJECTORY_ROWS:
        evidence['rows'] = [dict(cluster=row['cluster'], lineage=row['lineage_id'],
                                 pseudotime=row['pseudotime'] or None, weight=row['weight'] or None,
                                 covered=row['covered'].lower() == 'true') for row in _rows(trajectory)]
    units = next((entry for entry in tables if entry[0]['key'] == 'topic_units'
                  and entry[0]['source'].get('result_version_id') == trajectory[0]['source'].get('result_version_id')), None)
    if units is not None:
        samples = {sample for row in _rows(units) for sample in json.loads(row['samples']) if sample}
        if samples:
            evidence['known_selected_sample_count'] = len(samples)
    return evidence


def _native_science(snapshot):
    sources = snapshot.get('finding', {}).get('content', {}).get('sources', [])
    if len(sources) != 1 or sources[0]['source_kind'] != 'bio_report_context':
        return {}
    return sources[0]['content']


def trajectory_import_counts(assets, db, project, snapshot):
    """Read aggregate input dimensions after the report freeze has checked its source lineage."""
    scientific = _native_science(snapshot)
    if scientific.get('assay') != 'slingshot':
        return {}
    processed_id = scientific['study_design'].get('processed_source_id')
    if not processed_id:
        return {}

    from app.adapters.bio_analysis_store import BioAnalysisStore

    store = BioAnalysisStore(assets)
    _, processed, _ = store.processed_record(db, project, processed_id, verify_raw_bytes=False)
    raw = processed.get('raw_source') or processed['identity']['raw_source']
    _, manifest = store.raw_store.require_version(db, project, raw['dataset_id'], raw['dataset_version_id'])
    if manifest['assay'] != 'single_cell':
        return {}
    counts = {'feature_count': manifest['input_shape']['features']}
    if manifest.get('samples'):
        counts['library_count'] = len(manifest['samples'])
    return counts


def project_table_evidence(snapshot, table_raws, *, trajectory_import=None):
    scientific = _native_science(snapshot)
    if not scientific:
        return {}
    tables = [(table, raw) for table, raw in zip(snapshot['tables'], table_raws, strict=True)
              if table['source'].get('source_kind') == 'bio_insight_result_member']
    if scientific.get('assay') == 'bulk_rna_counts':
        limits = _bulk_testing_limits(scientific, tables)
        return {'bulk_testing_limits': limits} if limits else {}
    if scientific.get('assay') == 'slingshot':
        trajectory = _trajectory(tables)
        if trajectory_import:
            trajectory['source_import'] = trajectory_import
        return {'trajectory': trajectory} if trajectory else {}
    return {}
