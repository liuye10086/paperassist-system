"""New collection freeze uses the explanation generated today; no DB or HTTP."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.adapters.collection_store import CollectionStore
from app.domain.figure_workbench.explanations import version_for
from app.domain.report_collections.contracts import CollectionRequest
from tests.domain.test_batch05_collection_contracts import bundle


def repository_and_item(monkeypatch, contract, *, has_figure):
    item = bundle(language='en')
    item['result']['source']['file_id'] = 'file'
    item['configuration']['figure_contract'] = contract
    item['configuration']['config'] = {'language': 'en'}
    figure = item['figure']
    figure['engine'] = {'id': 'openai_figure_workbench_v' + str(contract)}
    if contract > 1:
        figure['presentation'] = {'schema_version': contract - 1}
    item['explanation'] = None
    if not has_figure:
        item['figure'] = None
    class Database:
        def execute(self, *args):
            return self
        def fetchone(self):
            return {'recipe_json': {}, 'summary_json': {}}
    @contextmanager
    def connection():
        yield Database()
    repository = object.__new__(CollectionStore)
    repository.store = SimpleNamespace(owner_id='owner', connection=connection)
    monkeypatch.setattr('app.domain.dataset_profile.service.DatasetProfileService.profile',
                        lambda *args: {'record_count': 3})
    monkeypatch.setattr(repository, 'read_bundle', lambda *args: repository.enrich_bundle('project', deepcopy(item)))
    monkeypatch.setattr(repository, 'read_config_bundle', lambda *args: repository.enrich_bundle('project', deepcopy(item)))
    return repository, item, figure


@pytest.mark.parametrize('contract', [1, 2, 3, 4])
@pytest.mark.parametrize('has_figure', [False, True])
def test_new_missing_dependency_freezes_the_actual_generation_version(monkeypatch, contract, has_figure):
    repository, item, figure = repository_and_item(monkeypatch, contract, has_figure=has_figure)
    expected = version_for(figure)
    selection = {'figure_id': figure['id']} if has_figure else {'figure_config_version_id': item['configuration']['id']}
    # This explicit engine is the frontend's actual missing-explanation request.
    request = CollectionRequest(title='New report', language='en', items=[selection | {'explanation_engine': expected}])
    frozen = repository.requested_snapshot('project', request)
    assert not frozen['ready']
    assert frozen['items'][0]['dependency_engine'] == expected
    assert frozen['items'][0]['explanation'] is None
    assert frozen['missing'][0]['kind'] == ('explanation' if has_figure else 'figure')


def test_new_collection_with_exact_historical_v4_explanation_keeps_that_engine(monkeypatch):
    repository, item, figure = repository_and_item(monkeypatch, 3, has_figure=True)
    historical = bundle(language='en')['explanation']
    historical['engine']['id'] = 'figure_explanation_v4'
    item['explanation'] = historical
    request = CollectionRequest(title='Historical exact selection', language='en', items=[{
        'figure_id': figure['id'], 'explanation_id': historical['id']}])
    frozen = repository.requested_snapshot('project', request)
    assert frozen['ready']
    assert frozen['items'][0]['dependency_engine'] == 'figure_explanation_v4'
    assert frozen['items'][0]['explanation'] == historical


def test_installed_catalog_reports_current_figure_and_explanation_ranges(monkeypatch):
    from app.domain.admin_configuration import catalog
    from app.domain.admin_configuration.contracts import Basic
    monkeypatch.setattr(catalog, 'defaults', lambda: ({'basic': Basic().model_dump()}, {}))
    monkeypatch.setattr(catalog, 'capability_version', lambda: 'synthetic-capability')
    monkeypatch.setattr('app.domain.journals.configuration.source_directory', lambda: [])
    monkeypatch.setattr('app.workers.config.concurrency_ceiling', lambda: 1)
    templates = catalog.metadata()['installed']['templates']
    assert 'openai_figure_workbench_v1-v4' in templates
    assert 'figure_explanation_v1-v5' in templates
    assert 'openai_figure_workbench_v1-v3' not in templates
    assert 'figure_explanation_v1-v4' not in templates
