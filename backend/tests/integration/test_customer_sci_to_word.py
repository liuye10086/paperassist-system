"""Real customer, PostgreSQL and DOCX paths with offline synthetic evidence."""
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile

from docx import Document
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.adapters.docx_parser import parse_docx
from app.db.database import database_connection
from app.domain.literature.execution import run_literature_task
from app.domain.manuscript_writing.bundle import build_bundle, validate_bundle
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.domain.tasks.execution import run_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_sci_workflow import article_request, sci_project
from tests.api.test_customer_workspace import sign_in
from tests.api.test_file_batches import register
from tests.api.test_literature import create as create_search
from tests.api.test_literature_citations import CitationNcbi
from tests.api.test_manuscript_writing_live import LiveFixture
from tests.api.test_manuscripts import body


DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
REPORTED_RESULT = 'The supplied engineering fixture reported an upward pattern across 4 observations.'
PROTOCOL = 'The supplied protocol called for 5 observations.'


class SciFixtureProvider(LiveFixture):
    """Generate only explicitly supplied fixture prose and frozen source aliases."""

    def __init__(self, paragraphs, *, pending=False):
        super().__init__(pending=pending)
        self.paragraphs = paragraphs

    def receipt(self):
        result = super().receipt()
        payload = json.loads(json.loads(self.posts[0])['input'])
        sections = []
        for section_id in payload['writing_scope']['output_section_ids']:
            paragraph = dict(id=f'{section_id}:1', source_aliases=[], evidence_aliases=[], study_numeric_bindings=[])
            sections.append(dict(id=section_id, paragraphs=[paragraph | self.paragraphs[section_id]]))
        result['response']['output'][0]['content'][0]['text'] = json.dumps(dict(sections=sections))
        return result


def request(client, method, path, *, status=200, key=None, **kwargs):
    headers = {'Idempotency-Key': key} if key else None
    response = client.request(method, path, headers=headers, **kwargs)
    assert response.status_code == status, response.text
    return response.json()


def create_fact(client, project, data):
    path = project + '/manuscripts'
    draft = request(client, 'POST', path, status=201, key='fact', json=data)
    version = draft['versions'][0]
    assert run_task(version['task_id'], 1)['status'] == 'succeeded'
    return path + '/' + draft['id'], version['snapshot']


def selected_pubmed_reference(client, project, language):
    literature = project + '/literature'
    response = create_search(client, project.rsplit('/', 1)[-1])
    assert response.status_code == 202, response.text
    search = response.json()
    assert run_literature_task(search['id'], search['revision'], client=CitationNcbi(3))['status'] == 'succeeded'
    references = request(client, 'GET', literature + '/references')['items']
    reference = next(ref for ref in references if ref['record']['abstract'])
    quote = reference['record']['abstract'][0]['text']
    draft = request(client, 'POST', project + '/manuscripts/selected-references', status=201, key='selected', json=dict(
        output_language=language, references=[dict(project_reference_id=reference['id'], search_id=search['id'], quote=quote)],
    ))
    return draft, literature, search, reference, quote


def assert_customer_writing_queued(client, root, task):
    assert task['status'] == 'queued'
    assert request(client, 'GET', root)['id'] == root.rsplit('/', 1)[-1]
    queued = request(client, 'GET', root + '/writing-requests/' + task['id'])
    assert queued['task']['status'] == 'queued' and queued['candidate'] is None
    with database_connection() as db:
        ready = db.execute('''SELECT task_revision FROM task_outbox WHERE task_id=%s AND event_type='task_ready'
            AND published_at IS NULL''', (task['id'],)).fetchall()
        assert [row['task_revision'] for row in ready] == [task['revision']]


