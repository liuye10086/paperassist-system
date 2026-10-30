"""Public route coverage before the gated business implementation."""
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_b02_routes_are_explicit_and_raw_and_processed_sources_are_separate():
    from app.main import app
    paths = app.openapi()['paths']
    prefix = '/api/v1/projects/{project_id}'
    expected = {
        '/bio-analysis-capabilities': 'get',
        '/bio-observation-map-table-previews': 'post',
        '/bio-observation-maps': 'post',
        '/bio-observation-maps/{set_id}/versions': 'post',
        '/bio-observation-maps/{set_id}/versions/{version_id}': 'get',
        '/bio-analysis-setups': 'post',
        '/bio-analysis-setups/{setup_id}/recipes': 'post',
        '/bio-analysis-setups/{setup_id}': 'get',
        '/bio-analysis-setups/{setup_id}/recipes/{version_id}': 'get',
        '/bio-analysis-runs': 'post',
        '/bio-analysis-runs/{run_id}': 'get',
        '/bio-analysis-runs/{run_id}/confirm': 'post',
        '/bio-processed-datasets/{version_id}': 'get',
        '/bio-processed-datasets/{version_id}/tables/{key}': 'get',
        '/bio-processed-datasets/{version_id}/coordinates': 'get',
        '/bio-processed-datasets/{version_id}/matrix-preview': 'get',
        '/bio-requests/{request_key}': 'get',
    }
    for suffix, method in expected.items():
        assert method in paths.get(prefix + suffix, {}), f'{method} {prefix}{suffix} missing'
