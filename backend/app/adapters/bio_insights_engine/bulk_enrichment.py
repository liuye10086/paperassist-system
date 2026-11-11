"""Scoped Bulk selection and identifier audit for the shared enrichment tests."""
from collections import Counter, defaultdict

from app.domain.bio_insights.bulk_enrichment import (
    bulk_enrichment_reference, bulk_namespace, bulk_resource_compatibility,
)
from app.domain.bio_insights.bulk_results import (
    bulk_contrast_labels, bulk_row_class, finite_metric, is_reviewed_bulk,
)
from .evidence import load_result
from .mapping import ExplicitMapper, resource_document


BULK_MAPPING_FIELDS = (
    'source_row_key', 'source_row_count', 'source_selection', 'mapping_class',
    'in_background', 'in_foreground', 'in_ranking', 'in_resource', 'many_to_one', 'tied_rank',
)
_MAPPING_CLASSES = {
    'one_to_many_mapping': 'ambiguous',
    'unmapped_feature_id': 'unmapped',
    'invalid_feature_id': 'invalid',
}
_ORA_BACKGROUND_EXCLUSIONS = {
    'not_computable': 'background_not_computable',
    'missing_metric': 'background_missing_selected_q_or_effect',
}


def load_bulk_result(source, scope, contrast_ids):
    metadata = source['metadata']
    if not is_reviewed_bulk(metadata):
        raise ValueError('bulk_complete_comparison_required')
    reference = bulk_enrichment_reference(metadata, scope)
    config = metadata['plan_config']
    for name in ('species_taxon_id', 'namespace', 'reference_version'):
        value, planned = metadata.get(name), config.get(name)
        if name == 'namespace':
            value, planned = bulk_namespace(value), bulk_namespace(planned)
        if value is not None and planned is not None and value != planned:
            raise ValueError('result_reference_metadata_mismatch')
    labels = bulk_contrast_labels(metadata)
    if not set(contrast_ids) <= labels.keys():
        raise ValueError('contrast_not_found')
    result = load_result(source, bulk_reference=reference, bulk_contrasts=contrast_ids)
    if not result['tested_universe_complete']:
        raise ValueError('bulk_complete_comparison_required')
    for row in result['rows']:
        if (labels[row['contrast_id']] != (row['numerator'], row['denominator'])
                or row['inference_scope'] != result['inference_scope']):
            raise ValueError('bulk_comparison_row_invalid')
    return result | {'bulk_reference': reference}


def bulk_resource_references(result, resources, maps):
    reference = result['bulk_reference']
    resource_references = {}
    for source, data in resources:
        resource_references[source['source_id']] = _resource_reference(reference, source, data)
    for source in maps:
        _resource_reference(reference, source, resource_document(source))
    return resource_references


def _resource_reference(reference, source, data):
    metadata = source.get('metadata', {})
    # Check any explicit frozen reference as well as the verified resource member.
    if metadata.get('species_taxon_id') is not None:
        frozen = bulk_resource_compatibility(reference, metadata)
        if (frozen['namespace'] != bulk_namespace(data.get('namespace'))
                or frozen['release'] != data.get('release')):
            raise ValueError('bulk_resource_identity_mismatch')
    return bulk_resource_compatibility(reference, metadata | data)


def bulk_mapper(result, target, maps):
    return ExplicitMapper(result['species_taxon_id'], result['namespace'], target['species_taxon_id'],
                          target['namespace'], maps, namespace_key=bulk_namespace)


def gene_set_universe(data):
    return {gene for term in data['terms'] for gene in term['genes']}


def ora_selection(contrast, config, source_id, contrast_id, exclusions):
    source_rows = {row['feature_id']: row for row in contrast}
    if len(source_rows) != len(contrast):
        raise ValueError('bulk_comparison_duplicate_feature')
    classes = {gene: bulk_row_class(row, config) for gene, row in source_rows.items()}
    if config.bulk_background is None:
        background = {gene for gene, row in source_rows.items() if row['tested']}
    else:
        background = set()
        for gene, row in source_rows.items():
            category = classes[gene]
            if category == 'excluded':
                continue
            if row['test_status'] != 'tested':
                category = classes[gene] = 'not_computable'
            reason = _ORA_BACKGROUND_EXCLUSIONS.get(category)
            if reason:
                exclusions.append(dict(result_source_id=source_id, contrast_id=contrast_id, resource_id='',
                                       feature_id=gene, reason=reason))
            else:
                background.add(gene)
    directions = {'up', 'down'} if config.direction == 'both' else {config.direction}
    foreground = {gene for gene in background if classes[gene] in directions}
    return source_rows, classes, background, foreground


def _ora_role_coverage(ids, mapped, universe):
    targets = {mapped[gene][0] for gene in ids if mapped[gene][1] is None}
    failures = Counter(mapped[gene][1] for gene in ids)
    effective = targets & universe
    coverage = dict(original_count=len(ids), unmapped_count=failures['unmapped_feature_id'],
                    ambiguous_count=failures['one_to_many_mapping'], invalid_count=failures['invalid_feature_id'],
                    many_to_one_collapse_count=failures[None] - len(targets),
                    out_of_resource_count=len(targets) - len(effective), mapped_count=len(targets),
                    effective_count=len(effective))
    return effective, coverage


