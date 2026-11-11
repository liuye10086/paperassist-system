"""Compare classifications on the complete saved gene tables of fixed Bulk results."""
from collections import Counter
import csv

from app.adapters.bio_analysis_store import BioAnalysisStore
from app.adapters.bio_insights_store import invalid

from .bulk_results import BULK_DIRECTIONS, bulk_contrast_labels, bulk_row_class, finite_metric, is_reviewed_bulk
from .results import checked_members


_GENE_FIELDS = ('feature_id', 'symbol', 'baseline_class', 'scenario_class', 'change',
                'baseline_q', 'scenario_q', 'baseline_effect', 'scenario_effect')
_TABLE_COLUMNS = frozenset((
    'row_key', 'feature_id', 'symbol', 'contrast_id', 'numerator', 'denominator', 'tested',
    'test_status', 'effect_value', 'q_within_contrast', 'q_global_family', 'original_method_adjustment',
))
_CHANGE_CLASSES = ('stable_up', 'stable_down', 'changed_direction', 'gained', 'lost', 'unchanged', 'ineligible')
_INELIGIBLE = frozenset(('excluded', 'not_computable', 'missing_metric', 'absent'))
_MODEL_PARAMETERS = (
    'design', 'method', 'analysis_layer', 'inference_unit', 'inference_goal', 'data_driven_grouping',
    'pairing_field', 'batch_adjustment', 'condition_reference', 'covariates', 'minimum_total_counts',
    'minimum_sample_counts', 'size_factor_method', 'family_contrast_ids',
)


def _fixed_gene_rows(path, selections, labels):
    by_contrast = {selection.contrast_id for selection in selections}
    tables = [{} for _ in selections]
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t', strict=True)
        columns = reader.fieldnames or []
        if not _TABLE_COLUMNS.issubset(columns) or len(columns) != len(set(columns)):
            raise ValueError('bulk_comparison_columns_invalid')
        for row in reader:
            if row['contrast_id'] not in by_contrast:
                continue
            if (None in row or None in row.values() or not row['feature_id'] or not row['row_key']
                    or (row['numerator'], row['denominator']) != labels
                    or row['test_status'] not in ('tested', 'excluded', 'not_computable')):
                raise ValueError('bulk_comparison_row_invalid')
            for selection, table in zip(selections, tables):
                if row['contrast_id'] != selection.contrast_id:
                    continue
                feature_id = row['feature_id']
                if feature_id in table:
                    raise ValueError('bulk_comparison_row_invalid')
                category = bulk_row_class(row, selection)
                if category in BULK_DIRECTIONS and selection.direction not in ('both', category):
                    category = 'direction_not_selected'
                q = finite_metric(row[selection.q_column])
                q = q if q is not None and 0 <= q <= 1 else None
                table[feature_id] = (category, q, finite_metric(row['effect_value']), row['symbol'])
    if not all(tables):
        raise ValueError('bulk_comparison_rows_missing')
    return tables


def _change(before, after):
    if before in _INELIGIBLE or after in _INELIGIBLE:
        return 'ineligible'
    if before in BULK_DIRECTIONS and after in BULK_DIRECTIONS:
        return 'stable_' + before if before == after else 'changed_direction'
    if after in BULK_DIRECTIONS:
        return 'gained'
    if before in BULK_DIRECTIONS:
        return 'lost'
    return 'unchanged'


