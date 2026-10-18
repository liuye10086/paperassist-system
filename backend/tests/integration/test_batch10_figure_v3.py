"""v3 publication and local export; every model response is a synthetic fixture."""
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree

from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_execution import queued_figure, FigureExplanationProvider
from tests.integration.test_batch06_pipeline import IndependentV2LineProvider, checked_policy
from app.adapters.figure_workbench_store import read_bundle
from app.adapters.collection_store import CollectionStore
from app.domain.figure_workbench.execution import run_figure_workbench_task, run_figure_explanation_task
from app.domain.figure_workbench.explanations import build_payload
from app.domain.figure_workbench.tasks import submit
from app.domain.figure_workbench.contracts import GenerateFigure
from app.domain.external_processing import digest
from app.domain.report_collections.contracts import CollectionRequest
from app.domain.report_collections.execution import run_collection_word_task


def test_v3_draw_explain_read_and_word_keep_full_caption_once(client, monkeypatch):
    config = {'figure_kind': 'line', 'language': 'en', 'projection': {'x_column': 'A', 'y_column': 'C'},
              'style': {'aliases': {'A': 'Axis alias', 'C': 'Response alias'}, 'caption': 'Author caption.'}}
    workbench, project, result, version, task = queued_figure(client, monkeypatch, config, contract_version=3)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', checked_policy)
    provider = IndependentV2LineProvider(result, pending=False)
    for _ in range(5):
        task = run_figure_workbench_task(task['id'], task['revision'], provider_factory=lambda: provider)
        assert task is not None
        if task['status'] in ('succeeded', 'failed'): break
    assert task['status'] == 'succeeded', task
    bundle = read_bundle(workbench.assets, project, task['result_figure_id'])
    figure = bundle['figure']
    assert figure['engine']['id'] == 'openai_figure_workbench_v3'
    assert figure['presentation']['schema_version'] == 2
    assert 'Axis alias' in figure['x_label'] and 'Response alias' in figure['y_label']
    payload = build_payload(bundle)
    assert payload['figure_explanation_contract'] == 4
    explanation = submit(workbench, project, result['file_id'], result['id'], version,
                         GenerateFigure(idempotency_key='v3-explanation', external_processing={'confirmed': True, 'payload_sha256': digest(payload)}),
                         figure_id=figure['id'])['task']
    prose = FigureExplanationProvider()
    explanation = run_figure_explanation_task(explanation['id'], explanation['revision'], provider_factory=lambda: prose)
    assert explanation is not None and explanation['status'] == 'succeeded', explanation
    published = read_bundle(workbench.assets, project, figure['id'], explanation['result_explanation_id'])
    assert published['explanation']['engine']['id'] == 'figure_explanation_v4'
    repository = CollectionStore(workbench.assets)
    collection = repository.create(project, CollectionRequest(title='v3 report', language='en', items=[{'figure_config_version_id': version}]), 'v3-report')
    request = collection['versions'][0]['requests'][0]
    done = run_collection_word_task(request['task_id'], 1, config=repository.store.db_config, directory=repository.store.directory)
    assert done is not None and done['status'] == 'succeeded', done
    state = repository.get(project, collection['id'])
    report = state['versions'][0]['requests'][0]['report']
    _, content = repository.download(project, collection['id'], report['id'])
    with ZipFile(BytesIO(content)) as archive:
        xml = ElementTree.fromstring(archive.read('word/document.xml'))
        text = ''.join(xml.itertext())
        assert text.count('Author caption.') == 1
        for note in figure['presentation']['statistical_notes']:
            assert text.count(note) == 1
        assert [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')] == [provider.png]
