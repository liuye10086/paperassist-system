"""Local lineage graph retains the direct parent and complete receipt identity."""
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_frozen_quality_side_relationships_keep_both_prepared_versions():
    from app.domain.file_lifecycle.references import frozen_references
    references=set(frozen_references({'prepared_dataset_id':'child','base_prepared_dataset_id':'base'}))
    assert references=={('prepared_dataset_versions','child'),('prepared_dataset_versions','base')}


def test_manifest_storage_key_is_fingerprinted_without_exposing_path():
    from app.domain.file_lifecycle.references import facts
    first=facts({'manifest_object_key':'quality-manifests/one.json','manifest_sha256':'a'*64})
    second=facts({'manifest_object_key':'quality-manifests/two.json','manifest_sha256':'a'*64})
    assert first!=second
    assert 'manifest_object_key' not in first and 'manifest_object_key_digest' in first
