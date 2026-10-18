"""Summary lists exact configured PNGs and immutable collection exports read-only."""
import hashlib

from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_batch05_collection_pipeline import complete_collection
from tests.integration.test_project_ownership import account_client
from app.domain.report_collections.execution import run_collection_word_task


def test_summary_keeps_collection_exports_and_actual_figure_kind_with_private_downloads(client, monkeypatch):
    repository, project, result, state, provider, prose = complete_collection(client, monkeypatch)
    second = repository.export(project, state['id'], state['current_version_id'], 'second-summary-export')
    assert run_collection_word_task(second['task_id'], 1, config=repository.store.db_config,
                                    directory=repository.store.directory)['status'] == 'succeeded'
    endpoint = f'/api/v1/projects/{project}/summary'
    provider_posts, explanation_posts = list(provider.posts), list(prose.posts)
    with repository.store.connection() as db:
        before = [dict(row) for row in db.execute('SELECT id,status,revision FROM tasks ORDER BY id')]
    pages = [client.get(endpoint, params={'artifact_page': i, 'page_size': 1}).json()
             for i in (1, 2, 3)]
    assert all(page['artifacts']['total'] == 3 for page in pages)
    items = [page['artifacts']['items'][0] for page in pages]
    assert len({item['id'] for item in items}) == 3
    reports = [item for item in items if item['collection_id']]
    assert len(reports) == 2
    assert {item['export_revision'] for item in reports} == {1, 2}
    for item in reports:
        assert item['analysis_run_id'] is None and item['setup_revision'] is None
        assert item['figure_id'] is None and item['explanation_id'] is None
        assert item['file_id'] == result['file_id']
        assert item['collection_id'] == state['id'] and item['collection_version_id'] == state['current_version_id']
        assert item['collection_revision'] == 1 and item['collection_title'] == 'Confirmed report'
        assert item['result_count'] == 1
        assert item['download_url'] == f"/api/v1/projects/{project}/report-collections/{state['id']}/reports/{item['id']}/download"
    figure = next(item for item in items if item['kind'] == 'figure')
    assert figure['figure_kind'] == 'line' and figure['download_filename'].startswith('line-')
    assert figure['download_url'].endswith(f"/figure-workbench/figures/{figure['id']}/png")
    for item in items:
        download = client.get(item['download_url'])
        assert download.status_code == 200, download.text
        assert hashlib.sha256(download.content).hexdigest() == item['sha256']
    assert client.get(endpoint).json()['artifacts']['total'] == 3
    with repository.store.connection() as db:
        assert [dict(row) for row in db.execute('SELECT id,status,revision FROM tasks ORDER BY id')] == before
    assert provider.posts == provider_posts and prose.posts == explanation_posts
    with account_client('other-summary@paperassist.local', 'user')[0] as other:
        for path in [endpoint, *[item['download_url'] for item in items]]:
            assert other.get(path).status_code == 404
