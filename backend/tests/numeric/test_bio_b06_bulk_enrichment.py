"""Frozen Bulk comparison rows through local ORA and joint-null prerank."""
from collections import Counter
import json
from math import comb
from pathlib import Path

import pytest

from app.adapters.bio_engine.manifest import Writer
from bio_insights_fixtures import rows
from test_bio_ora import config, execute, resource_source


BULK_SCOPE = {'source_taxon_id': 9606, 'taxon_evidence': 'Declared Homo sapiens fixture'}
MAPPING_ID = 'mapping'


def bulk_result(tmp_path, entries, *, complete=True):
    folder = tmp_path / 'bulk'
    folder.mkdir()
    writer = Writer(folder)
    table = []
    for i, (gene, changes) in enumerate(entries):
        table.append({
            'row_key': f'row{i}', 'feature_id': gene, 'contrast_id': 'c1',
            'numerator': 'B', 'denominator': 'A', 'tested': True, 'test_status': 'tested',
            'inference_scope': 'sample_inference', 'effect_value': 2.,
            'q_within_contrast': .8, 'q_global_family': .9, 'original_method_adjustment': .01,
            'wald_statistic': None, **changes,
        })
    writer.table('comparison_results', table)
    summary = {'tested_universe_complete': complete}
    writer.json('manifest', {'kind': 'bio_comparison', 'summary': summary, 'inference_scope': 'sample_inference'})
    return dict(source_id='bulk', source_kind='bio_insight_result_version', sha256='a' * 64, role='result',
                members={a['key']: a for a in writer.artifacts}, metadata={
                    'kind': 'comparison', 'inference_scope': 'sample_inference', 'summary_json': summary,
                    'namespace': 'Ensembl gene ID', 'reference_version': 'fixture release',
                    'species_taxon_id': None, 'plan_config': {
                        'kind': 'comparison', 'mode': 'bulk_counts', 'bulk_model': 'shared_wald_v1',
                        'namespace': 'Ensembl gene ID', 'reference_version': 'fixture release',
                        'species_taxon_id': None, 'family_contrast_ids': ['c1'],
                        'contrasts': [{'contrast_id': 'c1', 'groups': [{'label': 'B'}, {'label': 'A'}]}],
                    }})


def mapping_source(tmp_path, targets, *, ambiguous=()):
    return resource_source(tmp_path, sid=MAPPING_ID, namespace='ensembl_gene_id', mapping={
        'source_namespace': 'Ensembl gene ID', 'target_namespace': 'symbol', 'mapping': targets,
        'ambiguous_source_ids': list(ambiguous), 'strip_ensembl_version': False,
    })


def term(term_id, *genes):
    return {'term_id': term_id, 'name': term_id, 'namespace': 'BP', 'genes': list(genes)}


def ora_config(**overrides):
    return config(**({'result_source_ids': ['bulk'], 'bulk_enrichment': BULK_SCOPE,
                      'q_column': 'original_method_adjustment', 'direction': 'up'} | overrides))


def gsea_config(**overrides):
    return {'kind': 'gsea_prerank', 'result_source_id': 'bulk', 'contrast_id': 'c1',
            'resource_source_ids': ['resource1'], 'ranking_column': 'wald_statistic',
            'min_size': 1, 'max_size': 10, 'permutation_num': 100, 'seed': 29,
            'bulk_enrichment': BULK_SCOPE, **overrides}


def artifact_json(writer, key):
    return json.loads(Path(next(item['path'] for item in writer.artifacts if item['key'] == key)).read_bytes())


