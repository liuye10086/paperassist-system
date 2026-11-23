"""Customer reads and downloads a saved, unadopted draft using synthetic source material."""
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from app.db.database import database_connection
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.main import app
from tests.api.test_customer_sci_workflow import article_request, sci_project
from tests.api.test_customer_workspace import sign_in
from tests.api.test_manuscript_writing_live import authorize, request_v2
from tests.api.test_manuscripts import body
from tests.integration.test_customer_sci_to_word import (
    SciFixtureProvider, create_fact, request, selected_pubmed_reference,
)


def test_review_images_follow_first_in_section_mention_in_reader_and_docx():
    from hashlib import sha256
    from PIL import Image
    from app.domain.sci_draft_reader import draft_content, draft_word

    raw = BytesIO()
    Image.new('RGB', (32, 16), 'green').save(raw, format='PNG')
    pixels = raw.getvalue()
    theme = 'paper-' + 'a' * 32
    def figure(number):
        return dict(id=f'image-{number}', title=f'Diagram {number}', number=number, caption=f'Caption {number}',
                    sha256=sha256(pixels).hexdigest(), source_ids=[f'image-{number}'])
    def paragraph(index, text):
        return dict(id=f'body{index}', text=text, origin='model_generated')
    snapshot = dict(title='Review', output_language='en', article_type='narrative_review', references=[],
        paper_plan=dict(kind='narrative_review', review_figure_placement_version=1, sections=[dict(id=theme, label='Evaluation')]),
        results_groups=[dict(id=theme,title='Evaluation',tables=[],figures=[figure(1),figure(2)])],
        sections=[dict(id=theme,parent_id='themes',result_group_ids=[theme],level=2,
                       paragraphs=[paragraph(1,'See Figure 1.'),paragraph(2,'We revisit Fig. 1.'),paragraph(3,'Final paragraph.')])])
    section = draft_content(snapshot, {})['sections'][0]
    assert [f['number'] for f in section['paragraphs'][0]['figures']] == [1]
    assert all(not p.get('figures') for p in section['paragraphs'][1:])
    assert [f['number'] for group in section['groups'] for f in group['figures']] == [2]
    document = Document(BytesIO(draft_word(draft_content(snapshot, {}), {f'image-{n}': pixels for n in (1, 2)})))
    texts = [p.text for p in document.paragraphs]
    assert len(document.inline_shapes) == 2
    assert texts.index('See Figure 1.') < texts.index('Caption 1') < texts.index('We revisit Fig. 1.')
    assert texts.index('Final paragraph.') < texts.index('Caption 2')


def test_saved_customer_draft_before_review_and_after_a_new_request():
    with TestClient(app) as client, TestClient(app) as other:
        sign_in(client, 'reader-owner@example.test', 'customer')
        sign_in(other, 'reader-other@example.test', 'customer')
        project = sci_project(client, 'narrative_review')
        current = project + '/sci-current-draft'
        assert client.get(current).json() == {'draft': None}
        draft, _, _, reference, quote = selected_pubmed_reference(client, project, 'en')
        root, snapshot = create_fact(client, project, body(methods={}, citation_draft=draft))
        binding = snapshot['citation_snapshot']['paragraphs'][0]['fragments'][0]['bindings'][0]
        bundle = request(client, 'POST', root + '/writing-previews', status=201, key='preview',
                         json=article_request('narrative_review', selected_evidence_ids=[binding['evidence'][0]['id']]))
        _, consent = authorize(client, root, bundle)
        payload = request_v2(bundle, consent)
        task = request(client, 'POST', root + '/writing-requests', status=202, key='draft', json=payload)['task']
        reader = root + '/writing-requests/' + task['id'] + '/draft-reader'
        url = reader + '?revision=1'
        word = reader + '/word?revision=1'
        saved = dict(manuscript_id=root.rsplit('/', 1)[1], request_id=task['id'], revision=1)
        assert client.get(current).json() == {'draft': saved}
        assert client.get(current, params={'manuscript_id': saved['manuscript_id'], 'revision': 1}).json() == {'draft': saved}
        assert client.get(current, params={'manuscript_id': saved['manuscript_id'], 'revision': 9}).json() == {'draft': None}
        assert client.get(url).json()['status'] == 'queued'
        assert client.get(word).status_code == 409
        sections = {key: dict(text='This synthetic review describes a documented protocol.')
                    for key in ('title', 'abstract', 'introduction', 'literature_scope', 'themes', 'discussion', 'conclusion')}
        sections['themes'] = dict(text=quote, evidence_aliases=['e1'])
        assert run_manuscript_writing_task(task['id'], 1, provider=SciFixtureProvider(sections))['status'] == 'succeeded'
        response = request(client, 'GET', url)
        assert response['status'] == 'succeeded' and response['can_revise']
        manuscript = response['draft']
        theme = next(s for s in manuscript['sections'] if s['id'] == 'themes')
        citation = theme['paragraphs'][0]['parts'][0]['citations'][0]
        assert citation == dict(number=1, project_reference_id=reference['id'], title=binding['metadata']['title'],
                                excerpts=[dict(id=binding['evidence'][0]['id'], quote=quote, reading_scope='abstract')])
        download = client.get(word)
        assert download.status_code == 200
        lines = [p.text for p in Document(BytesIO(download.content)).paragraphs]
        assert quote + '[1]' in lines and '[1] ' + snapshot['references'][0]['text'] in lines
        assert 'Literature sources and inclusion scope' in lines
        second = request(client, 'POST', root + '/writing-requests', status=202, key='second',
                         json=dict(payload, logical_task_id='task-1'))['task']
        assert client.get(current).json()['draft']['request_id'] == second['id']
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET status='failed' WHERE id=%s", (second['id'],))
        assert client.get(current).json() == {'draft': saved}
        assert client.get(word).status_code == 200
        assert client.get(reader + '?revision=2').status_code == 404
        for path in (url, word, current):
            assert other.get(path).status_code == 404
        assert len(request(client, 'GET', root)['versions']) == 1


