"""Real customer, PostgreSQL and DOCX paths with offline synthetic evidence."""
from copy import deepcopy
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
from app.domain.literature.service import digest
from app.domain.manuscript_writing.bundle import build_bundle, validate_bundle
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.domain.manuscript_writing.live_review_candidate import body_digest
from app.domain.model_usage.service import ModelUsageService
from app.domain.tasks.execution import run_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_sci_workflow import article_request, sci_project
from tests.api.test_customer_workspace import sign_in
from tests.api.test_file_batches import register
from tests.api.test_literature import create as create_search
from tests.api.test_literature_citations import CitationNcbi, binding, draft_body, paragraph
from tests.api.test_manuscript_writing_language import approve
from tests.api.test_manuscript_writing_live import LiveFixture
from tests.api.test_manuscript_writing_live_review import decision
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


def submit_candidate(client, project, root, bundle, owner, provider, *, resume=False):
    assert bundle['execution_contract']['schema_version'] == 4
    bundle_ref = dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
    auth = request(client, 'POST', project + '/writing-authorizations', status=201, key='authorize', json=dict(
        schema_version=2, confirmed=True, tasks=[dict(logical_task_id='article', bundles=[bundle_ref])],
    ))
    payload = dict(schema_version=2, authorization_id=auth['id'], logical_task_id='article', **bundle_ref)
    task = request(client, 'POST', root + '/writing-requests', status=202, key='write', json=payload)['task']
    usage = ModelUsageService(owner)
    for scope, identifier in [('user', owner), ('project', task['project_id']), ('task', task['id'])]:
        if usage.get_budget(scope, identifier)['limit_micro_usd'] is None:
            usage.set_budget(scope, identifier, 5_000_000, 0)
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
    context = request(client, 'GET', path + '/review-context')
    provenance = context['candidate']['writing_provenance']
    assert provenance['provider_provenance'] == 'synthetic_fixture'
    assert provenance['verification_status'] == 'pending'
    return path, context


def publish_word(client, root, path, scientific_decision):
    science = request(client, 'POST', path + '/reviews', status=201, key='science', json=scientific_decision)
    payload = dict(schema_version=2, expected_revision=1, review_id=science['id'], review_sha256=science['review_sha256'])
    assert client.post(path + '/publish', headers={'Idempotency-Key': 'unreviewed'}, json=payload).status_code == 409
    language_context = request(client, 'GET', path + '/reviews/' + science['id'] + '/language-context')
    language_decision = approve(language_context)
    for item, item_decision in zip(language_context['inventory'], language_decision['decisions']):
        if item['kind'] == 'image':
            assert item['language_known'] and item['no_text']
            item_decision.update(decision='no_text', reason='Inspected the text-free synthetic plot.')
    language = request(client, 'POST', path + '/language-reviews', status=201, key='language', json=language_decision)
    payload.update(language_review_id=language['id'], language_review_sha256=language['artifact_sha256'])
    published = request(client, 'POST', path + '/publish', status=201, key='publish', json=payload)['versions'][0]
    assert published['revision'] == 2 and published['snapshot'] == language['candidate']
    replay = request(client, 'POST', path + '/publish', key='publish', json=payload)['versions'][0]
    assert replay['id'] == published['id']
    assert run_task(published['task_id'], 1)['status'] == 'succeeded'
    fixed = request(client, 'GET', root + '/versions/2')
    assert fixed['id'] == published['id'] and fixed['snapshot'] == published['snapshot']
    job = request(client, 'POST', root + '/versions/2/exports', status=201, key='export', json={})
    assert run_task(job['task_id'], 1)['status'] == 'succeeded'
    export = request(client, 'GET', root + '/exports/' + job['id'])
    assert export['status'] == 'succeeded'
    download = client.get(export['download_url'])
    assert download.status_code == 200, download.text
    assert download.headers['Content-Type'] == DOCX
    assert '.docx' in download.headers['Content-Disposition']
    assert sha256(download.content).hexdigest() == export['sha256']
    return fixed['snapshot'], export['download_url'], download.content


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
    source = dict(kind='document_version', id=document_id, file_id=file_id)
    version = request(client, 'POST', project + '/manuscript-figure-language-versions', status=201, key='figure', json=dict(
        source=source | dict(image_id=image['id']), original_sha256=image['sha256'],
        mode='no_text_confirmation', output_language='en', reason='Inspected the synthetic line plot for any lettering.',
        title='Synthetic line plot', caption='Direction of the supplied synthetic observation.',
    ))
    assert version['sha256'] == sha256(raw).hexdigest()
    figure = dict(kind='figure_language_version', id=version['id'], file_id=file_id, role='image_observation')
    return source | dict(role='user_results'), figure, raw


