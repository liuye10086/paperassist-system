"""Frozen Visium projection compatibility, without science or services."""
from copy import deepcopy

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def envelope():
    return dict(schema_version=1, kind='bio_comparison', config={'kind': 'comparison'},
        identity={'task_id': 'same-task'}, sources=[dict(source_kind='bio_processed_dataset_version',
            source_id='same-source', role='expression', sha256='a' * 64, project_id='same-project',
            locator={'kind': 'object'}, metadata=dict(assay='visium', observation_level='spot',
                canonical_dataset_id='same-canonical', shape={'rows': 3, 'columns': 4}),
            members={'matrix': {'sha256': 'b' * 64, 'path': '/current/matrix'}})])


def project(current, frozen):
    import app.domain.bio_insights.service as module
    assert hasattr(module, 'frozen_envelope_projection'), 'Historical frozen envelope projection is missing'
    return module.frozen_envelope_projection(current, frozen)


def test_old_visium_envelope_omits_only_two_new_derived_fields_without_mutating_sources():
    from app.domain.bio_insights.service import portable
    current=envelope(); original=deepcopy(current); frozen=portable(current)
    del frozen['sources'][0]['metadata']['assay']
    del frozen['sources'][0]['metadata']['observation_level']
    saved=deepcopy(frozen)
    assert project(current, frozen)==frozen
    assert current==original and frozen==saved


def test_new_visium_envelope_retains_fields_and_detects_changes():
    from app.domain.bio_insights.service import portable
    current=envelope(); frozen=portable(current)
    assert project(current, frozen)==frozen
    current['sources'][0]['metadata']['assay']='single_cell'
    assert project(current, frozen)!=frozen


@pytest.mark.parametrize('change',['single_cell','other_metadata','sha256','locator','owner_project','missing_one'])
def test_historical_compatibility_cannot_hide_other_changes(change):
    from app.domain.bio_insights.service import portable
    current=envelope(); frozen=portable(current)
    del frozen['sources'][0]['metadata']['assay']
    if change!='missing_one':del frozen['sources'][0]['metadata']['observation_level']
    if change=='single_cell':current['sources'][0]['metadata'].update(assay='single_cell',observation_level='cell')
    if change=='other_metadata':current['sources'][0]['metadata']['canonical_dataset_id']='changed'
    if change=='sha256':current['sources'][0]['sha256']='c' * 64
    if change=='locator':current['sources'][0]['locator']={'kind': 'changed'}
    if change=='owner_project':current['sources'][0]['project_id']='another-project'
    assert project(current, frozen)!=frozen