def compare_gene_tables(baseline_path, scenario_path, baseline, scenario, labels, *,
                        page=1, page_size=100, change_stream=None):
    if baseline_path == scenario_path:
        before, after = _fixed_gene_rows(baseline_path, (baseline, scenario), labels)
    else:
        before, = _fixed_gene_rows(baseline_path, (baseline,), labels)
        after, = _fixed_gene_rows(scenario_path, (scenario,), labels)
    writer = None
    if change_stream is not None:
        writer = csv.DictWriter(change_stream, fieldnames=_GENE_FIELDS, delimiter='\t', lineterminator='\n')
        writer.writeheader()
    counts = dict.fromkeys(_CHANGE_CLASSES, 0)
    baseline_counts, scenario_counts = Counter(), Counter()
    items = []
    identifiers = sorted(before.keys() | after.keys())
    start, end = (page - 1) * page_size, page * page_size
    absent = ('absent', None, None, '')
    for index, feature_id in enumerate(identifiers):
        left, left_q, left_effect, left_symbol = before.get(feature_id, absent)
        right, right_q, right_effect, right_symbol = after.get(feature_id, absent)
        change = _change(left, right)
        counts[change] += 1
        baseline_counts[left] += 1
        scenario_counts[right] += 1
        on_page = start <= index < end
        if on_page or writer:
            item = dict(feature_id=feature_id, symbol=left_symbol or right_symbol, baseline_class=left,
                        scenario_class=right, change=change, baseline_q=left_q, scenario_q=right_q,
                        baseline_effect=left_effect, scenario_effect=right_effect)
            if writer:
                writer.writerow(item)
            if on_page:
                items.append(item)
    return dict(counts=counts, baseline_counts=dict(baseline_counts), scenario_counts=dict(scenario_counts),
                items=items, total=len(identifiers), page=page, page_size=page_size)


def _processed_sources(assets, db, project, sources):
    bio = BioAnalysisStore(assets)
    out = []
    for source in sources:
        if source['source_kind'] != 'bio_processed_dataset_version':
            continue
        version = bio.require(db, 'bio_processed_dataset_versions', project, source['source_id'])
        recipe = bio.require(db, 'bio_analysis_recipe_versions', project, version['recipe_version_id'])
        raw = source['metadata']['raw_source']
        out.append(dict(version_id=version['id'], sha256=source['sha256'], task_id=version['task_id'],
                        run_id=version['run_id'], recipe_version_id=recipe['id'], dataset_id=raw['dataset_id'],
                        dataset_version_id=raw['dataset_version_id'], design_version_id=recipe['design_version_id'],
                        observation_map_version_id=recipe['observation_map_version_id'],
                        excluded_samples=sorted(recipe['params_json'].get('exclude_samples', [])),
                        excluded_feature_count=len(recipe['params_json'].get('exclude_features', []))))
    if not out:
        raise invalid('bio_insight_source_incomplete', 422)
    return out


def _read_fixed_comparison(service, db, project, version_id):
    from .service import BioInsightsService

    result = service.require(db, 'bio_insight_result_versions', project, version_id)
    plan = service.require(db, 'bio_insight_plan_versions', project, result['plan_version_id'])
    config = plan['config_json']
    metadata = {'kind': result['kind'], 'plan_config': config}
    if not is_reviewed_bulk(metadata) or plan['decision'] != 'confirmed':
        raise invalid('bio_insight_source_unsupported', 422)
    task = service.store.require_task(db, result['task_id'])
    if task['status'] != 'succeeded':
        raise invalid('bio_insight_source_incomplete', 422)
    envelope = BioInsightsService(service.assets).require_sources(db, task, runtime=False)
    _, members = checked_members(service, db, project, result)
    table = next((member for member in members if member['key'] == 'comparison_results'
                  and member['format'] == 'tsv' and member['role'] == 'table'), None)
    if table is None:
        raise invalid('bio_insight_source_incomplete', 422)
    try:
        labels = bulk_contrast_labels(metadata)
        reviewed = plan['design_checks_json']['bulk_model']
        sources = _processed_sources(service.assets, db, project, envelope['sources'])
        source_ids = {item['version_id']: item for item in sources}
        samples = []
        for sample in reviewed['samples']:
            source = source_ids[sample['processed_version_id']]
            samples.append(dict(sample, dataset_id=source['dataset_id'], dataset_version_id=source['dataset_version_id']))
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise invalid() from exc
    if not samples:
        raise invalid('bio_insight_source_incomplete', 422)
    taxa = {source['metadata'].get('species_taxon_id') for source in envelope['sources']
            if source['source_kind'] == 'bio_processed_dataset_version'} - {None}
    taxon = config.get('species_taxon_id') or (next(iter(taxa)) if len(taxa) == 1 else None)
    diagnostics = result['methods_json'].get('model_diagnostics', [])
    if isinstance(diagnostics, list):
        diagnostics = next(iter(diagnostics), {})
    parameters = {key: config.get(key) for key in _MODEL_PARAMETERS}
    parameters.update(dict(native_parameters=diagnostics.get('parameters', {}),
                           fit_type_effective=diagnostics.get('fit_type_effective'),
                           formula=reviewed.get('formula'), rank=reviewed.get('rank'),
                           design_columns=reviewed.get('design_columns'),
                           residual_degrees_freedom=reviewed.get('residual_degrees_freedom'),
                           filter=reviewed.get('filter')))
    return dict(version_id=version_id, result_version_id=version_id, run_id=result['run_id'], task_id=task['id'],
                plan_id=plan['plan_id'], plan_version_id=plan['id'], reviewed_design_sha256=plan['design_checks_json'].get('reviewed_design_sha256'),
                manifest_sha256=result['manifest_sha256'], table_sha256=table['sha256'],
                table_member_id=table['id'], provenance=result['provenance'], inference_scope=result['inference_scope'],
                species_taxon_id=taxon, namespace=config.get('namespace'), reference_version=config.get('reference_version'),
                processed_version_id=sources[0]['version_id'] if len(sources) == 1 else None,
                design_version_id=sources[0]['design_version_id'] if len(sources) == 1 else None,
                processed_sources=sources, samples=samples, parameters=parameters,
                group_sizes=reviewed.get('group_sizes', {}), environment_digest=result['environment_digest'],
                code_digest=result['code_digest']), labels, service.objects.path(table['object_key'])