def test_bulk_ora_exact_resource_universe_and_bh_include_zero_hits(tmp_path):
    source = bulk_result(tmp_path, [
        ('a1', {'effect_value': 1., 'original_method_adjustment': .05}), ('a2', {}), ('b', {}),
        ('out', {}), ('ambiguous', {}), ('unmapped', {}), ('failed', {'test_status': 'not_computable'}),
        ('negative', {'effect_value': -2.}), ('zero', {'effect_value': 0.}),
        ('excluded', {'tested': False, 'test_status': 'excluded'}),
    ])
    mapping = mapping_source(tmp_path, {'a1': 'A', 'a2': 'A', 'b': 'B', 'out': 'X',
        'failed': 'F', 'negative': 'N', 'zero': 'Z', 'excluded': 'U'}, ambiguous=('ambiguous',))
    resource = resource_source(tmp_path, namespace='symbol', terms=[
        term('hit', 'A', 'B', 'resource_only'), term('zero_hit', 'F', 'N', 'Z'), term('no_overlap', 'U', 'extra'),
    ])
    result, writer = execute(tmp_path, ora_config(mapping_source_ids=[MAPPING_ID]), [source, resource, mapping])
    actual = {r['term_id']: r for r in rows(writer, 'enrichment_results')}
    assert set(actual) == {'hit', 'zero_hit'}
    hit = actual['hit']
    N, K, n, k = (int(hit[key]) for key in ('N', 'K', 'n', 'k'))
    assert (N, K, n, k) == (5, 2, 2, 2)
    exact = sum(comb(K, x) * comb(N - K, n - x) for x in range(k, min(K, n) + 1)) / comb(N, n)
    assert float(hit['p_value']) == pytest.approx(exact, abs=1e-15)
    assert float(hit['q_value']) == pytest.approx(exact * 2, abs=1e-15)
    assert (actual['zero_hit']['k'], actual['zero_hit']['p_value'], actual['zero_hit']['q_value']) == ('0', '1.0', '1.0')
    assert result['summary']['enrichment_status'] == 'no_significant_terms'
    assert result['summary']['not_applicable_reason'] is None
    evidence = result['methods']['bulk_enrichment']
    assert evidence['source_reference']['species_taxon_id'] == 9606
    assert evidence['source_reference']['namespace'] == 'ensembl_gene_id'
    coverage = evidence['coverage'][0]
    assert coverage['background'] == dict(original_count=9, ambiguous_count=1, unmapped_count=1,
        invalid_count=0, many_to_one_collapse_count=1, out_of_resource_count=1, mapped_count=6, effective_count=5)
    assert coverage['foreground'] == dict(original_count=6, ambiguous_count=1, unmapped_count=1,
        invalid_count=0, many_to_one_collapse_count=1, out_of_resource_count=1, mapped_count=3, effective_count=2)
    audit = {r['original_id']: r for r in rows(writer, 'mapping_rows')}
    assert len(audit) == len(rows(writer, 'mapping_rows')) == 9
    assert audit['a1']['in_background'] == audit['a1']['in_foreground'] == 'True'
    assert audit['a2']['mapping_class'] == 'many_to_one'
    assert audit['failed']['in_background'] == 'True' and audit['failed']['in_foreground'] == 'False'
    assert audit['out']['mapping_class'] == 'out_of_resource'
    assert audit['ambiguous']['mapping_class'] == 'ambiguous'
    assert audit['unmapped']['mapping_class'] == 'unmapped'
    sets = artifact_json(writer, 'ora_sets')['families'][0]
    assert sets['background'] == ['A', 'B', 'F', 'N', 'Z'] and sets['foreground'] == ['A', 'B']


@pytest.mark.parametrize(('selected', 'terms', 'min_size', 'reason'), [
    ('zero', [term('bg', 'zero', 'bg')], 1, 'empty_foreground'),
    ('out', [term('bg', 'zero', 'bg')], 1, 'empty_effective_foreground'),
    ('out', [term('bg', 'out')], 2, 'insufficient_resource_background'),
    ('out', [term('too_large', 'zero', 'bg', 'out')], 1, 'no_eligible_terms'),
])
def test_bulk_ora_not_applicable_has_no_scientific_rows(tmp_path, selected, terms, min_size, reason):
    source = bulk_result(tmp_path, [
        ('out', {'original_method_adjustment': .01 if selected == 'out' else .8}),
        ('zero', {'effect_value': 0.}), ('bg', {'original_method_adjustment': .8}),
    ])
    resource = resource_source(tmp_path, namespace='ensembl_gene_id', terms=terms)
    result, writer = execute(tmp_path, ora_config(direction='both', minimum_absolute_effect=0.,
        min_size=min_size, max_size=max(2, min_size)), [source, resource])
    assert result['summary']['enrichment_status'] == 'not_applicable'
    assert result['summary']['not_applicable_reason'] == reason
    assert result['summary']['significant_terms'] == 0
    assert rows(writer, 'enrichment_results') == []
    assert result['methods']['bulk_enrichment']['coverage'][0]['not_applicable_reason'] == reason
    assert artifact_json(writer, 'ora_sets')['families'][0]['term_hits'] == []


