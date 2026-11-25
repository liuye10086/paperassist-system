import base64
from io import BytesIO
import json

from alembic import command
from docx import Document
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.core.exceptions import StorageError
from app.db.database import alembic_config, database_connection, migration_connection
from app.domain.manuscript_writing.bundle import safe_text
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.domain.manuscript_writing.frozen import wire_payload
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_project_types import SCI_SETTINGS, create, project_body, project_path
from tests.api.test_customer_sci_workflow import article_request
from tests.api.test_customer_workspace import sign_in
from tests.api.test_file_batches import register
from tests.api.test_manuscripts import body
from tests.integration.test_customer_sci_draft_revision import ChatStreamFixture, queue_write
from tests.integration.test_customer_sci_to_word import (
    SciFixtureProvider, create_fact, request, selected_pubmed_reference, submit_candidate,
)


def image_upload(client, project, name, image_format):
    image = BytesIO()
    Image.new('RGB', (32, 20), 'navy').save(image, format=image_format)
    raw = image.getvalue()
    base, batch, item, _ = register(client, {'id': project.rsplit('/', 1)[1]}, raw, name, name)
    uploaded = request(client, 'POST', f"{base}/{batch['id']}/items/{item['client_id']}",
                       files={'file': (name, raw)}, status=202)
    if task := uploaded.get('task'):
        def offline_ocr(*args, **kwargs):
            raise StorageError('parse_environment_unavailable', 'No OCR in this fixture.', 409)
        assert run_parse_file_task(task['id'], task['revision'], parser=offline_ocr)['status'] == 'failed'
    return uploaded['file_id'], raw


def assert_visual_input(part, media_type, original):
    prefix = f'data:{media_type};base64,'
    assert part['type'] == 'input_image' and part['detail'] == 'high' and part['image_url'].startswith(prefix)
    raster = base64.b64decode(part['image_url'][len(prefix):], validate=True)
    with Image.open(BytesIO(raster)) as received, Image.open(BytesIO(original)) as expected:
        assert received.format == expected.format and received.size == expected.size
        assert all(abs(actual - source) <= 3 for actual, source in zip(received.getpixel((0, 0)), expected.getpixel((0, 0))))


