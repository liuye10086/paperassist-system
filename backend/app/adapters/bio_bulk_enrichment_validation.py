"""Check Bulk enrichment against its frozen inputs without rerunning GSEA permutations."""
import hashlib
import json
import math
from collections import defaultdict
from itertools import zip_longest

from app.adapters.bio_insights_engine.bulk_enrichment import (
    BULK_MAPPING_FIELDS, bulk_mapper, bulk_ranking, bulk_resource_references,
    gene_set_universe, load_bulk_result, map_ora_selection, ora_selection, ora_skip_reason,
)
from app.adapters.bio_insights_engine.mapping import resource_document
from app.adapters.bio_insights_engine.evidence import numeric
from app.domain.bio_insights.contracts import GseaPrerankConfig, OraConfig


def _frozen_inputs(payload, config, source_id, contrasts):
    sources = {source['source_id']: source for source in payload['sources']}
    comparison = load_bulk_result(sources[source_id], config.bulk_enrichment, contrasts)
    resources = [(sources[key], resource_document(sources[key])) for key in config.resource_source_ids]
    maps = [sources[key] for key in config.mapping_source_ids]
    return comparison, resources, maps, bulk_resource_references(comparison, resources, maps)


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _ora_inputs(comparison, resources, maps, references, config, doc, mapping_rows, exclusions):
    source_id = comparison['source']['source_id']
    expected, sets, coverage = {}, {}, []
    for contrast in config.contrast_ids:
        rows = [row for row in comparison['rows'] if row['contrast_id'] == contrast]
        selection = ora_selection(rows, config, source_id, contrast, exclusions)
        for source, resource in resources:
            rid = source['source_id']
            universe = gene_set_universe(resource)
            context = dict(result_source_id=source_id, contrast_id=contrast, resource_id=rid)
            family_id = _identity(dict(result=source_id, contrast=contrast, direction=config.direction,
                collections=config.resource_source_ids if config.merge_collections else [rid]))
            background, foreground, audit = map_ora_selection(
                selection, bulk_mapper(comparison, references[rid], maps), universe, context, mapping_rows, exclusions)
            reason = ora_skip_reason(audit, config.min_size)
            terms = {}
            if reason is None:
                for term in resource['terms']:
                    members = set(term['genes']) & background
                    if config.min_size <= len(members) <= config.max_size:
                        hits = sorted(members & foreground)
                        row_key = _identity(dict(**context, term_id=term['term_id'], direction=config.direction))
                        terms[term['term_id']] = (row_key, hits)
                        expected[(contrast, rid, term['term_id'])] = (
                            len(background), len(foreground), len(members), hits, family_id, row_key)
                if not terms:
                    reason = 'no_eligible_terms'
            audit.update(not_applicable_reason=reason, resource_gene_count=len(universe), eligible_term_count=len(terms))
            coverage.append(audit)
            sets[(contrast, rid)] = (sorted(background), sorted(foreground), terms, reason, family_id)

    records = doc('ora_sets')['families']
    if len(records) != len(sets):
        raise ValueError('bulk_ora_sets_mismatch')
    for record in records:
        key = (record['contrast_id'], record['resource_id'])
        background, foreground, terms, reason, family_id = sets.pop(key)
        hits = {term['term_id']: (term['row_key'], term['hits']) for term in record['term_hits']}
        if (record['result_source_id'] != source_id or record['direction'] != config.direction
                or (record['N'], record['n']) != (len(background), len(foreground))
                or record['background'] != background or record['foreground'] != foreground
                or record.get('not_applicable_reason') != reason or record['family_id'] != family_id or hits != terms
                or len(hits) != len(record['term_hits'])):
            raise ValueError('bulk_ora_sets_mismatch')
    return expected, coverage


