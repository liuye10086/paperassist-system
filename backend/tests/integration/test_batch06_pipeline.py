"""Batch06 independent numerical oracle through real isolated PostgreSQL publication."""
from copy import deepcopy
from io import BytesIO
import json
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_execution import (
    queued_figure, IndependentLineProvider, FigureExplanationProvider, frozen_policy,
)
from app.adapters.figure_workbench_store import read_bundle
from app.adapters.collection_store import CollectionStore
from app.domain.figure_workbench.execution import run_figure_workbench_task, run_figure_explanation_task
from app.domain.figure_workbench.tasks import submit, validate_policy
from app.domain.figure_workbench.contracts import GenerateFigure
from app.domain.figure_workbench.explanations import build_payload
from app.domain.external_processing import digest
from app.domain.report_collections.contracts import CollectionRequest
from app.domain.report_collections.service import advance_pending
from app.domain.report_collections.execution import run_collection_word_task
from app.core.exceptions import StorageError


class IndependentV2LineProvider(IndependentLineProvider):
    def download(self, file_id, container_id, limit, *, policy):
        raw = super().download(file_id, container_id, limit, policy=policy)
        if file_id == 'cfile_png':
            return raw
        manifest = json.loads(raw)
        # Metadata is copied; the independent four-point numerical oracle above is retained.
        manifest['presentation'] = deepcopy(self.payload['presentation'])
        return json.dumps(manifest).encode()


def checked_policy(payload, explanation=False):
    value = frozen_policy(payload)
    if explanation:
        version = {1:'figure_explanation_v1',2:'figure_explanation_v2',3:'figure_explanation_v3',4:'figure_explanation_v4',5:'figure_explanation_v5'}[payload.get('figure_explanation_contract',1)]
        value['policy'].update(prompt_version=version, tools=[], output_format='analysis_explanation_v2')
        value.pop('tool_reserve_micro_usd')
        value.pop('tool_reserve_version')
        value['task_limit_micro_usd'] = 500000
    return validate_policy(value, payload, explanation=explanation)


@pytest.fixture
def pipeline(client, monkeypatch, request):
    workbench, project, result, version, task = queued_figure(client, monkeypatch, contract_version=2)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', checked_policy)
    repository = CollectionStore(workbench.assets)
    collection = None
    if request.node.name == 'test_pending_v2_collection_advances_local_word_without_model_call':
        collection = repository.create(project, CollectionRequest(title='Batch06 report', language='en',
            items=[{'figure_config_version_id': version}]), 'batch06-pending')
        assert collection['versions'][0]['requests'][0]['status'] == 'waiting'
    provider = IndependentV2LineProvider(result, pending=False)
    for _ in range(5):
        task = run_figure_workbench_task(task['id'], task['revision'], provider_factory=lambda: provider)
        assert task is not None
        if task['status'] in ('succeeded', 'failed'):
            break
    assert task['status'] == 'succeeded', task
    figure_id = task['result_figure_id']
    bundle = read_bundle(workbench.assets, project, figure_id)
    payload = build_payload(bundle)
    assert payload['figure_explanation_contract'] == 2
    request = GenerateFigure(idempotency_key='batch06-explain', external_processing={
        'confirmed': True, 'payload_sha256': digest(payload)})
    explanation = submit(workbench, project, result['file_id'], result['id'], version, request,
        figure_id=figure_id)['task']
    prose = FigureExplanationProvider()
    explanation = run_figure_explanation_task(explanation['id'], explanation['revision'], provider_factory=lambda: prose)
    assert explanation is not None and explanation['status'] == 'succeeded', explanation
    bundle = read_bundle(workbench.assets, project, figure_id, explanation['result_explanation_id'])
    return workbench, repository, project, result, collection, bundle, provider, prose


def test_v2_frozen_metadata_package_and_bound_explanation(pipeline, client):
    workbench, _, project, result, _, bundle, provider, prose = pipeline
    figure, explanation = bundle['figure'], bundle['explanation']
    assert figure['engine']['id'] == 'openai_figure_workbench_v2'
    assert figure['schema_version'] == 5 and figure['presentation']['schema_version'] == 1
    assert figure['presentation'] == provider.payload['presentation']
    assert [p['y'] for p in figure['statistics']['series'][0]['points']] == [9., 8., 7., 6.]
    assert explanation['engine']['id'] == 'figure_explanation_v2'
    assert len(explanation['sections']) == 6
    assert all(section['evidence'] for section in explanation['sections'])
    assert explanation['limitations'] and any('design' in note.lower() for note in explanation['limitations'])
    assert explanation['figure_sha256'] == figure['sha256']
    response = client.get(f"/api/v1/projects/{project}/files/{result['file_id']}/analysis-runs/{result['id']}/figure-workbench/figures/{figure['id']}/package")
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        description = json.loads(archive.read('explanation.json'))
        assert description['figure_number'] == 1
        assert description['presentation'] == figure['presentation']
        assert archive.read('figure.png') == provider.png == workbench.assets.figure_png(figure)
    assert provider.posts == ['container', 'upload', 'response'] and len(prose.posts) == 1