def test_customer_research_freezes_uploaded_result_numeric_context_and_figure_in_word():
    with TestClient(app) as client, TestClient(app) as other:
        owner = sign_in(client, 'research-to-word@manuscript.test', 'customer')
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
        path, context = submit_candidate(client, project, root, bundle, owner, provider, resume=True)
        science = decision(context)
        next(p for p in science['paragraphs'] if p['paragraph_id'] == 'results:1').update(
            classification='context_claim', scientific_basis='Compared the reported observation and panel with the supplied fixture.',
            numeric_bindings=[dict(occurrence=0, kind='context', **result_number)],
        )
        next(p for p in science['paragraphs'] if p['paragraph_id'] == 'discussion:1').update(
            classification='study_claim', scientific_basis='Verified the direction and source in the supplied report.',
        )
        next(p for p in science['paragraphs'] if p['paragraph_id'] == 'materials_and_methods:1').update(
            classification='context_claim', scientific_basis='Checked the protocol number against the user-provided method.',
            numeric_bindings=[dict(occurrence=0, kind='context', **method_number)],
        )
        corrected = deepcopy(science)
        candidate = deepcopy(context['candidate'])
        altered = 'The supplied fixture describes a directional pattern.'
        discussion = next(section for section in candidate['sections'] if section['id'] == 'discussion')
        discussion['paragraphs'][0]['text'] = altered
        corrected_discussion = next(p for p in corrected['paragraphs'] if p['paragraph_id'] == 'discussion:1')
        corrected_discussion.update(corrected_text=altered, text_sha256=digest(altered))
        corrected['consistency']['body_sha256'] = body_digest(candidate)
        missing_source = request(client, 'POST', path + '/reviews', status=422,
                                 key='correction-without-source', json=corrected)
        assert missing_source['detail']['code'] == 'manuscript_writing_review_invalid'
        corrected_discussion['source_aliases'] = ['s1']
        changed = request(client, 'POST', path + '/reviews', status=201, key='science-correction', json=corrected)
        changed_discussion = next(section for section in changed['candidate']['sections'] if section['id'] == 'discussion')
        assert changed_discussion['paragraphs'][0]['source_ids'] == [result_source['id']]
        fixed, url, raw = publish_word(client, root, path, science)
        assert fixed['article_type'] == 'research'
        assert fixed['keywords'] == ['synthetic fixture']
        methods = next(section for section in fixed['sections'] if section['id'] == 'materials_and_methods')
        assert methods['paragraphs'][0]['numeric_bindings'][0]['kind'] == 'context'
        result = next(section for section in fixed['sections'] if section['id'] == 'results')['paragraphs'][0]
        assert result['numeric_bindings'][0]['kind'] == 'context' and result['source_ids'] == [result_source['id']]
        discussion = next(section for section in fixed['sections'] if section['id'] == 'discussion')['paragraphs'][0]
        assert discussion['source_ids'] == [result_source['id']]
        paragraphs = [p.text for p in Document(BytesIO(raw)).paragraphs]
        assert result_text in paragraphs and PROTOCOL in paragraphs
        with ZipFile(BytesIO(raw)) as archive:
            assert png in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        assert other.get(url).status_code == 404


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