def _gsea_inputs(comparison, resources, maps, references, config, table, doc, mapping_rows, exclusions, *, neutral_keys):
    source_id = comparison['source']['source_id']
    context = dict(result_source_id=source_id, contrast_id=config.contrast_id, resource_id='joint')
    universes = {source['source_id']: gene_set_universe(data) for source, data in resources}
    mapper = bulk_mapper(comparison, next(iter(references.values())), maps)
    ranked, audit = bulk_ranking(comparison['rows'], mapper, universes, context, mapping_rows, exclusions)
    ranked.sort(key=lambda row: (-row['statistic'], row['feature_id']))
    saved = list(table('gsea_ranking', {'rank', 'feature_id', 'statistic', 'source_feature_id', 'source_row_key'}))
    if len(saved) != len(ranked) or any(
        int(actual['rank']) != index or float(actual['statistic']) != expected['statistic']
        or any(actual[key] != expected[key] for key in ('feature_id', 'source_feature_id', 'source_row_key'))
        for index, (actual, expected) in enumerate(zip(saved, ranked))
    ):
        raise ValueError('bulk_gsea_frozen_ranking_mismatch')

    ranks = {row['feature_id']: index for index, row in enumerate(ranked)}
    insufficient = len(ranked) < 2 or not any(row['statistic'] for row in ranked)
    ranking_reason = ('ranking_all_zero_or_insufficient' if insufficient else
                      'ranking_all_equal' if neutral_keys and len({row['statistic'] for row in ranked}) == 1 else None)
    expected = {}
    for source, resource in resources:
        rid = source['source_id']
        count = 0
        if ranking_reason is None:
            for term in resource['terms']:
                hits = sorted(ranks[gene] for gene in term['genes'] if gene in ranks)
                if (config.min_size <= len(hits) <= config.max_size and len(hits) < len(ranked)
                        and (config.weight == 0 or any(ranked[index]['statistic'] for index in hits))):
                    expected[(config.contrast_id, rid, term['term_id'])] = hits
                    count += 1
        audit['resources'][rid].update(eligible_term_count=count,
            not_applicable_reason=None if count else ranking_reason or 'no_eligible_terms')
    audit['not_applicable_reason'] = None if expected else ranking_reason or 'no_eligible_terms'

    terms = doc('gsea_curves')['terms']
    curves = {(config.contrast_id, term['resource_id'], term['term_id']): term for term in terms}
    if set(curves) != set(expected) or len(curves) != len(terms):
        raise ValueError('bulk_gsea_curve_family_mismatch')
    genes = [row['feature_id'] for row in ranked]
    scores = [row['statistic'] for row in ranked]
    for key, hits in expected.items():
        curve = curves[key]
        if curve['hit_indices'] != hits or curve['weight'] != config.weight:
            raise ValueError('bulk_gsea_curve_membership_mismatch')
        _check_leading_edge(curve, genes, scores, hits)
    return expected, [audit], curves


def _check_leading_edge(curve, genes, scores, hits):
    from app.adapters.bio_insights_engine.figure_data import running_enrichment

    running = running_enrichment(scores, hits, curve['weight'], curve['es'])
    leading = curve['leading_edge']
    count = len(leading)
    if not 1 <= count <= len(hits):
        raise ValueError('bulk_gsea_leading_edge_mismatch')
    if curve['es'] >= 0:
        expected = [genes[index] for index in hits[:count]]
        begin = hits[count - 1]
        end = hits[count] if count < len(hits) else len(genes)
        peak, extreme = max(running[begin:end]), max(running)
    else:
        expected = [genes[index] for index in hits[-count:]]
        begin = hits[-count - 1] + 1 if count < len(hits) else 0
        end = hits[-count] + 1
        peak, extreme = min(running[begin:end]), min(running)
    # Permit either boundary only when the running scores tie at the peak.
    if leading != expected or not math.isclose(peak, extreme, rel_tol=0, abs_tol=1e-12):
        raise ValueError('bulk_gsea_leading_edge_mismatch')


def _check_mapping_audit(table, name, columns, expected):
    for actual, row in zip_longest(table(name, columns), expected):
        if actual is None or row is None or any(
            actual[key] != ('' if row.get(key) is None else str(row[key])) for key in columns
        ):
            raise ValueError('bulk_enrichment_mapping_audit_mismatch')


def _probability(cell):
    value = float(cell)
    if not 0 <= value <= 1:
        raise ValueError('bulk_enrichment_invalid_probability')
    return value


def _check_bh(families):
    from scipy.stats import hypergeom

    for items in families.values():
        parameters = list(zip(*(item[2] for item in items)))
        N, n, K, k = parameters
        exact = hypergeom.sf([count - 1 for count in k], N, K, n)
        if any(not math.isclose(row[0], p, rel_tol=1e-10, abs_tol=0) for row, p in zip(items, exact)):
            raise ValueError('bulk_ora_probability_mismatch')
        adjusted = 1.0
        ordered = sorted(items, key=lambda item: item[0])
        for rank in range(len(ordered), 0, -1):
            p, q, _ = ordered[rank - 1]
            adjusted = min(adjusted, p * len(ordered) / rank)
            if not math.isclose(q, adjusted, rel_tol=1e-12, abs_tol=0):
                raise ValueError('bulk_ora_correction_mismatch')


