import csv
import hashlib
import json
from pathlib import Path

import pytest

from tests.domain.test_bio_b05_selection import write_comparisons


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.fixture
def payload(tmp_path):
    path = tmp_path / 'comparison_results.tsv'
    write_comparisons(path)
    content = path.read_bytes()
    output = tmp_path / 'output'
    output.mkdir()
    source = dict(source_kind='bio_insight_result_version', source_id='result', sha256='f' * 64,
                  metadata=dict(kind='comparison', species_taxon_id=9606, namespace='ensembl',
                                reference_version='fixed', inference_scope='sample_inference',
                                canonical_dataset_ids=['dataset'],
                                plan_config=dict(mode='bulk_counts', bulk_model='shared_wald_v1', contrasts=[
                                    dict(contrast_id='ab', groups=[{'label': 'A'}, {'label': 'B'}]),
                                    dict(contrast_id='ba', groups=[{'label': 'B'}, {'label': 'A'}]),
                                ])),
                  members={'comparison_results': dict(path=str(path), sha256=hashlib.sha256(content).hexdigest(),
                                                      size_bytes=len(content), role='table', format='tsv')})
    return dict(schema_version=1, kind='bio_candidate', output_directory=str(output),
                identity={'source_digest': 'e' * 64}, sources=[source],
                config=dict(kind='candidate', result_source_ids=['result'], source_contrasts={'result': 'ab'},
                            primary_result_source_id='result', steps=[], bulk_selection={'contrast_id': 'ab'},
                            bulk_top_n=2))


def published_outputs(result):
    return {member['key']: Path(member['path']) for member in result['outputs']}


def read_rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def test_bulk_candidate_run_freezes_full_ranked_set_evidence_and_separate_top_n(payload):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result

    result = validate_result(run(payload), payload['output_directory'], payload)
    outputs = published_outputs(result)
    ranked = read_rows(outputs['candidate_results'])
    top = read_rows(outputs['bulk_candidate_top'])
    evidence = read_rows(outputs['candidate_evidence'])
    assert [row['feature_id'] for row in ranked] == ['gA', 'gB', 'gC']
    assert [row['rank'] for row in ranked] == ['1', '2', '3']
    assert top == ranked[:2]
    assert [row['primary_q'] for row in ranked] == ['0', '0', '0']
    assert [row['row_key'] for row in evidence] == ['ab:gA', 'ab:gB', 'ab:gC']
    assert [row['direction'] for row in evidence] == ['1', '1', '-1']
    assert all(row['q_column'] == 'q_within_contrast' for row in evidence)
    assert json.loads(outputs['candidate_sets'].read_text()) == {
        'selected': ['gA', 'gB', 'gC'], 'source_sets': {'result': ['gA', 'gB', 'gC']}}
    frozen = json.loads(outputs['bulk_candidate_selection'].read_text())
    assert frozen == result['methods']['bulk_selection']
    assert frozen['comparison_sha256'] == payload['sources'][0]['members']['comparison_results']['sha256']
    assert (frozen['numerator'], frozen['denominator'], frozen['q_threshold'], frozen['minimum_absolute_effect']) == (
        'A', 'B', 0.05, 1.0)
    assert result['summary']['candidate_count'] == 3
    assert result['summary']['top_n'] == 2 and result['summary']['displayed_count'] == 2


@pytest.mark.parametrize(('selection', 'features'), [
    ({'direction': 'down'}, ['gC']),
    ({'q_column': 'original_method_adjustment'}, []),
])
def test_bulk_candidate_run_supports_fewer_than_n_and_empty_results(payload, selection, features):
    from app.adapters.bio_insights_engine.pipeline import run

    payload['config']['bulk_top_n'] = 20
    payload['config']['bulk_selection'].update(selection)
    result = run(payload)
    outputs = published_outputs(result)
    assert [row['feature_id'] for row in read_rows(outputs['candidate_results'])] == features
    assert [row['feature_id'] for row in read_rows(outputs['bulk_candidate_top'])] == features
    assert result['summary']['candidate_count'] == result['summary']['displayed_count'] == len(features)
    assert result['summary']['empty_result'] == (not features)
    if not features:
        reasons = {row['feature_id']: row['reason'] for row in read_rows(outputs['candidate_exclusions'])}
        assert reasons['gA'] == 'missing_metric'
        assert reasons['gExcluded'] == 'excluded'
        assert reasons['gFail'] == 'not_computable'


def test_bulk_candidate_run_rejects_unreviewed_source(payload):
    from app.adapters.bio_insights_engine.pipeline import run

    payload['sources'][0]['metadata']['plan_config'].pop('bulk_model')
    with pytest.raises(ValueError, match='reviewed_bulk_comparison_required'):
        run(payload)


@pytest.mark.parametrize('key', ['candidate_results', 'bulk_candidate_top'])
def test_parent_rejects_truncation_even_with_matching_member_and_manifest_hashes(payload, key):
    from app.adapters.bio_engine.manifest import canonical
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from app.core.exceptions import StorageError

    result = run(payload)
    outputs = {member['key']: member for member in result['outputs']}
    member = outputs[key]
    path = Path(member['path'])
    content = b''.join(path.read_bytes().splitlines(keepends=True)[:-1])
    path.write_bytes(content)
    member.update(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    manifest = result['manifest']
    manifest['members'] = [{name: value for name, value in item.items() if name != 'path'}
                           for item in result['outputs'] if item['key'] != 'manifest']
    manifest_bytes = canonical(manifest)
    manifest_member = outputs['manifest']
    Path(manifest_member['path']).write_bytes(manifest_bytes)
    manifest_member.update(size_bytes=len(manifest_bytes), sha256=hashlib.sha256(manifest_bytes).hexdigest())
    with pytest.raises(StorageError) as error:
        validate_result(result, payload['output_directory'], payload)
    assert str(error.value.__cause__) == 'bulk_candidate_member_mismatch:' + key
