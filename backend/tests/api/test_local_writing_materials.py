"""Viewing frozen local material is independent of provider wire restrictions."""
import pytest
from tests.api.test_manuscripts import client, setup, body
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task
from app.db.database import database_connection


def test_local_statistical_labels_and_paths_are_preserved_without_external_text_checks():
    from app.domain.manuscripts.writing_materials import project_materials
    snapshot = dict(title='Retained analysis', output_language='en', sources=[dict(
        kind='analysis_run', role='computed_results', content=dict(
            statistics={'/cohort~baseline': 3.5, 'available': True},
            groups=[dict(label='https://example.org/cohort', n=3, method='abs(effect)/(1+abs(effect))')]))])
    source = project_materials(snapshot)['sources'][0]
    assert source['facts'] == [
        dict(fact_path='/statistics/~1cohort~0baseline', value='3.5'),
        dict(fact_path='/groups/0/n', value='3'),
    ]
    assert source['labels'] == [
        dict(path='/groups/0/label', value='https://example.org/cohort'),
        dict(path='/groups/0/method', value='abs(effect)/(1+abs(effect))'),
    ]


@pytest.mark.parametrize('text', [
    'Resource release: https://ftp.ebi.ac.uk/pub/contrib/goa/goex/releases/2026-06-16/',
    'Score definition: abs(effect)/(1+abs(effect))',
])
def test_local_materials_preserve_prose_without_authorizing_external_writing(client, text):
    path, _, _ = setup(client)
    created = post(client, path, body(methods={'study_design': text}), 'local-base')
    assert created.status_code == 201, created.text
    manuscript = created.json(); version = manuscript['versions'][0]
    assert run_task(version['task_id'], 1)['status'] == 'succeeded'
    root = path + '/' + manuscript['id']
    response = client.get(root + '/versions/1/writing-materials')
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['can_execute'] is False and value['version_id'] == version['id']
    assert any(text in p['text'] for s in value['materials']['context'] for p in s['paragraphs'])
    external = post(client, root + '/writing-previews', dict(schema_version=2, base_revision=1,
        mode='full_draft', output_language='en', selected_source_ids=[], selected_evidence_ids=[]), 'external')
    assert external.status_code == 422, external.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