def validate_bulk_enrichment(result, payload, table, doc):
    wire = payload['config']
    ora = wire['kind'] == 'ora'
    config = (OraConfig if ora else GseaPrerankConfig).model_validate(wire)
    source_id = config.result_source_ids[0] if ora else config.result_source_id
    contrasts = config.contrast_ids if ora else [config.contrast_id]
    comparison, resources, maps, references = _frozen_inputs(payload, config, source_id, contrasts)
    resource_sha = {source['source_id']: source['sha256'] for source, _ in resources}
    mapping_rows, exclusions = [], []
    if ora:
        if result['methods'].get('background') != config.bulk_background_method:
            raise ValueError('bulk_ora_background_method_mismatch')
        expected, coverage = _ora_inputs(comparison, resources, maps, references, config, doc, mapping_rows, exclusions)
    else:
        expected, coverage, curves = _gsea_inputs(comparison, resources, maps, references, config, table, doc,
                                                   mapping_rows, exclusions,
                                                   neutral_keys=result['methods'].get('native_term_key_policy') == 'membership_ordered_opaque_v1')
    reasons = sorted({item['not_applicable_reason'] for item in coverage if item['not_applicable_reason']})
    audit = result['methods']['bulk_enrichment']
    if audit != dict(source_reference=comparison['bulk_reference'], resource_references=references,
                     coverage=coverage, not_applicable_reasons=reasons):
        raise ValueError('bulk_enrichment_coverage_mismatch')

    context = {'result_source_id', 'contrast_id', 'resource_id', 'reason'}
    _check_mapping_audit(table, 'mapping_rows', context | {'original_id', 'target_id', *BULK_MAPPING_FIELDS}, mapping_rows)
    _check_mapping_audit(table, 'mapping_exclusions', context | {'feature_id'}, exclusions)

    counts = defaultdict(list)
    seen, row_keys, significant = set(), set(), 0
    adjusted_column = 'q_value' if ora else 'fdr_q_value'
    for row in table('enrichment_results', {'row_key', 'term_id', adjusted_column}):
        key = (row['contrast_id'], row['resource_id'], row['term_id'])
        if (key not in expected or key in seen or not row['row_key'] or row['row_key'] in row_keys
                or row['result_source_id'] != source_id or row['resource_sha256'] != resource_sha[key[1]]):
            raise ValueError('bulk_enrichment_term_family_mismatch')
        seen.add(key)
        row_keys.add(row['row_key'])
        q = _probability(row[adjusted_column]) if ora or row[adjusted_column] else None
        if ora:
            N, n, K, hits, family_id, row_key = expected[key]
            k = len(hits)
            if (tuple(int(row[k]) for k in ('N', 'n', 'K', 'k')) != (N, n, K, len(hits))
                    or json.loads(row['hits']) != hits or row['direction'] != config.direction
                    or row['source_q_column'] != config.q_column
                    or (row['family_id'], row['row_key'], row['GeneRatio'], row['BgRatio'])
                    != (family_id, row_key, f'{k}/{n}', f'{K}/{N}')
                    or (numeric(row['gene_ratio']), numeric(row['background_ratio']), numeric(row['enrichment_ratio']))
                    != (k/n, K/N, (k/n)/(K/N))):
                raise ValueError('bulk_ora_term_counts_mismatch')
            counts[(key[0], None if config.merge_collections else key[1])].append(
                (_probability(row['p_value']), q, (N, n, K, len(hits))))
        else:
            curve = curves[key]
            if (curve['row_key'] != row['row_key'] or curve['hit_indices'] != json.loads(row['hit_indices'])
                    or curve['leading_edge'] != json.loads(row['leading_edge'])
                    or int(row['set_size']) != len(curve['hit_indices'])
                    or int(row['ranking_size']) != coverage[0]['ranking']['effective_count']
                    or any(curve[k] != numeric(row[k]) for k in ('es', 'nes', 'nominal_p_value', 'fdr_q_value', 'fwer_p_value'))):
                raise ValueError('bulk_gsea_term_data_mismatch')
        significant += int(q is not None and q <= .05)
    if seen != set(expected):
        raise ValueError('bulk_enrichment_term_family_mismatch')
    if ora:
        _check_bh(counts)

    summary = result['summary']
    status = 'completed' if significant else 'no_significant_terms' if seen else 'not_applicable'
    reason = None if seen else reasons[0] if len(reasons) == 1 else 'no_applicable_enrichment_families'
    if (summary.get('row_count'), summary.get('enrichment_status'), summary.get('significant_terms'),
            summary.get('not_applicable_reason')) != (len(seen), status, significant, reason):
        raise ValueError('bulk_enrichment_status_mismatch')