def assert_review_journal_adaptation(client, project, root, fixed, original_headings):
    from tests.api.test_journal_format import guide, target
    from tests.api.test_journals import profile, request as recommendation

    journals = project + '/journals'
    p = request(client, 'POST', journals + '/profiles', status=201, key='review-profile', json=profile())
    r = request(client, 'POST', journals + '/recommendations', status=202, key='review-recommendation',
                json=recommendation(article_type='review', hard_filters=[]))
    assert run_task(r['task']['id'], 1)['status'] == 'succeeded'
    rules = 'Required sections: Literature sources and inclusion scope | Thematic synthesis\nBody font size: 12 pt'
    g = request(client, 'POST', journals + '/guides', status=201, key='review-guide',
                json=guide(p, source_text=rules, article_types=['review']))
    t = request(client, 'POST', journals + '/targets', status=201, key='review-target',
                json=target(p, r, g, article_type='review'))
    parent = request(client, 'GET', root + '/versions/2')
    combination = dict(target_id=t['id'], manuscript=dict(id=root.rsplit('/', 1)[1], revision=2))
    check = request(client, 'POST', journals + '/checks', status=202, key='review-check', json=combination)
    assert run_task(check['task']['id'], 1)['status'] == 'succeeded'
    check_result = request(client, 'GET', journals + '/checks/' + check['id'])['result']
    states = {item['key']: item['status'] for item in check_result['items']}
    assert states['required_sections'] == 'pass' and states['body_font_size_pt'] == 'mismatch'
    combination['check_id'] = check['id']
    combination['manuscript']['version_id'] = parent['id']
    preview = request(client, 'POST', journals + '/adaptations/preview', json=combination)
    assert [action['key'] for action in preview['actions']] == ['body_font_size_pt']
    adoption = request(client, 'POST', journals + '/adaptations', status=202, key='review-adapt', json=combination | dict(
        expected_current_revision=2, preview_sha256=preview['preview_sha256'],
        selected_action_ids=[preview['actions'][0]['id']],
    ))
    task = run_task(adoption['task']['id'], 1)
    assert task['status'] == 'succeeded', task
    output = request(client, 'GET', journals + '/adaptations/' + adoption['id'])['result']['output']
    assert output['parent_version_id'] == parent['id'] and output['revision'] == 3
    assert run_task(output['task_id'], 1)['status'] == 'succeeded'
    adapted = request(client, 'GET', root + '/versions/3')['snapshot']
    for key in ('sections', 'sources', 'references', 'citation_snapshot', 'writing_provenance'):
        assert adapted[key] == fixed[key]
    job = request(client, 'POST', root + '/versions/3/exports', status=201, key='review-adapted-export', json={})
    assert run_task(job['task_id'], 1)['status'] == 'succeeded'
    export = request(client, 'GET', root + '/exports/' + job['id'])
    download = client.get(export['download_url'])
    assert download.status_code == 200 and sha256(download.content).hexdigest() == export['sha256']
    doc = Document(BytesIO(download.content))
    assert [p.text for p in doc.paragraphs if p.style.name == 'Heading 1'] == original_headings
    assert doc.styles['Normal'].font.size.pt == 12


def test_customer_narrative_review_exports_checked_literature_and_review_structure():
    with TestClient(app) as client:
        owner = sign_in(client, 'review-to-word@manuscript.test', 'customer')
        project = sci_project(client, 'narrative_review')
        literature = project + '/literature'
        response = create_search(client, project.rsplit('/', 1)[-1])
        assert response.status_code == 202, response.text
        search = response.json()
        assert run_literature_task(search['id'], search['revision'], client=CitationNcbi(3))['status'] == 'succeeded'
        references = request(client, 'GET', literature + '/references')['items']
        reference = next(ref for ref in references if ref['record']['abstract'])
        quote = reference['record']['abstract'][0]['text']
        claim = request(client, 'POST', literature + '/evidence/claims', status=201, key='initial-claim', json=dict(
            content=quote, context='Synthetic abstract selection', output_language='en',
        ))
        claim, binding_ref, metadata, _ = binding(client, literature, search, reference, claim)
        draft = request(client, 'POST', literature + '/citations/drafts', status=201, key='citation-draft',
                        json=draft_body(paragraph(claim, binding_ref)))
        root, fixed_base = create_fact(client, project, body(methods={}, citation_draft=dict(id=draft['id'], revision=1)))
        evidence = fixed_base['citation_snapshot']['paragraphs'][0]['fragments'][1]['bindings'][0]['evidence'][0]
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
        path, context = submit_candidate(client, project, root, bundle, owner, provider)
        science = decision(context)
        bound = record_candidate_citation(client, literature, search, reference, context['claim_contexts']['themes:1'], metadata, quote)
        next(p for p in science['paragraphs'] if p['paragraph_id'] == 'themes:1').update(
            classification='literature_claim', claim=bound, scientific_basis='Compared exact prose with the reviewed abstract.',
        )
        fixed, _, raw = publish_word(client, root, path, science)
        assert fixed['article_type'] == 'narrative_review' and not fixed['results_groups']
        assert len(fixed['references']) == 1
        theme = next(section for section in fixed['sections'] if section['id'] == 'themes')['paragraphs'][0]
        assert theme['text'] == quote + ' (1)'
        assert theme['citations'][0]['review_id'] == bound['bindings'][0]['review_id']
        document = Document(BytesIO(raw))
        headings = [p.text for p in document.paragraphs if p.style.name == 'Heading 1']
        assert {'Literature sources and inclusion scope', 'Thematic synthesis', 'Conclusion', 'References'} <= set(headings)
        assert 'Results' not in headings
        assert any(item['id'] == 'missing:ethics' for item in fixed['issues'])
        assert all('No computed Results selected.' not in p.text and 'Ethics information:' not in p.text
                   for p in document.paragraphs)
        assert theme['text'] in [p.text for p in document.paragraphs]
        assert any(p.text.startswith('(1) ') and metadata['metadata']['title'] in p.text for p in document.paragraphs)
        assert_review_journal_adaptation(client, project, root, fixed, headings)
