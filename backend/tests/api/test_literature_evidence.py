"""Synthetic offline evidence API contracts, isolated by conftest."""
import pytest

from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project


def base(client, kind='sci'):
    return f'/api/v1/projects/{project(client, kind)}/literature/evidence'


def post(client, path, body, key='evidence-key'):
    return client.post(path, json=body, headers={'Idempotency-Key': key})


def claim(client, path):
    response = post(client, path+'/claims', {'content': 'Synthetic claim', 'context': 'Synthetic context', 'output_language': 'en'})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize('kind', ['sci', 'thesis'])
def test_claim_versions_are_immutable_and_revision_guarded(client, kind):
    path = base(client, kind)
    first = claim(client, path)
    assert first['revision'] == 1
    second = post(client, path+'/claims/'+first['id']+'/versions',
        {'expected_revision': 1, 'content': 'Narrower claim', 'context': '', 'output_language': 'en'}, 'v2')
    assert second.status_code == 201, second.text
    assert second.json()['revision'] == 2
    stale = post(client, path+'/claims/'+first['id']+'/versions',
        {'expected_revision': 1, 'content': 'Stale overwrite', 'context': '', 'output_language': 'en'}, 'v3')
    assert stale.status_code == 409
    old = client.get(path+'/claims/'+first['id'], params={'revision': 1}).json()
    assert old['content'] == first['content'] and old['is_current'] is False
    assert len(old['versions']) == 2


def test_evidence_configuration_and_cross_project_are_scoped(client):
    path = base(client)
    item = claim(client, path)
    config = client.get(path+'/config')
    assert config.status_code == 200, config.text
    assert config.json()['real_model_calls'] is False
    assert config.json()['supplement_candidate_limit'] == 20
    assert client.get(base(client)+'/claims/'+item['id']).status_code == 404
    assert client.get(path+'/material-options').json()['items'] == []


def test_stable_claim_supplement_is_limited_across_revisions(client):
    path = base(client)
    item = claim(client, path)
    endpoint = path+'/claims/'+item['id']+'/supplement'
    request = {'claim_revision': 1, 'query': 'synthetic[Title]', 'reason': 'Need materials'}
    response = post(client, endpoint, request, 'supplement-1')
    assert response.status_code == 202, response.text
    assert response.json()['round'] == 1 and response.json()['limit'] == 20
    replay = post(client, endpoint, request, 'supplement-1')
    assert replay.status_code == 200 and replay.json() == response.json()
    limited = post(client, endpoint, {**request, 'query': 'other'}, 'supplement-2')
    assert limited.status_code == 409
    assert limited.json()['detail']['code'] == 'literature_supplement_limit'
    second = post(client, path+'/claims/'+item['id']+'/versions',
        {'expected_revision': 1, 'content': 'Revised', 'context': '', 'output_language': 'en'}, 'v2')
    assert second.status_code == 201
    assert post(client, endpoint, {**request, 'claim_revision': 2}, 'supplement-3').status_code == 409


def test_supported_without_evidence_and_original_material_are_rejected(client):
    path = base(client)
    item = claim(client, path)
    body = dict(claim_revision=1, project_reference_id='missing', evidence_ids=[], status='supported',
        relevance='related', reason='Synthetic reason', narrowed_statement='', limitations='')
    assert post(client, path+'/claims/'+item['id']+'/reviews', body).status_code == 422
    assert post(client, path+'/materials', dict(project_reference_id='missing', file_id='missing', source_kind='original',
        version_id='missing', source_description='Synthetic', match_note='Synthetic')).status_code == 422
