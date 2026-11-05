from copy import deepcopy
import pytest

from app.domain.research_results.frozen_projection import frozen_source_projection, matches_frozen_source


def source(kind, content):
    return dict(schema_version=1, source_kind=kind, source_id='fixed-id', sha256='a'*64, content=content)


def test_only_known_additions_are_projected_without_mutating_either_input():
    old = source('bio_figure_version', {'figure': {'task': {'id': 'task', 'status': 'succeeded'}}})
    current = deepcopy(old)
    current['content']['figure']['task'].update(result_bio_resource_version_id=None, result_bio_insight_result_version_id=None)
    saved = deepcopy(current)
    assert matches_frozen_source(current, old)
    projected = frozen_source_projection(current, old)
    projected['content']['figure']['task']['status'] = 'changed by caller'
    assert current == saved and old['content']['figure']['task']['status'] == 'succeeded'
    current['content']['figure']['task']['result_bio_resource_version_id'] = 'actual-new-result'
    assert not matches_frozen_source(current, old)


@pytest.mark.parametrize('change', ['sha256', 'source_id', 'schema_version', 'unknown', 'value', 'missing'])
def test_legacy_layers_compatibility_preserves_all_other_checks(change):
    old = source('bio_processed_dataset_version', {'summary': {'observations': 3}})
    current = deepcopy(old); current['content']['layers'] = {'counts': {'shape': [3, 5]}}
    assert matches_frozen_source(current, old)
    if change == 'value': current['content']['summary']['observations'] = 4
    elif change == 'missing': current['content'].pop('summary')
    elif change == 'unknown': current['content']['unexpected_new_field'] = None
    elif change == 'schema_version': current[change] = 2
    else: current[change] = 'different'
    assert not matches_frozen_source(current, old)


def test_existing_layers_and_unrelated_source_kinds_are_never_ignored():
    old = source('bio_processed_dataset_version', {'layers': {'counts': [3, 5]}})
    current = deepcopy(old); current['content']['layers']['counts'] = [4, 5]
    assert not matches_frozen_source(current, old)
    old = source('original_file', {})
    assert not matches_frozen_source({**old, 'content': {'layers': {}}}, old)