def submit_candidate(client, project, root, bundle, provider, *, resume=False):
    assert bundle['execution_contract']['schema_version'] == 4
    bundle_ref = dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
    auth = request(client, 'POST', project + '/writing-authorizations', status=201, key='authorize', json=dict(
        schema_version=2, confirmed=True, tasks=[dict(logical_task_id='article', bundles=[bundle_ref])],
    ))
    payload = dict(schema_version=2, authorization_id=auth['id'], logical_task_id='article', **bundle_ref)
    task = request(client, 'POST', root + '/writing-requests', status=202, key='write', json=payload)['task']
    assert_customer_writing_queued(client, root, task)
    result = run_manuscript_writing_task(task['id'], task['revision'], provider=provider)
    if resume:
        assert result['status'] == 'running', result
        replay = request(client, 'POST', root + '/writing-requests', key='write', json=payload)
        assert replay['task']['id'] == task['id']
        provider.pending = False
        result = run_manuscript_writing_task(task['id'], result['revision'], provider=provider)
        assert len(provider.gets) == 1
    assert result['status'] == 'succeeded', result
    assert provider.posts == [bundle['wire_json']]
    path = root + '/writing-requests/' + task['id']
    saved = request(client, 'GET', path)
    provenance = saved['candidate']['writing_provenance']
    assert provenance['provider_provenance'] == 'synthetic_fixture'
    assert provenance['verification_status'] == 'pending'
    assert saved['published_revision'] is None
    return path + '/draft-reader', saved['candidate']


def upload_research_material(client, project):
    image = Image.new('RGB', (300, 200), 'white')
    ImageDraw.Draw(image).line([(25, 170), (125, 115), (260, 35)], fill='navy', width=7)
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    raw = buffer.getvalue()
    document = Document()
    document.add_paragraph(REPORTED_RESULT + ' ' + PROTOCOL)
    document.add_picture(BytesIO(raw))
    content = BytesIO()
    document.save(content)
    filename = 'reported-result.docx'
    base, batch, item, docx = register(client, {'id': project.rsplit('/', 1)[-1]}, content.getvalue(), filename, key='material')
    uploaded = request(client, 'POST', base + '/' + batch['id'] + '/items/' + item['client_id'], status=202,
                       files={'file': (filename, docx)})
    file_id = uploaded['file_id']
    task = uploaded['task']
    parsed = run_parse_file_task(task['id'], task['revision'], parser=parse_docx)
    assert parsed['status'] == 'succeeded', parsed
    documents = project + f'/files/{file_id}/document-versions'
    document_id = request(client, 'GET', documents)['items'][0]['id']
    image = request(client, 'GET', documents + '/' + document_id)['images'][0]
    assert sha256(raw).hexdigest() == image['sha256']
    source = dict(kind='original', id=file_id, file_id=file_id, role='user_results')
    figure = dict(kind='document_version', id=document_id, file_id=file_id, role='image_observation')
    return source, figure, raw


