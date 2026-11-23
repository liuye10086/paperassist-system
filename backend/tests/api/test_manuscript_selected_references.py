from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.db.database import database_connection
from app.domain.literature.execution import run_literature_task
from app.domain.tasks.execution import run_task
from app.main import app
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_customer_project_types import create, project_body, project_path
from tests.api.test_customer_sci_workflow import sci_project
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_literature import create as create_search
from tests.api.test_literature_citations import CitationNcbi, seeded
from tests.api.test_literature_evidence import post
from tests.api.test_manuscripts import body
from tests.api.test_thesis_manuscripts import bound


def selection(ref):
    return dict(project_reference_id=ref['id'], search_id=ref['source']['search_id'],
                quote=ref['record']['abstract'][0]['text'])


def counts():
    with database_connection() as db:
        return tuple(db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n'] for table in (
            'literature_claims', 'literature_claim_evidence', 'literature_claim_reviews',
            'literature_citation_metadata_versions', 'literature_citation_drafts', 'model_calls',
        ))


def test_selected_abstracts_create_one_usable_draft_and_replay_concurrently(client):
    project, lit, search, refs = seeded(client)
    path = f'/api/v1/projects/{project}/manuscripts'
    endpoint = path + '/selected-references'
    selected = [selection(ref) for ref in refs]
    payload = dict(references=selected, output_language='en')
    # An existing verified bibliography entry must remain the current version.
    old = post(client, f"{lit}/citations/references/{refs[0]['id']}/metadata",
               dict(mode='extract', expected_revision=0, search_id=search['id']), 'old')
    assert old.status_code == 201, old.text
    barrier = Barrier(2)

    def save(_):
        barrier.wait(timeout=10)
        return post(client, endpoint, payload, 'selection')

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(save, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 201], [r.text for r in responses]
    draft = responses[0].json()
    assert draft == responses[1].json() and set(draft) == {'id', 'revision'} and draft['revision'] == 1
    assert counts() == (2, 2, 2, 2, 1, 0)
    for changed in (payload | {'references': selected[::-1]}, payload | {'output_language': 'zh-CN'}):
        assert post(client, endpoint, changed, 'selection').status_code == 409
    preview = post(client, path + '/preview', body(citation_draft=draft), 'preview')
    assert preview.status_code == 200, preview.text
    frozen = preview.json()['citation_snapshot']
    assert [r['project_reference_id'] for r in frozen['output']['references']] == [r['id'] for r in refs]
    for paragraph, wanted in zip(frozen['paragraphs'], selected, strict=True):
        fragment, = paragraph['fragments']
        binding, = fragment['bindings']
        evidence, = binding['evidence']
        assert fragment['text'] == evidence['quote'] == wanted['quote']
        assert evidence['reading_scope'] == 'abstract' and evidence['source']['search_id'] == search['id']
        assert evidence['project_reference_id'] == wanted['project_reference_id']
    assert frozen['paragraphs'][0]['fragments'][0]['bindings'][0]['metadata_version_id'] == old.json()['id']


def test_invalid_second_reference_rolls_back_all_steps_and_can_retry(client):
    project, lit, _, refs = seeded(client)
    path = f'/api/v1/projects/{project}/manuscripts/selected-references'
    selected = [selection(ref) for ref in refs]
    for invalid in (selected[1] | {'quote': 'absent from the stored abstract'},
                    selected[1] | {'search_id': 'missing'}, selected[0]):
        response = post(client, path, {'references': [selected[0], invalid]}, 'retry')
        assert response.status_code in (404, 422), response.text
        if invalid['quote'] == 'absent from the stored abstract':
            assert response.json()['detail']['code'] == 'selected_reference_quote_invalid'
            assert response.json()['detail']['params'] == {'position': 2}
        assert counts() == (0, 0, 0, 0, 0, 0)
    excluded = client.patch(f"{lit}/references/{refs[1]['id']}", json=dict(expected_revision=1, status='excluded'))
    assert excluded.status_code == 200, excluded.text
    response = post(client, path, {'references': selected}, 'retry')
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'selected_reference_excluded'
    assert response.json()['detail']['params'] == {'position': 2}
    assert '排除' in response.json()['detail']['message']
    assert counts() == (0, 0, 0, 0, 0, 0)
    assert post(client, path, {'references': selected[:1]}, 'retry').status_code == 201