def map_ora_selection(selection, mapper, universe, context, mapping_rows, exclusions):
    source_rows, classes, background, foreground = selection
    mapped = {gene: mapper.map_id(gene) for gene in sorted(background)}
    counts = Counter(target for target, reason in mapped.values() if reason is None)
    for gene, (target, reason) in mapped.items():
        in_resource = target in universe
        many_to_one = target is not None and counts[target] > 1
        if reason:
            mapping_class = _MAPPING_CLASSES[reason]
        elif not in_resource:
            mapping_class, reason = 'out_of_resource', 'mapped_target_outside_resource_universe'
        else:
            mapping_class = 'many_to_one' if many_to_one else 'mapped'
        mapping_rows.append(dict(**context, original_id=gene, target_id=target, reason=reason,
            source_row_key=source_rows[gene]['row_key'], source_row_count=1, source_selection=classes[gene],
            mapping_class=mapping_class, in_background=True, in_foreground=gene in foreground,
            in_resource=in_resource, many_to_one=many_to_one))
        if reason:
            exclusions.append(dict(**context, feature_id=gene, reason=reason))
    bg, background_coverage = _ora_role_coverage(background, mapped, universe)
    fg, foreground_coverage = _ora_role_coverage(foreground, mapped, universe)
    return bg, fg, dict(**context, background=background_coverage, foreground=foreground_coverage,
                        not_tested_count=sum(not row['tested'] for row in source_rows.values()),
                        selection_counts=dict(Counter(classes.values())))


def ora_skip_reason(coverage, min_size):
    background, foreground = coverage['background'], coverage['foreground']
    if not background['original_count']:
        return 'insufficient_resource_background'
    if not foreground['original_count']:
        return 'empty_foreground'
    if background['effective_count'] < min_size:
        return 'insufficient_resource_background'
    if not foreground['effective_count']:
        return 'empty_effective_foreground'
    return None


def bulk_ranking(contrast, mapper, universes, context, mapping_rows, exclusions):
    originals = defaultdict(list)
    for row in contrast:
        originals[row['feature_id']].append(row)
    target_counts, audited, ranking = Counter(), [], []
    union = set().union(*universes.values())
    for original, records in sorted(originals.items()):
        row = records[0]
        score, target, reason = None, None, None
        if len(records) > 1:
            category, reason = 'duplicate_source', 'duplicate_source_feature_id'
        elif not row['tested']:
            category, reason = 'not_tested', 'ranking_gene_not_tested'
        elif (score := finite_metric(row['wald_statistic'])) is None:
            category, reason = 'missing_score', 'ranking_value_missing'
        elif row['test_status'] != 'tested':
            category, reason = 'not_computable', 'ranking_gene_not_computable'
        else:
            target, reason = mapper.map_id(original)
            category = _MAPPING_CLASSES[reason] if reason else 'mapped'
            if target is not None:
                target_counts[target] += 1
        audited.append((original, target, reason, category, score, records))

    classes = Counter()
    for original, target, reason, category, score, records in audited:
        many_to_one = target is not None and target_counts[target] > 1
        in_resource = target in union
        in_ranking = target is not None and not many_to_one
        source_key = records[0]['row_key'] if len(records) == 1 else None
        if many_to_one:
            category, reason = 'many_to_one', 'many_to_one_ranking_conflict'
        if in_ranking:
            if not in_resource:
                category = 'out_of_resource'
            ranking.append(dict(feature_id=target, statistic=score, source_feature_id=original, source_row_key=source_key))
        classes[category] += 1
        mapping_rows.append(dict(**context, original_id=original, target_id=target, reason=reason,
            source_row_key=source_key, source_row_count=len(records), source_selection=records[0]['test_status'],
            mapping_class=category, in_ranking=in_ranking, in_resource=in_resource, many_to_one=many_to_one))
        if reason:
            exclusions.append(dict(**context, feature_id=original, reason=reason))

    score_counts = Counter(row['statistic'] for row in ranking)
    tied = {row['source_feature_id'] for row in ranking if score_counts[row['statistic']] > 1}
    for entry in mapping_rows:
        entry['tied_rank'] = entry['original_id'] in tied
    genes = {row['feature_id'] for row in ranking}
    resource_coverage = {rid: dict(resource_gene_count=len(universe), effective_count=len(genes & universe),
                                    out_of_resource_count=len(genes - universe))
                         for rid, universe in universes.items()}
    coverage = dict(original_count=len(originals), original_row_count=len(contrast), not_tested_count=classes['not_tested'],
                    missing_score_count=classes['missing_score'], not_computable_count=classes['not_computable'],
                    duplicate_source_count=classes['duplicate_source'], ambiguous_count=classes['ambiguous'],
                    unmapped_count=classes['unmapped'], invalid_count=classes['invalid'],
                    many_to_one_conflict_count=classes['many_to_one'],
                    many_to_one_target_count=sum(count > 1 for count in target_counts.values()),
                    mapped_count=len(target_counts), out_of_resource_count=classes['out_of_resource'],
                    effective_count=len(ranking), tied_rank_count=len(tied),
                    tied_rank_excess_count=len(ranking) - len(score_counts))
    return ranking, dict(**context, ranking=coverage, resources=resource_coverage)


def bulk_result_status(result, references, coverage, summary, methods, significant_terms):
    reasons = sorted({item['not_applicable_reason'] for item in coverage if item['not_applicable_reason']})
    reason = None
    if not summary['row_count']:
        status = 'not_applicable'
        reason = reasons[0] if len(reasons) == 1 else 'no_applicable_enrichment_families'
    else:
        status = 'completed' if significant_terms else 'no_significant_terms'
    summary.update(enrichment_status=status, not_applicable_reason=reason, significant_terms=significant_terms)
    methods['bulk_enrichment'] = dict(source_reference=result['bulk_reference'], resource_references=references,
        coverage=coverage, not_applicable_reasons=reasons)