def test_customer_research_freezes_uploaded_result_numeric_context_and_figure_in_word():
    with TestClient(app) as client, TestClient(app) as other:
        sign_in(client, 'research-to-word@manuscript.test', 'customer')
        sign_in(other, 'foreign-word@manuscript.test', 'customer')
        project = sci_project(client)
        result_source, figure_source, png = upload_research_material(client, project)
        root, base_snapshot = create_fact(client, project, body(
            sources=[result_source, figure_source], methods=dict(study_design=PROTOCOL),
            method_source_ids={'study_design': [result_source['id']]},
            reported_result=dict(text=REPORTED_RESULT, source_ids=[result_source['id']]),
            figure_notes=[dict(figure_id=figure_source['id'], caption='Direction of the supplied synthetic observation.',
                               panels=[dict(label='A', description='Text-free synthetic line plot.')])],
        ))
        bundle = request(client, 'POST', root + '/writing-previews', status=201, key='preview', json=article_request(
            'research', selected_source_ids=[result_source['id'], figure_source['id']], keywords=['synthetic fixture'],
        ))
        wire = json.loads(json.loads(bundle['wire_json'])['input'])
        assert wire['sources'][0]['facts'] == []
        assert wire['illustrations'][0]['panels'][0]['label'] == 'A'
        alias, item = next((alias, item) for alias, item in bundle['local_manifest']['numeric_context'].items()
                           if item['text'].endswith(PROTOCOL))
        method_number = dict(source_alias=alias, **item['values'][0])
        assert method_number['value'] == '5'
        reported = next((row for row in wire['numeric_context'] if row['location'] == 'reported_results'), None)
        assert reported and reported['origin'] == 'user_provided' and reported['text'].endswith(REPORTED_RESULT)
        assert 'source_ids' not in reported
        assert reported['source_aliases'] == ['s1']
        result_number = dict(source_alias=reported['alias'], **reported['values'][0])
        assert result_number['value'] == '4'
        assert bundle['local_manifest']['numeric_context'][reported['alias']]['source_ids'] == [result_source['id']]
        legacy = build_bundle(base_snapshot, bundle['request_json'], execution_contract=bundle['execution_contract'],
                              include_reported_results=False)
        legacy.update(base_snapshot=base_snapshot, request_json=bundle['request_json'])
        assert validate_bundle(legacy)['bundle_sha256'] != bundle['bundle_sha256']
        unselected = request(client, 'POST', root + '/writing-previews', status=422, key='unselected', json=article_request(
            'research', selected_source_ids=[figure_source['id']],
        ))
        assert unselected['detail']['code'] == 'manuscript_writing_evidence_required'
        result_text = REPORTED_RESULT.removesuffix('.') + ' (Figure 1A).'
        provider = SciFixtureProvider(dict(
            title=dict(text='Synthetic directional observation'),
            abstract=dict(text='This engineering exercise demonstrated a source-linked draft.'),
            introduction=dict(text='The fixture illustrates a descriptive reporting workflow.'),
            results=dict(text=result_text, source_aliases=['s1', 's2'], study_numeric_bindings=[result_number]),
            discussion=dict(text='The supplied fixture describes an upward pattern.', source_aliases=['s1']),
            materials_and_methods=dict(text=PROTOCOL, source_aliases=['s1'], study_numeric_bindings=[method_number]),
        ), pending=True)
        reader, candidate = submit_candidate(client, project, root, bundle, provider, resume=True)
        assert candidate['keywords'] == ['synthetic fixture']
        assert candidate['article_type'] == 'research'
        result = next(s for s in candidate['sections'] if s['id'] == 'results')['paragraphs'][0]
        assert result['text'] == result_text and result['source_ids'] == [result_source['id'], figure_source['id']]
        assert result['context_numeric_bindings'][0]['value'] == '4'
        draft = request(client, 'GET', reader + '?revision=1')['draft']
        results = next(section for section in draft['sections'] if section['id'] == 'results')
        [figure] = [f for g in results['groups'] for f in g['figures']]
        assert figure['panels'] == [dict(label='A', description='Text-free synthetic line plot.')]
        image_url = reader + '/figures/1?revision=1'
        assert client.get(image_url).content == png
        assert client.get(reader + '/figures/99?revision=1').status_code == 404
        assert other.get(image_url).status_code == 404
        word_url = reader + '/word?revision=1'
        response = client.get(word_url)
        assert response.status_code == 200 and response.headers['Content-Type'] == DOCX
        lines = [p.text for p in Document(BytesIO(response.content)).paragraphs]
        assert result_text in lines and PROTOCOL in lines
        assert figure['caption'] in lines and 'A  Text-free synthetic line plot.' in lines
        with ZipFile(BytesIO(response.content)) as archive:
            assert png in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        assert client.get(word_url).content == response.content
        assert len(request(client, 'GET', root)['versions']) == 1
        assert other.get(word_url).status_code == 404


