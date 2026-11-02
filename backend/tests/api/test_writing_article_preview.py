"""Schema4 real API storage boundary; no provider or scientific execution."""
import json

from tests.api.test_manuscripts import client, setup, body  # noqa: F401
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task
from app.db.database import database_connection


def test_article_preview_roundtrip_and_document_kind_without_model_call(client):
    path, _, _ = setup(client)
    manuscript = post(client, path, body(), 'article-base').json()
    assert run_task(manuscript['versions'][0]['task_id'], 1)['status'] == 'succeeded'
    endpoint = path + '/' + manuscript['id'] + '/writing-previews'
    request = dict(schema_version=4, document_kind='sci', article_type='methods',
                   base_revision=1, mode='full_draft', output_language='en',
                   selected_source_ids=[], selected_evidence_ids=[])
    response = post(client, endpoint, request, 'article-preview')
    assert response.status_code == 201, response.text
    bundle = response.json()
    payload = json.loads(json.loads(bundle['wire_json'])['input'])
    assert payload['schema_version'] == 4 and payload['article_type'] == 'methods'
    assert payload['validation_available'] is False
    assert 'validation' in payload['writing_scope']['output_section_ids']
    assert client.get(endpoint + '/' + bundle['id']).json() == bundle
    assert post(client, endpoint, request, 'article-preview').json() == bundle
    wrong_kind = post(client, endpoint, request | {'document_kind': 'thesis', 'article_type': 'research'}, 'wrong-kind')
    assert wrong_kind.status_code == 422, wrong_kind.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