def test_pending_v2_collection_advances_local_word_without_model_call(pipeline):
    workbench, repository, project, _, collection, bundle, provider, _ = pipeline
    frozen = collection['versions'][0]['items'][0]
    assert frozen['dependency_engine'] == 'figure_explanation_v2'
    advance_pending(config=repository.store.db_config, directory=repository.store.directory)
    state = repository.get(project, collection['id'])
    request = state['versions'][0]['requests'][0]
    assert request['status'] == 'queued', request
    done = run_collection_word_task(request['task_id'], 1, config=repository.store.db_config, directory=repository.store.directory)
    assert done['status'] == 'succeeded', done
    state = repository.get(project, collection['id'])
    report = state['versions'][0]['requests'][0]['report']
    _, content = repository.download(project, collection['id'], report['id'])
    preview = repository.preview(project, collection['id'], collection['current_version_id'])
    figures = next(s for s in preview['sections'] if s['key'] == 'figures')['content']
    assert figures[0]['presentation'] == bundle['figure']['presentation']
    assert figures[0]['figure_number'] == preview['items'][0]['figure_number'] == 1
    with ZipFile(BytesIO(content)) as archive:
        assert [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')] == [provider.png]
        document = ElementTree.fromstring(archive.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text = '\n'.join(''.join(node.text or '' for node in paragraph.findall('.//w:t', ns))
                         for paragraph in document.findall('.//w:p', ns))
        presentation = bundle['figure']['presentation']
        assert presentation['abbreviations'] and presentation['statistical_notes']
        for entry in presentation['abbreviations']:
            assert f"{entry['term']} — {entry['definition']}" in text
        for note in presentation['statistical_notes']:
            assert note in text
    with workbench.tasks.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s', (request['task_id'],)).fetchone()['n'] == 0


@pytest.mark.parametrize('language,definition,note', [
    ('en', 'Sample standard deviation (denominator n−1)', 'Error bars show sample SD.'),
    ('zh-CN', '样本标准差（分母n−1）', '误差线表示样本SD。'),
], ids=['english', 'chinese'])
def test_reader_figure_displays_frozen_abbreviation_definition(language, definition, note):
    from app.domain.external_processing import digest
    from app.domain.statistics_reader_reports.narrative import figure_output

    presentation = dict(abbreviations=[{'term': 'SD', 'definition': definition}], statistical_notes=[note])
    item = dict(figure={'figure_kind': 'bar', 'title': 'SD', 'presentation': presentation}, result={},
                explanation={'sections': [{'key': key, 'text': 'Saved text.'}
                                          for key in ('methods', 'results', 'interpretation')]})
    output = figure_output(item, 1, language)
    assert output['reading'].count('SD — ' + definition) == 1
    assert output['limitations'].count(note) == 1
    # Whole-output digests from the historical projection of the same synthetic figure.
    old_digests = {'en': '8f0bee00b9fae759256bab06995f3388bb5931fd71a9619e328a6ae0696d9114',
                   'zh-CN': '061d267371d758c87036dc96e0606b8447dcddb169a828bafce19e681beed4b8'}
    assert digest(figure_output(item, 1, language, context_schema_version=1)) == old_digests[language]


@pytest.mark.parametrize('change', ['metadata', 'figure_engine', 'limitations', 'explanation_engine'])
def test_saved_v2_tampering_is_rejected(pipeline, change):
    workbench, _, project, _, _, bundle, _, _ = pipeline
    figure, explanation = bundle['figure'], bundle['explanation']
    with workbench.tasks.connection(write=True) as db:
        if change in ('metadata', 'figure_engine'):
            changed = deepcopy(figure)
            if change == 'metadata':
                changed['presentation']['axes']['y']['unit'] = 'forged unit'
            else:
                changed['engine']['id'] = 'openai_figure_workbench_v99'
            db.execute('UPDATE figures SET figure_json=%s WHERE id=%s', (json.dumps(changed), figure['id']))
        else:
            changed = deepcopy(explanation)
            if change == 'limitations':
                changed['limitations'] = ['Invented reassurance']
            else:
                changed['engine']['id'] = 'figure_explanation_v99'
            db.execute('UPDATE explanations SET explanation_json=%s WHERE id=%s', (json.dumps(changed), explanation['id']))
    with pytest.raises(StorageError):
        read_bundle(workbench.assets, project, figure['id'], explanation['id'])
    with pytest.raises(StorageError):
        workbench.state(project,bundle['result']['file_id'],bundle['result']['id'])
