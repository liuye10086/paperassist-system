from contextlib import nullcontext
import json
import re
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from tests.domain.test_bio_b05_selection import write_comparisons


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.fixture
def published_bulk(monkeypatch, tmp_path):
    from app.adapters.bio_insights_store import BioInsightsObjects
    from app.adapters.task_store import TaskStore
    from app.api.bio_insights import router
    from app.api.bio_datasets import get_request_project_store
    from app.core.exceptions import StorageError
    from app.domain.bio_insights.service import BioInsightsService

    assets = SimpleNamespace(owner_id='owner', db_config=object(), directory=tmp_path)
    objects = BioInsightsObjects(tmp_path)
    path = tmp_path / 'comparisons.tsv'
    write_comparisons(path)
    table = objects.describe(str(uuid4()), path.read_bytes())
    objects.write(table, path.read_bytes())
    member = dict(id='member', key='comparison_results', role='table', format='tsv',
                  storage_object_id='table', sha256=table['sha256'], size_bytes=table['size_bytes'])
    manifest_data = json.dumps({'members': [member]}).encode()
    manifest = objects.describe(str(uuid4()), manifest_data, json=True)
    objects.write(manifest, manifest_data)
    plan_config = dict(mode='bulk_counts', bulk_model='shared_wald_v1', contrasts=[
        dict(contrast_id='ab', groups=[{'label': 'A'}, {'label': 'B'}]),
        dict(contrast_id='ba', groups=[{'label': 'B'}, {'label': 'A'}]),
    ])
    plan = dict(config_json=plan_config)
    task = dict(id='task', status='succeeded')
    result = dict(id='result', kind='comparison', provenance='system_computed', inference_scope='sample_inference',
                  plan_version_id='plan', task_id='task', manifest_object_id='manifest',
                  manifest_sha256=manifest['sha256'])
    records = {
        ('projects', ('project', 'owner')): {'id': 'project'},
        ('tasks', ('task', 'owner', 'owner')): task,
        ('bio_insight_result_versions', ('result', 'project', 'owner')): result,
        ('bio_insight_plan_versions', ('plan', 'project', 'owner')): plan,
        ('bio_insight_result_members', ('result', 'project', 'owner')): [member],
        ('storage_objects', ('manifest', 'project', 'owner')): manifest,
        ('storage_objects', ('table', 'project', 'owner')): table,
    }

    def execute(query, parameters):
        table_name = re.search(r'\bFROM (\w+)', query).group(1)
        value = records.get((table_name, parameters))
        return SimpleNamespace(fetchone=lambda: value, fetchall=lambda: value)

    lineage_checks = []

    def require_sources(self, db, source_task, *, runtime):
        lineage_checks.append((source_task['id'], runtime))

    monkeypatch.setattr(TaskStore, 'connection', lambda self: nullcontext(SimpleNamespace(execute=execute)))
    monkeypatch.setattr(BioInsightsService, 'require_sources', require_sources)
    api = FastAPI()
    api.include_router(router)
    api.dependency_overrides[get_request_project_store] = lambda: assets

    @api.exception_handler(StorageError)
    async def storage_error(request: Request, error: StorageError):
        return JSONResponse({'code': error.code}, status_code=error.status)

    with TestClient(api) as client:
        yield SimpleNamespace(client=client, plan=plan_config, sha256=table['sha256'],
                              table_path=objects.path(table['object_key']), lineage_checks=lineage_checks)


PATH = '/api/v1/projects/project/bio-insight-results/result/bulk-comparisons'


def test_bulk_comparison_route_reads_the_published_table_with_query_validation(published_bulk):
    fixture = published_bulk
    response = fixture.client.get(PATH, params={'subset': 'deg', 'page_size': 1})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['contrast_id'] == 'ab' and result['matched_total'] == 3
    assert result['items'][0]['feature_id'] == 'gA' and result['items'][0]['q_within_contrast'] == '0'
    assert result['sha256'] == fixture.sha256
    assert fixture.lineage_checks == [('task', False)]
    other = fixture.client.get(PATH, params={'contrast_id': 'ba', 'subset': 'down', 'search': 'gA'})
    assert other.status_code == 200, other.text
    assert [row['contrast_id'] for row in other.json()['feature_matches']] == ['ab', 'ba']
    assert fixture.client.get(PATH, params={'q_column': 'original_q'}).status_code == 422
    assert fixture.client.get(PATH, params={'q_threshold': 'nan'}).status_code == 422
    assert fixture.client.get(PATH, params={'page_size': 101}).status_code == 422


def test_bulk_comparison_route_rejects_missing_comparisons_legacy_results_and_tampering(published_bulk):
    fixture = published_bulk
    assert fixture.client.get(PATH.replace('/project/', '/other/')).status_code == 404
    assert fixture.client.get(PATH, params={'contrast_id': 'not-frozen'}).status_code == 404
    fixture.plan.pop('bulk_model')
    assert fixture.client.get(PATH).status_code == 422
    fixture.plan['bulk_model'] = 'shared_wald_v1'
    content = fixture.table_path.read_bytes()
    fixture.table_path.write_bytes(content.replace(b'Missing Q', b'Missing Z', 1))
    assert fixture.client.get(PATH).status_code == 409