def test_unusable_bibliography_identifies_the_reference_and_preserves_history(client):
    from tests.api.test_literature import project

    paper = project(client)
    search = create_search(client, paper).json()
    assert run_literature_task(search['id'], search['revision'], client=CitationNcbi(4))['status'] == 'succeeded'
    base = f'/api/v1/projects/{paper}'
    refs = client.get(base + '/literature/references').json()['items']
    incomplete = next(r for r in refs if r['pmid'] == '990000004')
    usable = next(r for r in refs if r['pmid'] == '990000002')
    response = post(client, base + '/manuscripts/selected-references',
                    dict(references=[selection(usable), selection(incomplete)]), 'gaps')
    assert response.status_code == 409, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'selected_reference_metadata_incomplete' and detail['params'] == {'position': 2}
    assert counts() == (0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize('kind', ['sci', 'thesis'])
def test_customer_can_select_only_own_paper_project_references(kind):
    with TestClient(app) as owner, TestClient(app) as other:
        sign_in(owner, 'paper-owner@example.test', 'customer')
        sign_in(other, 'paper-other@example.test', 'customer')
        paper = sci_project(owner) if kind == 'sci' else project_path(create(owner, 'thesis', **project_body('thesis')))
        search = create_search(owner, paper.rsplit('/', 1)[-1]).json()
        assert run_literature_task(search['id'], search['revision'], client=CitationNcbi(3))['status'] == 'succeeded'
        refs = owner.get(paper + '/literature/references').json()['items']
        payload = dict(references=[selection(next(r for r in refs if r['record']['abstract']))])
        suffix = '/manuscripts/selected-references'
        assert post(other, paper + suffix, payload, 'foreign-owner').status_code == 404
        other_paper = sci_project(owner, key='other-sci')
        assert post(owner, other_paper + suffix, payload, 'foreign-reference').status_code == 404
        assert post(owner, create_customer_project(owner) + suffix, payload, 'research').status_code == 403
        made = post(owner, paper + suffix, payload, 'allowed')
        assert made.status_code == 201, made.text
        language = owner.get(paper).json()['default_output_language']
        if kind == 'sci':
            response = post(owner, paper + '/manuscripts/preview', body(output_language=language, citation_draft=made.json()), 'frozen')
            assert response.status_code == 200, response.text
            saved = response.json()['citation_snapshot']
        else:
            saved = owner.get(paper + '/literature/citations/drafts/' + made.json()['id']).json()['snapshot']
        assert saved['output_language'] == language


@pytest.mark.parametrize('whole_abstract', [False, True])
def test_selected_references_work_with_saved_thesis_binding(client, whole_abstract):
    paper, _, manuscript = bound(client)
    search = create_search(client, paper.rsplit('/', 1)[-1]).json()
    assert run_literature_task(search['id'], search['revision'], client=CitationNcbi(3))['status'] == 'succeeded'
    refs = client.get(paper + '/literature/references').json()['items']
    selected = [selection(ref) for ref in refs if ref['record']['abstract']]
    path = paper + '/manuscripts'
    if whole_abstract:
        for item in selected:
            item.pop('quote')
            marked = client.patch(f"{paper}/literature/references/{item['project_reference_id']}",
                                  json=dict(status='shortlisted', expected_revision=1))
            assert marked.status_code == 200, marked.text
        partial = post(client, path + '/selected-references', dict(references=selected[:1]), 'incomplete')
        assert partial.status_code == 409, partial.text
    draft = post(client, path + '/selected-references', dict(references=selected), 'thesis')
    assert draft.status_code == 201, draft.text
    retry = post(client, path + '/selected-references', dict(references=selected), 'thesis')
    assert retry.status_code == 200 and retry.json() == draft.json()
    preview = post(client, path + '/preview', manuscript | {'citation_draft': draft.json()}, 'preview')
    assert preview.status_code == 200, preview.text
    assert len(preview.json()['references']) == len(selected)
    assert preview.json()['thesis_context']['confirmation_id'] == manuscript['thesis']['confirmation_id']
    if whole_abstract:
        prepared = post(client, path, manuscript | {'citation_draft':draft.json()}, 'prepare-thesis')
        assert prepared.status_code == 201, prepared.text
        root = prepared.json()
        assert run_task(root['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        evidence = [item for p in preview.json()['citation_snapshot']['paragraphs']
                    for fragment in p['fragments'] for binding in fragment['bindings'] for item in binding['evidence']]
        bundle = post(client, f"{path}/{root['id']}/writing-previews", dict(
            schema_version=3, base_revision=1, mode='full_draft', output_language=manuscript['output_language'],
            selected_source_ids=[], selected_evidence_ids=[e['id'] for e in evidence],
            document_context_version='selected-text-v1'), 'preview-thesis')
        assert bundle.status_code == 201, bundle.text
        payload = json.loads(json.loads(bundle.json()['wire_json'])['input'])
        assert payload['schema_version'] == 3
        assert [row['title'] for row in payload['chapters']] == ['绪论','研究方法','结果']
        assert [row['quote'] for row in payload['evidence']] == [e['quote'] for e in evidence]
        assert counts()[-1] == 0