def test_bulk_ora_merged_bh_excludes_collection_without_effective_foreground(tmp_path):
    source = bulk_result(tmp_path, [('a', {})] + [
        (gene, {'original_method_adjustment': .8}) for gene in ('b', 'c', 'd')
    ])
    active = resource_source(tmp_path, namespace='ensembl_gene_id',
        terms=[term('one_hit', 'a'), term('zero_hit', 'b', 'c', 'd')])
    inactive = resource_source(tmp_path, sid='outside', namespace='ensembl_gene_id',
        terms=[term('outside', 'b', 'c')])
    cfg = ora_config(resource_source_ids=['resource1', 'outside'], merge_collections=True)
    result, writer = execute(tmp_path, cfg, [source, active, inactive])
    actual = {row['term_id']: row for row in rows(writer, 'enrichment_results')}
    assert set(actual) == {'one_hit', 'zero_hit'}
    assert float(actual['one_hit']['q_value']) == pytest.approx(.5)
    assert result['summary']['enrichment_status'] == 'no_significant_terms'
    assert result['summary']['not_applicable_reason'] is None
    assert result['methods']['bulk_enrichment']['not_applicable_reasons'] == ['empty_effective_foreground']


def test_bulk_gsea_keeps_misses_and_saved_curve_matches_independent_walk(tmp_path):
    import gseapy
    import pandas as pd

    source = bulk_result(tmp_path, [
        (gene, {'wald_statistic': value, 'original_method_adjustment': .8}) for gene, value in [
            ('plus_b', 4.), ('plus_a', 4.), ('miss_hi', 3.), ('plus_c', 2.), ('neutral', 0.),
            ('miss_lo', -1.), ('minus_a', -2.), ('minus_b', -5.), ('collision1', 6.), ('collision2', -6.),
            ('ambiguous', 2.), ('unmapped', 3.), ('missing', None), ('nonfinite', 'Inf'), ('dup', 5.), ('dup', 1.),
        ]
    ] + [('excluded', {'wald_statistic': 8., 'tested': False, 'test_status': 'excluded'})])
    mapping = mapping_source(tmp_path, {'plus_b': 'B', 'plus_a': 'A', 'miss_hi': 'Y', 'plus_c': 'C',
        'neutral': 'X', 'miss_lo': 'W', 'minus_a': 'F', 'minus_b': 'G', 'collision1': 'clash',
        'collision2': 'clash', 'missing': 'M', 'nonfinite': 'I', 'dup': 'D'}, ambiguous=('ambiguous',))
    r1 = resource_source(tmp_path, namespace='symbol', terms=[term('positive', 'A', 'C'), term('zero_weight', 'X')])
    r2 = resource_source(tmp_path, sid='resource2', namespace='symbol', terms=[term('negative', 'B', 'F', 'G')])
    cfg = gsea_config(resource_source_ids=['resource1', 'resource2'], mapping_source_ids=[MAPPING_ID])
    result, writer = execute(tmp_path, cfg, [source, r1, r2, mapping])
    _, replay = execute(tmp_path, cfg, [source, r1, r2, mapping], 'replay')
    ranking = rows(writer, 'gsea_ranking')
    assert [r['feature_id'] for r in ranking] == ['A', 'B', 'Y', 'C', 'X', 'W', 'F', 'G']
    assert [int(r['rank']) for r in ranking] == list(range(8))
    actual = rows(writer, 'enrichment_results')
    assert actual == rows(replay, 'enrichment_results')
    assert result['summary']['significant_terms'] == sum(float(row['fdr_q_value']) <= .05 for row in actual)
    assert {r['term_id'] for r in actual} == {'positive', 'negative'}
    curves = artifact_json(writer, 'gsea_curves')
    assert curves == artifact_json(replay, 'gsea_curves')
    by_key = {item['row_key']: item for item in curves['terms']}
    scores = [float(r['statistic']) for r in ranking]
    joint = gseapy.prerank(rnk=pd.Series(scores, index=[r['feature_id'] for r in ranking]),
        gene_sets={'resource1::positive': ['A', 'C'], 'resource2::negative': ['B', 'F', 'G']},
        min_size=1, max_size=10, permutation_num=100, weight=1, threads=1, seed=29,
        ascending=None, no_plot=True, outdir=None, verbose=False)
    for row in actual:
        genes = {'A', 'C'} if row['term_id'] == 'positive' else {'B', 'F', 'G'}
        ranks = [i for i, r in enumerate(ranking) if r['feature_id'] in genes]
        hit_total = sum(abs(scores[i]) for i in ranks)
        running, score = [], 0.
        for i, wald in enumerate(scores):
            score += abs(wald) / hit_total if i in ranks else -1 / (len(scores) - len(ranks))
            running.append(score)
        peak = max(range(len(running)), key=lambda i: abs(running[i]))
        expected_es = running[peak]
        leading = [ranking[i]['feature_id'] for i in ranks if (i <= peak if expected_es > 0 else i >= peak)]
        assert float(row['es']) == pytest.approx(expected_es, abs=1e-14)
        assert json.loads(row['leading_edge']) == leading
        assert by_key[row['row_key']]['hit_indices'] == ranks
        library = joint.results[row['collection_term_id']]
        assert float(row['nes']) == pytest.approx(library['nes'], abs=1e-12)
        assert float(row['fdr_q_value']) == pytest.approx(library['fdr'], abs=1e-12)
        assert row['q_value'] == ''
    coverage = result['methods']['bulk_enrichment']['coverage'][0]['ranking']
    assert coverage['missing_score_count'] == 2 and coverage['not_tested_count'] == 1
    assert coverage['duplicate_source_count'] == 1 and coverage['many_to_one_conflict_count'] == 2
    assert coverage['out_of_resource_count'] == 2 and coverage['effective_count'] == 8
    assert coverage['tied_rank_count'] == 2
    audit = {r['original_id']: r for r in rows(writer, 'mapping_rows')}
    assert audit['dup']['source_row_count'] == '2'
    assert audit['miss_hi']['mapping_class'] == 'out_of_resource'
    assert audit['collision1']['reason'] == 'many_to_one_ranking_conflict'
    assert Counter(r['reason'] for r in rows(writer, 'term_exclusions'))['gsea_term_zero_weight'] == 1


