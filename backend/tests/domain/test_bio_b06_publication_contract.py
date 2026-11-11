import csv
import hashlib
import json
from pathlib import Path

import pytest

from app.adapters.bio_engine.manifest import Writer
from app.adapters.bio_insights_engine.pipeline import run
from app.adapters.bio_insights_process import _validate_scientific_contract


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.fixture
def scoped_ora(tmp_path, request):
    frozen = Writer(tmp_path)
    common = dict(contrast_id='a_vs_b', numerator='A', denominator='B', tested=True,
                  test_status='tested', inference_scope='sample_inference')
    rows = [
        dict(common, feature_id=f'g{i}', row_key=f'r{i}', effect_value=2 if i < 4 else -.5,
             q_within_contrast=.01 if i < 4 else .8, q_global_family=.02, original_method_adjustment=.01,
             wald_statistic=10 - i)
        for i in range(12)
    ]
    rows[10]['test_status'] = 'not_computable'
    rows[11]['q_within_contrast'] = None
    comparison = frozen.table('comparison_results', rows)
    resource = frozen.json('resource', dict(schema_version=1, kind='gene_sets', species_taxon_id=9606,
        namespace='ensembl_gene_id', release='v1', usage={'redistribution_allowed': True}, terms=[
            dict(term_id='positive', name='Positive', genes=[f'g{i}' for i in range(4)]),
            dict(term_id='other', name='Other', genes=[f'g{i}' for i in range(4, 12)]),
        ]))
    plan = dict(kind='comparison', mode='bulk_counts', bulk_model='shared_wald_v1', species_taxon_id=9606,
                namespace='Ensembl gene ID', reference_version='v1', contrasts=[dict(contrast_id='a_vs_b',
                groups=[dict(label='A'), dict(label='B')])])
    sources = [
        dict(source_id='comparison', source_kind='bio_insight_result_version', sha256=comparison['sha256'],
             metadata=dict(kind='comparison', plan_config=plan, inference_scope='sample_inference',
                           summary_json={'tested_universe_complete': True}), members={'comparison_results': comparison}),
        dict(source_id='collection', source_kind='bio_resource_version', sha256=resource['sha256'], metadata={},
             members={'resource': resource}),
    ]
    from app.domain.bio_insights.contracts import OraConfig
    config = OraConfig(result_source_ids=['comparison'], resource_source_ids=['collection'], contrast_ids=['a_vs_b'],
                       bulk_enrichment={}, min_size=2, max_size=9).model_dump(mode='json')
    if getattr(request, 'param', False):
        config['bulk_background'] = 'computable_selected_q_effect_intersected_with_collection'
    output = tmp_path / 'outputs'
    output.mkdir()
    payload = dict(schema_version=1, kind='bio_enrichment', identity={}, config=config, sources=sources,
                   output_directory=str(output))
    result = run(payload)
    items = {member['key']: member for member in result['outputs']}
    return payload, result, items


@pytest.mark.parametrize('scoped_ora', [True], indirect=True)
def test_parent_checks_new_background_against_the_frozen_plan(scoped_ora):
    payload, result, items = scoped_ora
    _validate_scientific_contract(result, items, payload)
    coverage = result['methods']['bulk_enrichment']['coverage'][0]
    assert coverage['background']['effective_count'] == 10

    result['methods']['background'] = 'complete_tested_gene_universe_intersected_with_collection'
    result['manifest']['methods'] = result['methods']
    Path(items['methods']['path']).write_text(json.dumps(result['methods']), encoding='utf-8')
    with pytest.raises(ValueError, match='bulk_ora_background_method_mismatch'):
        _validate_scientific_contract(result, items, payload)


def test_parent_rejects_a_truncated_bulk_enrichment_family_with_updated_member_hash(scoped_ora):
    payload, result, items = scoped_ora
    _validate_scientific_contract(result, items, payload)
    member = items['enrichment_results']
    path = Path(member['path'])
    rows = path.read_bytes().splitlines(keepends=True)
    assert len(rows) == 3
    changed = b''.join(rows[:-1])
    path.write_bytes(changed)
    member.update(sha256=hashlib.sha256(changed).hexdigest(), size_bytes=len(changed))
    with pytest.raises(ValueError, match='bulk_enrichment_term_family_mismatch'):
        _validate_scientific_contract(result, items, payload)


def test_parent_rejects_fabricated_ora_probabilities_even_if_bh_and_summary_agree(scoped_ora):
    payload, result, items = scoped_ora
    path = Path(items['enrichment_results']['path'])
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        rows = [row | {'p_value': '1', 'q_value': '1'} for row in reader]
        fields = reader.fieldnames
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fields, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    result['summary'].update(enrichment_status='no_significant_terms', significant_terms=0)
    result['manifest']['summary'] = result['summary']
    with pytest.raises(ValueError, match='bulk_ora_probability_mismatch'):
        _validate_scientific_contract(result, items, payload)


def test_parent_rejects_a_header_only_mapping_audit(scoped_ora):
    payload, result, items = scoped_ora
    path = Path(items['mapping_rows']['path'])
    path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
    with pytest.raises(ValueError, match='bulk_enrichment_mapping_audit_mismatch'):
        _validate_scientific_contract(result, items, payload)
