from pathlib import Path
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_cache_reuses_complete_artifact_and_repairs_corruption(tmp_path):
    from app.domain.bio_insights.bulk_delivery_cache import ArtifactCache
    cache = ArtifactCache(tmp_path, ttl=60, budget=1024)
    calls = []
    def build(folder):
        calls.append(1)
        (folder / 'payload').write_bytes(b'fixed')
        return {'facts_digest': 'a' * 64}
    first = cache.obtain('a' * 64, build)
    assert cache.obtain('a' * 64, build)['metadata'] == first['metadata']
    assert len(calls) == 1
    (first['path'] / 'payload').write_bytes(b'wrong')
    assert cache.obtain('a' * 64, build)['path'].joinpath('payload').read_bytes() == b'fixed'
    assert len(calls) == 2


def test_failed_build_never_publishes_and_retry_works(tmp_path):
    from app.domain.bio_insights.bulk_delivery_cache import ArtifactCache
    cache = ArtifactCache(tmp_path)
    def fail(folder):
        (folder / 'payload').write_bytes(b'partial')
        raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError):
        cache.obtain('a' * 64, fail)
    assert cache.read('a' * 64) is None
    assert not list(tmp_path.glob('building-*'))


def test_cache_expiry_and_budget_only_remove_derived_entries(tmp_path):
    from app.domain.bio_insights.bulk_delivery_cache import ArtifactCache
    cache = ArtifactCache(tmp_path, ttl=0, budget=1024)
    original = tmp_path / 'original-data'
    original.write_bytes(b'keep')
    def build(folder):
        (folder / 'payload').write_bytes(b'fixed')
        return {}
    cache.obtain('a' * 64, build)
    assert cache.read('a' * 64) is None
    cache.prune()
    assert original.read_bytes() == b'keep'

def test_sensitivity_disk_index_reuses_pages_without_loading_source_rows(tmp_path, monkeypatch):
    import io
    from app.domain.bio_insights.bulk_sensitivity_index import compare_index
    from app.domain.bio_insights.contracts import BulkSelection
    from tests.domain.test_bio_b07_workflow import write_table
    from tests.domain.test_bio_b05_selection import saved_row
    table = tmp_path / 'table.tsv'
    write_table(table, [saved_row('g2', '-2', '.01'), saved_row('g1', '2', '.01')])
    selection = BulkSelection(contrast_id='ab')
    index = tmp_path / 'index.sqlite'
    first = compare_index(index, table, table, selection, selection, ('A', 'B'), page=1, page_size=1)
    assert first['items'][0]['feature_id'] == 'g1'
    table.unlink()
    changes = io.StringIO()
    second = compare_index(index, table, table, selection, selection, ('A', 'B'), page=2, page_size=1, change_stream=changes)
    assert second['items'][0]['feature_id'] == 'g2'
    assert second['counts'] == first['counts']
    assert len(changes.getvalue().splitlines()) == 3

def test_prepared_download_routes_keep_post_interoperability():
    from app.main import app
    prefix = '/api/v1/projects/{project_id}/bulk-workflow/delivery'
    routes = app.openapi()['paths']
    assert 'post' in routes[prefix + '/prepare/{kind}']
    assert 'get' in routes[prefix + '/prepared/{kind}/{artifact_id}']
    assert 'post' in routes[prefix + '/report.docx']
    assert 'post' in routes[prefix + '/reproducibility-package']

from tests.domain.test_bio_b07_bulk_delivery import published