@pytest.mark.parametrize(('scores', 'terms', 'ranking_size', 'reason'), [
    ([None, None], [term('one', 'g1')], 0, 'ranking_all_zero_or_insufficient'),
    ([0., 0.], [term('one', 'g1')], 2, 'ranking_all_zero_or_insufficient'),
    ([2., None], [term('one', 'g1')], 1, 'ranking_all_zero_or_insufficient'),
    ([2., 0.], [term('none', 'external')], 2, 'no_eligible_terms'),
])
def test_bulk_gsea_publishes_audit_even_when_no_test_is_applicable(tmp_path, scores, terms, ranking_size, reason):
    source = bulk_result(tmp_path, [(f'g{i}', {'wald_statistic': score}) for i, score in enumerate(scores)])
    resource = resource_source(tmp_path, namespace='ensembl_gene_id', terms=terms)
    result, writer = execute(tmp_path, gsea_config(), [source, resource])
    assert result['summary']['enrichment_status'] == 'not_applicable'
    assert result['summary']['not_applicable_reason'] == reason
    assert result['summary']['significant_terms'] == 0
    assert rows(writer, 'enrichment_results') == []
    assert len(rows(writer, 'gsea_ranking')) == ranking_size
    assert artifact_json(writer, 'gsea_curves')['terms'] == []