def test_alias_ids_do_not_determine_reference_numbers_and_same_paper_excerpts_stay_together():
    from app.domain.sci_draft_reader import paragraph_parts, paragraph_text

    def item(identity, quote):
        return dict(id=identity, quote=quote, reading_scope='abstract')

    a, b, c = item('right-a', 'First excerpt.'), item('right-b', 'Second excerpt.'), item('right-c', 'Third excerpt.')
    shared = dict(project_reference_id='paper-b', metadata={'title': 'Second paper'}, evidence=[b, a])
    other = dict(project_reference_id='paper-a', metadata={'title': 'First paper'}, evidence=[c])
    manifest = dict(e1=dict(evidence_id=a['id'], binding=shared), e2=dict(evidence_id=c['id'], binding=other),
                    e3=dict(evidence_id=b['id'], binding=shared))
    refs = {'paper-a': dict(number=1), 'paper-b': dict(number=2)}
    paragraph = dict(text='Unchanged dose (2).', suggested_evidence_aliases=['e1', 'e3', 'e2'])
    parts = paragraph_parts(paragraph, {}, manifest, refs)
    assert [cite['excerpts'] for cite in parts[0]['citations']] == [[c], [a, b]]
    assert paragraph_text(dict(parts=parts)) == 'Unchanged dose (2).[1][2]'


def test_generated_body_numbers_follow_first_use_and_exclude_unmentioned_selection():
    from app.domain.sci_draft_reader import draft_content, draft_word
    names = ['Unused selection', 'Later paper', 'First paper']
    refs = [dict(number=i, project_reference_id=f'r{i}', text=name) for i, name in enumerate(names, 1)]
    def paragraph(i):
        return dict(id=f'p{i}', text=f'Claim {i}.', origin='model_generated', suggested_evidence_aliases=[f'e{i}'])
    evidence = {f'e{i}': dict(evidence_id=f'quote{i}', binding=dict(project_reference_id=f'r{i}', metadata={'title': name},
                evidence=[dict(id=f'quote{i}', quote=name, reading_scope='abstract')])) for i, name in enumerate(names, 1)}
    candidate = dict(title='Title', output_language='en', references=refs, results_groups=[],
                     sections=[dict(id='discussion', paragraphs=[paragraph(3), paragraph(2)])])
    view = draft_content(candidate, evidence)
    assert [(r['number'], r['project_reference_id']) for r in view['references']] == [(1, 'r3'), (2, 'r2')]
    lines = [p.text for p in Document(BytesIO(draft_word(view, {}))).paragraphs]
    assert 'Claim 3.[1]' in lines and 'Claim 2.[2]' in lines
    assert '[1] First paper' in lines and '[2] Later paper' in lines and not any('Unused selection' in text for text in lines)


def test_published_legacy_v1_bookmark_opens_its_original_writing_request():
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.domain.manuscript_writing.service import WritingService
    from tests.api.test_manuscript_writing_execution import WritingProvider

    with TestClient(app) as client:
        owner = sign_in(client, 'legacy-draft@example.test', 'customer')
        project = sci_project(client)
        root, _ = create_fact(client, project, body())
        project_id, manuscript = project.rsplit('/', 1)[1], root.rsplit('/', 1)[1]
        # Seed exactly the workflow that produced these historical records through its original service.
        writing = WritingService(ProjectStore(get_data_dir(), owner_id=owner))
        saved, _ = writing.create(project_id, manuscript, dict(base_revision=1, mode='full_draft'), 'legacy')
        assert run_manuscript_writing_task(saved['id'], 1, provider=WritingProvider())['status'] == 'succeeded'
        writing.publish(project_id, manuscript, saved['id'], 1, 'old-publication')
        bookmark = request(client, 'GET', project + '/sci-current-draft', params={'manuscript_id': manuscript, 'revision': 2})
        assert bookmark['draft'] == dict(manuscript_id=manuscript, revision=1, request_id=saved['id'])
        reader = root + '/writing-requests/' + saved['id'] + '/draft-reader'
        view = request(client, 'GET', reader + '?revision=1')
        assert view['status'] == 'succeeded' and not view['can_revise']
        lines = [p.text for p in Document(BytesIO(client.get(reader + '/word?revision=1').content)).paragraphs]
        assert view['draft']['title'] in lines and 'Synthetic prose. Missing study facts require verification.' in lines