def _sample_changes(before, after):
    def indexed(samples):
        return {(sample['dataset_version_id'], sample['sample_id']): sample for sample in samples}

    left, right = indexed(before), indexed(after)
    shared = sorted(left.keys() & right.keys())
    added = sorted(right.keys() - left.keys())
    removed = sorted(left.keys() - right.keys())
    changed_fields = ('biological_unit_id', 'batch', 'donor', 'covariates')
    return dict(added=[sample for _, sample in added], removed=[sample for _, sample in removed], shared=len(shared),
                reassigned=[key[1] for key in shared if left[key]['condition'] != right[key]['condition']],
                metadata_changed=[key[1] for key in shared if any(left[key].get(field) != right[key].get(field)
                                                                 for field in changed_fields)],
                identity_basis='dataset_version_id_and_sample_id')


def compare_saved_bulk(service, db, project, baseline_version_id, scenario_version_id, baseline_selection,
                       scenario_selection, *, page=1, page_size=100, change_stream=None):
    left, left_labels, left_path = _read_fixed_comparison(service, db, project, baseline_version_id)
    same_result = baseline_version_id == scenario_version_id
    if same_result:
        right, right_labels, right_path = left, left_labels, left_path
    else:
        right, right_labels, right_path = _read_fixed_comparison(service, db, project, scenario_version_id)
    direction = left_labels.get(baseline_selection.contrast_id)
    scenario_direction = right_labels.get(scenario_selection.contrast_id)
    if direction is None or scenario_direction is None:
        raise invalid('bio_insight_not_found', 404)
    identity_fields = ('species_taxon_id', 'namespace', 'reference_version')
    if (direction != scenario_direction or same_result and baseline_selection.contrast_id != scenario_selection.contrast_id
            or any(left[key] != right[key] for key in identity_fields)):
        raise invalid('bio_insight_source_unsupported', 422)
    try:
        results = compare_gene_tables(left_path, right_path, baseline_selection, scenario_selection, direction,
                                      page=page, page_size=page_size, change_stream=change_stream)
    except (csv.Error, OSError, UnicodeError, ValueError) as exc:
        raise invalid() from exc
    numerator, denominator = direction
    labels = dict(numerator=numerator, denominator=denominator)
    changes = sorted(key for key in left['parameters'] if left['parameters'][key] != right['parameters'][key])
    changes.extend(key for key in ('inference_scope', 'environment_digest', 'code_digest') if left[key] != right[key])
    return dict(**results, comparison_type='threshold_only' if same_result else 'alternate_run',
                baseline={**left, **labels, 'selection': baseline_selection.model_dump(mode='json')},
                scenario={**right, **labels, 'selection': scenario_selection.model_dump(mode='json')},
                sample_changes=_sample_changes(left['samples'], right['samples']), parameter_changes=changes)
