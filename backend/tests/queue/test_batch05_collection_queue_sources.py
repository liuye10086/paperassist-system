from tests.helpers.projection import check_projection,confirm_projection
"""Local prerequisite validation only; this module never starts Docker or a broker."""
from app.adapters.collection_store import CollectionStore
from app.db.database import database_connection
from app.domain.figure_workbench.contracts import SaveConfiguration, ConfirmProjection
from app.domain.report_collections.contracts import CollectionRequest
from app.domain.report_collections.execution import run_collection_word_task
from app.domain.report_collections.service import advance_pending
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from tests.queue.test_batch05_collection_queue import synthetic_figure, synthetic_explanation, build_state


def test_queue_synthetic_prerequisites_and_publication_gap(client, monkeypatch):
    workbench, project, result = source(client)
    args = project, result['file_id'], result['id']
    configured = workbench.save(*args, SaveConfiguration(config={
        'figure_kind': 'line', 'language': 'en', 'projection': {'x_column': 'A', 'y_column': 'C'}}))
    config_id = configured['version']['id']
    check = check_projection(workbench,*args, config_id)
    confirm_projection(workbench,*args, config_id, ConfirmProjection(input_sha256=check['input_sha256'], approved=True))
    repository = CollectionStore(workbench.assets)
    collection = repository.create(project, CollectionRequest(title='Queue prerequisites', language='en',
        items=[{'figure_config_version_id': config_id}]), 'queue-prerequisite')
    request_id = collection['versions'][0]['requests'][0]['id']
    state = lambda: build_state(repository, project, collection['id'], request_id)
    assert state()['missing'] == [{'figure_config_version_id': config_id, 'kind': 'figure'}]
    bundle = synthetic_figure(workbench, project, result, config_id, monkeypatch)
    advance_pending()
    assert state()['missing'] == [{'figure_id': bundle['figure']['id'], 'kind': 'explanation'}]
    with monkeypatch.context() as gap:
        gap.setattr('app.domain.report_collections.service.advance_pending', lambda **kwargs: 0)
        synthetic_explanation(workbench, project, result, config_id, bundle, gap)
    assert state()['task_id'] is None
    advance_pending()
    with database_connection() as db:
        task = db.execute('SELECT * FROM tasks WHERE id=%s', (state()['task_id'],)).fetchone()
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 2
        assert db.execute("SELECT count(*) AS n FROM task_attempts a JOIN tasks t ON t.id=a.task_id WHERE t.task_type='figure_projection'").fetchone()['n'] == 0
    completed = run_collection_word_task(task['id'], task['revision'])
    assert completed['status'] == 'succeeded'
    assert state()['report']['id']