def test_review_freezes_auto_and_specified_figures_and_exports_each_in_its_section():
    with TestClient(app) as client:
        sign_in(client, 'review-images@manuscript.test', 'customer')
        settings = {k: v for k, v in SCI_SETTINGS.items() if k != 'figure_findings'}
        project = project_path(create(client, 'review', **project_body('sci', sci_settings={
            **settings, 'article_type': 'narrative_review', 'review_sections': [],
        })))
        png, png_bytes = image_upload(client, project, 'overview.png', 'PNG')
        jpg, jpg_bytes = image_upload(client, project, 'detail.jpg', 'JPEG')
        tif, _ = image_upload(client, project, 'synthesis.tif', 'TIFF')
        notes = project + '/paper-materials'
        view = request(client, 'GET', notes)
        assert view.get('review_figure_placement') is True
        assert {t['id'] for t in view['targets']} == {
            'sci:section:introduction', 'sci:review-topic', 'sci:section:discussion', 'sci:section:conclusion'}
        caption = 'Conceptual illustration. Source: public example, CC BY 4.0 https://creativecommons.org/licenses/by/4.0/'
        input_note = dict(expected_revision=0, file_id=jpg, target_id='sci:section:introduction', result=caption)
        assert request(client, 'PUT', notes + '/' + jpg, json=input_note)['revision'] == 1
        assert request(client, 'PUT', notes + '/' + jpg, json=input_note)['revision'] == 1
        request(client, 'PUT', notes + '/' + tif, json=dict(expected_revision=0, file_id=tif,
                target_id='sci:section:conclusion', result=''))
        plan = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
        theme = plan['sections'][0]['id']
        assert {m['selection']['id']: m['section_id'] for m in plan['materials']} == {
            png: theme, jpg: 'introduction', tif: 'conclusion'}
        citation, *_ = selected_pubmed_reference(client, project, 'en')
        root, base = create_fact(client, project, body(title=plan['title'], methods={}, paper_plan_token=plan['token'],
                                                      citation_draft=citation))
        evidence = base['citation_snapshot']['paragraphs'][0]['fragments'][0]['bindings'][0]['evidence'][0]
        selection = article_request(
            'narrative_review', document_context_version='selected-text-v1',
            selected_evidence_ids=[evidence['id']], selected_source_ids=[png, jpg, tif])
        previews = root + '/writing-previews'
        bundle = request(client, 'POST', previews, status=201, key='preview', json=selection)
        wire = json.loads(json.loads(bundle['wire_json'])['input'])
        assert [(f['number'], f['section_id']) for f in wire['illustrations']] == [
            (1, 'introduction'), (2, theme), (3, 'conclusion')]
        assert wire['illustrations'][0]['caption'] == caption
        assert 'detail.jpg' not in bundle['wire_json']
        sections = {key: dict(text='This review describes the scope of the literature.')
                    for key in wire['writing_scope']['output_section_ids']}
        sections['introduction'] = dict(text='See Figure 1 for the conceptual illustration.')
        sections[theme] = dict(text=evidence['quote'], evidence_aliases=['e1'])
        # The provider may reuse a fact-draft paragraph identity while replacing its whole text.
        sections['conclusion']['id'] = 'review-illustrations:conclusion'
        reader, original = submit_candidate(client, project, root, bundle, SciFixtureProvider(sections))
        rendered = request(client, 'GET', reader + '?revision=1')['draft']
        figure_ids = []
        for section in rendered['sections']:
            assert all(not g['figures'] for g in section['groups'])
            for paragraph in section['paragraphs']:
                for figure in paragraph.get('figures', []):
                    figure_ids.append(figure['id'])
                    prose = ' '.join(part['text'] for part in paragraph['parts'])
                    assert prose.count(f"Figure {figure['number']}") == 1
        assert figure_ids == [jpg, png, tif]
        assert client.get(reader + '/figures/1?revision=1').content == jpg_bytes
        assert client.get(reader + '/figures/2?revision=1').content == png_bytes
        assert client.get(reader + '/figures/3?revision=1').content.startswith(b'\x89PNG')
        word = client.get(reader + '/word?revision=1')
        assert word.status_code == 200, word.text[:100] if word.status_code != 200 else ''
        document = Document(BytesIO(word.content))
        assert len(document.inline_shapes) == 3
        assert caption in [p.text for p in document.paragraphs]

        revision = selection | dict(revision_of_request_id=reader.split('/')[-2], target_sections=['introduction'],
                                    instructions='Clarify what Figure 1 illustrates.')
        revised_bundle = request(client, 'POST', previews, status=201, key='revise-with-image', json=revision)
        assert request(client, 'POST', previews, key='revise-with-image', json=revision) == revised_bundle
        assert revised_bundle['execution_contract']['scope_figure_input'] is True
        [message] = json.loads(revised_bundle['wire_json'])['input']
        text, visual = message['content']
        assert message['role'] == 'user' and text['type'] == 'input_text'
        assert_visual_input(visual, 'image/jpeg', jpg_bytes)
        payload = wire_payload(revised_bundle['wire_json'])
        assert [s['id'] for s in payload['original_draft']] == ['introduction']
        assert [item['number'] for item in payload['illustrations']] == [1, 2, 3]
        assert payload['revision_figure_context'] == [
            dict(number=1, section_ids=['introduction'], title='Review illustration', caption=caption),
        ]
        revised_text = 'Figure 1 illustrates the scope of this review.'
        task = queue_write(client, project, root, revised_bundle, 'revise-with-image')
        provider = ChatStreamFixture(observe=lambda: None, prefix='Figure 1 illustrates',
                                     paragraphs={'introduction': {'text': revised_text}})
        finished = run_manuscript_writing_task(task['id'], task['revision'], provider=provider)
        assert finished['status'] == 'succeeded', finished
        assert provider.posts == [revised_bundle['wire_json']]
        revised_path = root + '/writing-requests/' + task['id']
        revised = request(client, 'GET', revised_path)
        assert [s for s in revised['candidate']['sections'] if s['id'] != 'introduction'] == [
            s for s in original['sections'] if s['id'] != 'introduction']
        changes = request(client, 'GET', revised_path + '/draft-reader?revision=1')['changes']
        assert [(change['section_id'], change['after']) for change in changes] == [('introduction', [revised_text])]

        advice = revision | dict(revision_of_request_id=task['id'], target_sections=['conclusion'],
                                 instructions='What could make Figure 3 more useful here?', draft_advice=True)
        advice_bundle = request(client, 'POST', previews, status=201, key='advice-with-image', json=advice)
        [message] = json.loads(advice_bundle['wire_json'])['input']
        _, visual = message['content']
        assert_visual_input(visual, 'image/png', client.get(reader + '/figures/3?revision=1').content)
        assert [row['number'] for row in wire_payload(advice_bundle['wire_json'])['revision_figure_context']] == [3]
        advice_task = queue_write(client, project, root, advice_bundle, 'advice-with-image')
        advice_text = 'Explain how Figure 3 relates to the conclusion.'
        provider = ChatStreamFixture(observe=lambda: None, prefix='Explain how Figure 3', advice=advice_text)
        finished = run_manuscript_writing_task(advice_task['id'], advice_task['revision'], provider=provider)
        assert finished['status'] == 'succeeded', finished
        assert provider.posts == [advice_bundle['wire_json']]
        advice_view = request(client, 'GET', root + '/writing-requests/' + advice_task['id'] + '/draft-reader?revision=1')
        assert advice_view['advice'] == advice_text and advice_view['draft'] is None

        text_bundle = request(client, 'POST', previews, status=201, key='advice-text-only',
                              json=advice | dict(target_sections=['discussion'], instructions='Explain the discussion.'))
        assert isinstance(json.loads(text_bundle['wire_json'])['input'], str)
        assert 'revision_figure_context' not in wire_payload(text_bundle['wire_json'])

        request(client, 'PUT', notes + '/' + tif, json=dict(expected_revision=1, file_id=tif, target_id=None, result=''))
        current = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
        assert current['token'] != plan['token']
        assert next(m for m in current['materials'] if m['selection']['id'] == tif)['section_id'] == theme
        assert request(client, 'GET', reader + '?revision=1')['draft'] == rendered