def test_api_preparation_reuses_statistics_word_and_archive_and_rechecks_sources(published, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.api import bulk_workflow as api
    from app.domain.bio_insights import bulk_delivery
    from app.domain.bio_insights.bulk_delivery_archive import BulkDeliveryArchive
    from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest, BulkDownloadRequest
    from app.core.exceptions import StorageError
    from tests.domain.test_bio_b07_bulk_delivery import service
    service(published, monkeypatch)
    published.assets.db_config = SimpleNamespace(url=SimpleNamespace(database='test'), schema='isolated')
    monkeypatch.setattr(api, 'heavy_slot', lambda *a: nullcontext())
    calls = dict(stats=0, word=0, archive=0)
    original = bulk_delivery._report_contrasts
    def stats(*args):
        calls['stats'] += 1
        return original(*args)
    monkeypatch.setattr(bulk_delivery, '_report_contrasts', stats)
    original_docx = bulk_delivery.BulkDeliveryService.docx
    def docx(self, *args, **kwargs):
        calls['word'] += 1
        return original_docx(self, *args, **kwargs)
    monkeypatch.setattr(bulk_delivery.BulkDeliveryService, 'docx', docx)
    def archive(self, project, facts, word, *, destination, **kwargs):
        calls['archive'] += 1
        assert word[:2] == b'PK'
        destination.write_bytes(b'fixed archive')
        return dict(file=destination.open('rb'), manifest_sha256='a'*64, analysis_inputs_self_contained=True)
    monkeypatch.setattr(BulkDeliveryArchive, 'export_delivery', archive)
    request = BulkDeliveryRequest(comparison_version_id='comparison')
    facts = api.preview_delivery('project', request, published.assets)
    download = BulkDownloadRequest(**request.model_dump(), facts_digest=facts['facts_digest'])
    word = api.prepare_download('project', 'word', download, published.assets)
    packed = api.prepare_download('project', 'archive', download, published.assets)
    api.prepare_download('project', 'archive', download, published.assets)
    assert calls == dict(stats=1, word=1, archive=1)
    response = api.download_prepared('project', 'archive', packed['download_url'].split('/')[-1], published.assets)
    assert response.headers['content-length'] == '13'
    # Close the opened streaming response without relying on a client consuming it.
    response.background.func()
    member = next(item for item in published.records['bio_insight_result_members', ('comparison', 'project', 'owner')]
                  if item['key'] == 'comparison_results')
    source = published.assets.directory / member['object_key']
    original_bytes = source.read_bytes()
    source.write_bytes(b'corrupt cached source')
    with pytest.raises(StorageError):
        api.download_prepared('project', 'word', word['download_url'].split('/')[-1], published.assets)
    source.write_bytes(original_bytes)
    published.records['tasks', ('comparison', 'owner', 'owner')]['status'] = 'failed'
    with pytest.raises(StorageError):
        api.download_prepared('project', 'word', word['download_url'].split('/')[-1], published.assets)
    assert calls == dict(stats=1, word=1, archive=1)

def test_open_stream_survives_expiry_and_new_generation(tmp_path):
    from app.domain.bio_insights.bulk_delivery_cache import ArtifactCache
    cache = ArtifactCache(tmp_path, ttl=60)
    def build(folder):
        (folder / 'payload').write_bytes(b'original')
        return {}
    first = cache.obtain('a'*64, build)
    with (first['path'] / 'payload').open('rb') as stream:
        cache.ttl = 0
        second = cache.obtain('a'*64, build)
        assert first['path'] != second['path']
        assert stream.read() == b'original'
        assert (second['path'] / 'payload').read_bytes() == b'original'

def test_cache_budget_is_shared_across_project_scopes(tmp_path):
    from app.domain.bio_insights.bulk_delivery_cache import ArtifactCache
    left = ArtifactCache(tmp_path / ('a'*64), pool=tmp_path, budget=1500)
    right = ArtifactCache(tmp_path / ('b'*64), pool=tmp_path, budget=1500)
    def build(folder):
        (folder / 'payload').write_bytes(b'x'*800)
        return {}
    left.obtain('c'*64, build)
    right.obtain('d'*64, build)
    assert left.read('c'*64) is None
    assert right.read('d'*64) is not None


def test_cache_budget_includes_the_generation_manifest(tmp_path):
    from app.core.exceptions import StorageError
    from app.domain.bio_insights.bulk_delivery_cache import ArtifactCache

    cache = ArtifactCache(tmp_path, budget=100)
    def build(folder):
        (folder / 'payload').write_bytes(b'x')
        return {}
    with pytest.raises(StorageError) as error:
        cache.obtain('a'*64, build)
    assert error.value.code == 'bio_insight_limit_exceeded'
    assert cache.read('a'*64) is None

def test_existing_bulk_word_route_uses_shared_slot_and_keeps_language(published, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app.api import bulk_workflow as api, bio_insights
    from app.domain.bio_insights import bulk_delivery
    from tests.domain.test_bio_b07_bulk_delivery import service
    service(published, monkeypatch)
    published.assets.db_config = SimpleNamespace(url=SimpleNamespace(database='test'), schema='isolated')
    published.records['bio_insight_plan_versions', ('comparison-plan', 'project', 'owner')]['config_json'] = published.inputs['comparison']['config']
    entries = []
    @contextmanager
    def slot(*args):
        entries.append('enter')
        yield
        entries.append('exit')
    monkeypatch.setattr(api, 'heavy_slot', slot)
    response = bio_insights.insight_word_report('project', 'comparison', published.assets, None, 'en')
    assert entries == ['enter', 'exit']
    assert response.media_type == api.WORD_MEDIA_TYPE
    assert response.headers['x-bulk-facts-sha256']
    if response.background:
        response.background.func()

def test_archive_can_finish_when_word_cache_expires_during_build(published, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.api import bulk_workflow as api
    from app.domain.bio_insights.bulk_delivery_archive import BulkDeliveryArchive
    from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest, BulkDownloadRequest
    from tests.domain.test_bio_b07_bulk_delivery import service
    service(published, monkeypatch)
    published.assets.db_config = SimpleNamespace(url=SimpleNamespace(database='test'), schema='isolated')
    monkeypatch.setattr(api, 'heavy_slot', lambda *args: nullcontext())
    original_cache = api.cache_for
    def immediate(*args):
        cache = original_cache(*args)
        cache.ttl = 0
        return cache
    monkeypatch.setattr(api, 'cache_for', immediate)
    def archive(self, project, facts, word, *, destination, **kwargs):
        assert word[:2] == b'PK'
        destination.write_bytes(b'archive')
        return dict(file=destination.open('rb'), manifest_sha256='a'*64, analysis_inputs_self_contained=True)
    monkeypatch.setattr(BulkDeliveryArchive, 'export_delivery', archive)
    request = BulkDeliveryRequest(comparison_version_id='comparison')
    facts = api.preview_delivery('project', request, published.assets)
    result = api.prepare_download('project', 'archive', BulkDownloadRequest(**request.model_dump(), facts_digest=facts['facts_digest']), published.assets)
    assert result['facts_digest'] == facts['facts_digest']

def test_prepared_stream_survives_eviction_during_reauthorization(published, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.api import bulk_workflow as api
    from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest, BulkDownloadRequest
    from tests.domain.test_bio_b07_bulk_delivery import service
    service(published, monkeypatch)
    published.assets.db_config = SimpleNamespace(url=SimpleNamespace(database='test'), schema='isolated')
    monkeypatch.setattr(api, 'heavy_slot', lambda *args: nullcontext())
    request = BulkDeliveryRequest(comparison_version_id='comparison')
    facts = api.preview_delivery('project', request, published.assets)
    prepared = api.prepare_download('project', 'word', BulkDownloadRequest(**request.model_dump(), facts_digest=facts['facts_digest']), published.assets)
    original = api.resolve_delivery
    def expire(*args, **kwargs):
        resolved = original(*args, **kwargs)
        cache = api.cache_for(published.assets, 'project', 'word')
        cache.ttl = 0
        cache.prune()
        return resolved
    monkeypatch.setattr(api, 'resolve_delivery', expire)
    response = api.download_prepared('project', 'word', prepared['download_url'].split('/')[-1], published.assets)
    assert int(response.headers['content-length']) > 1000
    response.background.func()

def test_corrupt_metadata_and_missing_payload_are_rebuilt(tmp_path):
    import json
    from app.domain.bio_insights.bulk_delivery_cache import ArtifactCache
    cache = ArtifactCache(tmp_path)
    calls = []
    def build(folder):
        calls.append(1)
        (folder / 'payload').write_bytes(b'fixed')
        return {'request': {'comparison_version_id': 'fixed'}}
    entry = cache.obtain('a'*64, build)
    manifest = entry['path'] / 'complete.json'
    value = json.loads(manifest.read_text())
    value['metadata'] = {'request': {'comparison_version_id': 'changed'}}
    manifest.write_text(json.dumps(value))
    assert cache.read('a'*64) is None
    entry = cache.obtain('a'*64, build)
    (entry['path'] / 'payload').unlink()
    assert cache.read('a'*64) is None
    assert cache.obtain('a'*64, build)['metadata']['request']['comparison_version_id'] == 'fixed'
    assert len(calls) == 3

def test_waiting_heavy_slot_does_not_reserve_business_pool_connection(monkeypatch):
    from contextlib import contextmanager, nullcontext
    from types import SimpleNamespace
    from app.domain.bio_insights import bulk_delivery_cache as cache
    active = []
    @contextmanager
    def business():
        active.append(True)
        try:
            yield SimpleNamespace(execute=lambda *args: None)
        finally:
            active.pop()
    store = SimpleNamespace(connection=business, require_project=lambda *args: None)
    monkeypatch.setattr(cache, 'BioInsightsStore', lambda assets: SimpleNamespace(store=store))
    raw = SimpleNamespace(begin=lambda: nullcontext(), exec_driver_sql=lambda *args: None)
    monkeypatch.setattr(cache, '_slot_engine', lambda url: SimpleNamespace(connect=lambda: nullcontext(raw)), raising=False)
    assets = SimpleNamespace(db_config=SimpleNamespace(url=SimpleNamespace(database='isolated'), schema='test'))
    with cache.heavy_slot(assets, 'project'):
        assert not active
