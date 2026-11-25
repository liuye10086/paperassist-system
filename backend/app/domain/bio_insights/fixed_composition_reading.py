"""Presentation of published donor-level Propeller values from a fixed table."""

from math import isclose, isfinite

from app.adapters.bio_insights_store import invalid
from app.domain.runtime_skills.runtime import SINGLE_CELL_COMPOSITION_PREVIEW, is_enabled


TABLE_KEY = 'composition_results'
ROW_FIELDS = (
    'category', 'label_id', 'mean_proportion_denominator', 'mean_proportion_numerator',
    'proportion_difference', 'p_adjust', 'inference_status', 'reason',
)


def supported(result):
    methods = result['methods']
    config = methods.get('config')
    return (result['kind'] == 'comparison' and result['inference_scope'] == 'donor_inference'
            and methods.get('name') == 'speckle_propeller' and isinstance(config, dict)
            and config.get('schema_version') == 5 and config.get('method') == 'single_cell_composition'
            and config.get('mode') == 'donor_unpaired' and config.get('transform') == 'asin'
            and config.get('batch_adjustment') is False and config.get('labels_confirmed') is True)


def preview_available(result):
    return (is_enabled(SINGLE_CELL_COMPOSITION_PREVIEW) and supported(result)
            and any(member['key'] == TABLE_KEY and member['role'] == 'table' and member['format'] == 'tsv'
                    for member in result['members']))


def _check_proportions(row, design):
    if any(row[key] != design[key] for key in ('numerator', 'denominator')):
        raise ValueError('Composition direction changed')
    denominator = float(row['mean_proportion_denominator'])
    numerator = float(row['mean_proportion_numerator'])
    difference = float(row['proportion_difference'])
    if not (0 <= numerator <= 1 and 0 <= denominator <= 1
            and isclose(difference, numerator - denominator, rel_tol=1e-10, abs_tol=1e-12)):
        raise ValueError('Invalid composition values')
    adjusted = row['p_adjust']
    if row['inference_status'] == 'tested':
        probability = float(adjusted)
        if not isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError('Invalid adjusted probability')
    elif row['inference_status'] != 'not_computable' or adjusted:
        raise ValueError('Invalid composition inference status')


def project_table(project_id, result, metadata, table, trace):
    try:
        config = metadata['methods']['config']
        units, = metadata['methods']['actual_units']
        design = {key: units[key] for key in ('denominator', 'numerator', 'n_denominator', 'n_numerator')}
        if (units['observation_level'] != 'donor' or design['numerator'] == design['denominator']
                or any(design[key] != config[key] for key in ('numerator', 'denominator'))
                or any(type(design[key]) is not int or design[key] < 3 for key in ('n_denominator', 'n_numerator'))
                or not set(ROW_FIELDS + ('numerator', 'denominator')) <= set(table['columns'])):
            raise ValueError('Invalid composition design')
        rows = []
        for row in table['items']:
            projected = {key: row[key] for key in ROW_FIELDS}
            if (any(not isinstance(value, str) for value in projected.values()) or not projected['category']
                    or (projected['category'] == 'label') != bool(projected['label_id'])):
                raise ValueError('Invalid composition category or cells')
            _check_proportions(row, design)
            rows.append(projected)
        versions = metadata['methods'].get('versions') or {}
        runtime = {name: versions[name] for name in ('R', 'speckle', 'limma', 'statmod') if isinstance(versions.get(name), str)}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise invalid() from exc
    return dict(schema_version=1, project_id=project_id, result_version_id=result['id'], manifest_sha256=result['manifest_sha256'],
                table_sha256=table['sha256'], trace=trace.model_dump(mode='json'), design=design, runtime=runtime,
                rows=rows, page=table['page'], page_size=table['page_size'], total=table['total'])