def test_auto_placement_uses_a_unique_saved_theme_and_recovers_a_removed_target(postgres_migration_config):
    with TestClient(app) as client, TestClient(app) as foreign:
        sign_in(client, 'review-themes@manuscript.test', 'customer')
        uploader = sign_in(foreign, 'unreleased-figure@manuscript.test', 'customer')
        settings = {k: v for k, v in SCI_SETTINGS.items() if k != 'figure_findings'}
        themes = [dict(id='overview', heading='Disease mechanisms', content='Mechanisms of disease.'),
                  dict(id='biomarkers', heading='Biomarkers', content='Markers reported in the literature.')]
        settings.update(article_type='narrative_review', review_sections=themes)
        project = project_path(create(client, 'themes', **project_body('sci', sci_settings=settings)))
        biomarker, _ = image_upload(client, project, 'biomarkers_overview.png', 'PNG')
        other, _ = image_upload(client, project, 'summary.png', 'PNG')
        hidden, _ = image_upload(client, project, 'not-released.png', 'PNG')
        with database_connection(write=True) as db:
            db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (uploader, hidden))
        notes = project + '/paper-materials/'
        def placement():
            plan = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
            by_id = {s['id']: s['label'] for s in plan['sections']}
            return {m['selection']['id']: by_id[m['section_id']] for m in plan['materials']}
        assert placement() == {biomarker: 'Biomarkers', other: 'Disease mechanisms'}
        request(client, 'PUT', notes + other, json=dict(expected_revision=0, file_id=other,
                target_id='sci:review:biomarkers', result=''))
        assert placement()[other] == 'Biomarkers'
        current = request(client, 'GET', project + '/sci-settings')
        request(client, 'PUT', project + '/sci-settings', json=dict(expected_revision=current['revision'],
                settings={**settings, 'review_sections': themes[:1]}))
        assert placement() == {biomarker: 'Disease mechanisms', other: 'Disease mechanisms'}
        [note] = request(client, 'GET', notes.rstrip('/'))['items']
        assert not note['target_available'] and note['target_label'] == 'Biomarkers'
        config = alembic_config()
        with migration_connection(write=True) as db:
            config.attributes.update(database_config=postgres_migration_config, connection=db.raw_connection)
            with pytest.raises(RuntimeError, match='Caption-free figure placements'):
                command.downgrade(config, '0090_material_submissions')


def test_license_url_is_exact_and_does_not_allow_private_locations():
    url = 'https://creativecommons.org/licenses/by/4.0/'
    assert safe_text(url) == url
    for invalid in [url + '?key=private', url + '#private', url + 'private', url.replace('https:', 'http:'),
                    url.replace('.org/', '.org.invalid/'), url.replace('//', '//user@'),
                    url.replace('by/4.0', 'private')]:
        with pytest.raises(StorageError):
            safe_text(invalid)
