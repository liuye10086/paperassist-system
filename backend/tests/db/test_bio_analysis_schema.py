"""Metadata contract first; PostgreSQL isolation tests added with migration."""
import pytest
from app.db.schema import metadata


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


TABLES = ('bio_observation_map_sets','bio_observation_map_versions','bio_analysis_setups',
          'bio_analysis_recipe_versions','bio_analysis_runs','bio_processed_dataset_versions',
          'bio_analysis_artifacts','bio_annotation_sets','bio_annotation_versions',
          'bio_annotation_evidence','bio_figure_versions','bio_figure_members')


def test_all_twelve_persistent_tables_and_scoped_result_foreign_keys_exist():
    assert set(TABLES) <= set(metadata.tables), 'B02 persistent normalized tables missing'
    for name in TABLES:
        assert {'id','project_id'} <= set(metadata.tables[name].c.keys())
    tasks = metadata.tables['tasks']
    for column in ('result_bio_processed_dataset_version_id','result_bio_figure_version_id'):
        assert column in tasks.c
        assert any(column in fk.column_keys and 'project_id' in fk.column_keys for fk in tasks.foreign_key_constraints)


def test_default_figures_allow_multiple_figures_for_the_same_analysis_task():
    assert 'bio_figure_versions' in metadata.tables, 'B02 figure persistence missing'
    table = metadata.tables['bio_figure_versions']
    assert not any(getattr(c,'columns',None) is not None and list(c.columns.keys()) == ['task_id']
                   for c in table.constraints)


def test_annotation_evidence_and_every_leaf_have_real_scoped_foreign_keys():
    assert set(TABLES) <= set(metadata.tables), 'B02 persistent normalized tables missing'
    evidence = metadata.tables['bio_annotation_evidence']
    for column in ('annotation_version_id', 'analysis_artifact_id', 'file_id'):
        assert any(column in fk.column_keys and 'project_id' in fk.column_keys
                   for fk in evidence.foreign_key_constraints)
    for table, column in (('bio_observation_map_versions','mapping_object_id'),
                          ('bio_processed_dataset_versions','manifest_object_id'),
                          ('bio_analysis_artifacts','storage_object_id'),
                          ('bio_annotation_versions','geometry_object_id'),
                          ('bio_annotation_versions','assignments_object_id'),
                          ('bio_figure_members','storage_object_id')):
        assert any(column in fk.column_keys and 'project_id' in fk.column_keys
                   for fk in metadata.tables[table].foreign_key_constraints)


def test_recipe_mapping_and_annotation_cannot_cross_raw_versions_in_same_project():
    assert set(TABLES) <= set(metadata.tables), 'B02 persistent normalized tables missing'
    for table, column in (('bio_analysis_recipe_versions','observation_map_version_id'),
                          ('bio_annotation_sets','processed_dataset_version_id')):
        assert any({column,'raw_dataset_version_id','project_id'} <= set(fk.column_keys)
                   for fk in metadata.tables[table].foreign_key_constraints)