def record_candidate_citation(client, literature, search, reference, context, metadata, quote):
    evidence_path = literature + '/evidence/claims'
    claim = request(client, 'POST', evidence_path, status=201, key='candidate-claim', json=dict(
        content=quote, context=context, output_language='en',
    ))
    claim_path = evidence_path + '/' + claim['id']
    evidence = request(client, 'POST', claim_path + '/evidence', status=201, key='candidate-quote', json=dict(
        claim_revision=claim['revision'], project_reference_id=reference['id'], source_kind='abstract',
        search_id=search['id'], quote=quote,
    ))
    support = request(client, 'POST', claim_path + '/reviews', status=201, key='candidate-support', json=dict(
        claim_revision=claim['revision'], project_reference_id=reference['id'], evidence_ids=[evidence['id']],
        status='supported', relevance='related', reason='Checked the exact sentence against the saved synthetic abstract.',
        narrowed_statement='', limitations='Synthetic abstract only.',
    ))
    return dict(claim_id=claim['id'], claim_revision=claim['revision'],
                bindings=[dict(review_id=support['id'], metadata_version_id=metadata['id'])])


def test_customer_narrative_review_exports_suggested_excerpts_and_review_structure():
    with TestClient(app) as client:
        sign_in(client, 'review-to-word@manuscript.test', 'customer')
        project = sci_project(client, 'narrative_review')
        draft, _, _, reference, quote = selected_pubmed_reference(client, project, 'en')
        root, fixed_base = create_fact(client, project, body(methods={}, citation_draft=draft))
        selected = fixed_base['citation_snapshot']['paragraphs'][0]['fragments'][0]['bindings'][0]
        evidence, metadata = selected['evidence'][0], selected['metadata_source']
        bundle = request(client, 'POST', root + '/writing-previews', status=201, key='preview', json=article_request(
            'narrative_review', selected_evidence_ids=[evidence['id']],
        ))
        wire = json.loads(json.loads(bundle['wire_json'])['input'])
        assert not wire['sources'] and not wire['illustrations']
        assert wire['evidence'][0]['quote'] == quote and wire['evidence'][0]['reading_scope'] == 'abstract'
        provider = SciFixtureProvider(dict(
            title=dict(text='Narrative review of a synthetic protocol fixture'),
            abstract=dict(text='The review considers the scope of the acquired fixture abstract.'),
            introduction=dict(text='This engineering exercise concerns an example protocol description.'),
            literature_scope=dict(text='Only the saved synthetic abstract was read.'),
            themes=dict(text=quote, evidence_aliases=['e1']),
            discussion=dict(text='Full text was unavailable for this engineering exercise.'),
            conclusion=dict(text='The available evidence supports only the quoted account.'),
        ))
        reader, candidate = submit_candidate(client, project, root, bundle, provider)
        theme = next(section for section in candidate['sections'] if section['id'] == 'themes')['paragraphs'][0]
        assert theme['suggested_evidence_aliases'] == ['e1'] and theme['citations'] == []
        assert candidate['article_type'] == 'narrative_review' and not candidate['results_groups']
        draft = request(client, 'GET', reader + '?revision=1')['draft']
        theme = next(section for section in draft['sections'] if section['id'] == 'themes')['paragraphs'][0]
        [part] = theme['parts']
        assert part['text'] == quote
        [cite] = part['citations']
        assert cite['number'] == 1 and cite['project_reference_id'] == reference['id']
        assert cite['title'] == metadata['metadata']['title']
        assert cite['excerpts'] == [dict(id=evidence['id'], quote=quote, reading_scope='abstract')]
        response = client.get(reader + '/word?revision=1')
        assert response.status_code == 200 and response.headers['Content-Type'] == DOCX
        document = Document(BytesIO(response.content))
        headings = [p.text for p in document.paragraphs if p.style.name == 'Heading 1']
        assert {'Literature sources and inclusion scope', 'Thematic synthesis', 'Conclusion', 'References'} <= set(headings)
        assert 'Results' not in headings
        lines = [p.text for p in document.paragraphs]
        assert all('No computed Results selected.' not in text and 'Ethics information:' not in text for text in lines)
        assert quote + '[1]' in lines and '[1] ' + draft['references'][0]['text'] in lines
        assert len(request(client, 'GET', root)['versions']) == 1
