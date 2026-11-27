import json
from base64 import b64decode
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.adapters.research_figure_render import render_figure
from app.domain.manuscript_writing.frozen import wire_payload
from app.domain.research_results.execution import run_research_figure_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_sci_workflow import article_request, sci_project
from tests.api.test_customer_workspace import sign_in
from tests.api.test_file_batches import register
from tests.api.test_manuscripts import body
from tests.helpers.ocr_samples import ocr_result
from tests.integration.test_customer_sci_to_word import (
    SciFixtureProvider, create_fact, request, selected_pubmed_reference, submit_candidate,
)


def upload_panel(client, project, index, color):
    image = BytesIO()
    Image.new('RGB', (40, 30), color).save(image, format='PNG')
    name = f'panel-{index}.png'
    url, batch, item, raw = register(client, {'id': project.rsplit('/', 1)[-1]}, image.getvalue(), name, key=f'panel-{index}')
    saved = request(client, 'POST', f"{url}/{batch['id']}/items/{item['client_id']}", status=202,
                    files={'file': (name, raw)})
    task = saved['task']
    assert run_parse_file_task(task['id'], task['revision'], parser=ocr_result)['status'] == 'succeeded'
    return saved['file_id']


def word_image_section(data):
    document = Document(BytesIO(data))
    heading = None
    image_sections = []
    for paragraph in document.paragraphs:
        if paragraph.style.name.startswith('Heading'):
            heading = paragraph.text
        if paragraph._p.xpath('.//w:drawing'):
            image_sections.append(heading)
    return document, image_sections


@pytest.mark.parametrize(('article_type', 'caption'), [('research', None), ('narrative_review', 'Two panels supplied for this fixture.')])
def test_sci_composed_figure_is_frozen_in_the_confirmed_chapter_and_word(article_type, caption, tmp_path):
    with TestClient(app) as client:
        sign_in(client, f'figure-word-{article_type}@example.test', 'customer')
        project = sci_project(client, article_type)
        template_url = project + '/sci-template'
        state = request(client, 'GET', template_url)
        style = 'review' if article_type == 'narrative_review' else 'research'
        template = next(row for row in state['templates'] if row['id'] == f'frontiers-genetics-{style}-v1')
        custom_id = 'sci-section-0123456789abcdef0123456789abcdef'
        outline = [*template['sections'][:-1], dict(id=custom_id, en='Image record', zh='图像记录'), template['sections'][-1]]
        selected = request(client, 'PUT', template_url, json=dict(
            expected_revision=state['revision'], template_id=template['id'], figure_workflow=True, sections=outline,
            **({'combine_review_topics': True} if article_type == 'narrative_review' else {}),
        ))
        assert selected['figure_workflow'] is True

        source_ids = [upload_panel(client, project, 1, 'darkblue'), upload_panel(client, project, 2, 'green')]
        created = request(client, 'POST', project + '/sci-figures', status=201, key='composed',
                          json=dict(title='Combined illustration', file_ids=source_ids, columns=2))
        task = created['task']
        result = run_research_figure_task(task['id'], task['revision'], engine=render_figure, staging_directory=tmp_path / 'staging')
        assert result['status'] == 'succeeded', result
        figure = request(client, 'GET', project + '/sci-figures/' + created['id'])
        member = next(member for member in figure['members'] if member['role'] == 'figure' and member['format'] == 'png')
        composed_png = client.get(member['download_url']).content
        assert composed_png.startswith(b'\x89PNG\r\n\x1a\n')

        resources = project + '/sci-resources'
        state = request(client, 'GET', resources)
        assert custom_id in {chapter['id'] for chapter in state['chapters']}
        placement = dict(figure_id=figure['id'], chapter_id=custom_id)
        if caption is not None:
            placement['caption'] = caption
        saved = request(client, 'PUT', resources, json=dict(expected_revision=state['revision'], placements=[placement]))
        assert saved['placements'] == [dict(placement, caption=caption or '')]
        if caption is None:
            assert request(client, 'PUT', resources, json=dict(expected_revision=state['revision'],
                           placements=[dict(placement, caption='  ')])) == saved
        plan = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
        assert not plan['sci_figures_need_configuration']
        assert [item['figure_id'] for item in plan['sci_figures']] == [figure['id']]
        assert all(item['selection']['id'] not in source_ids for item in plan['materials'])

        bibliography, quote = None, None
        if article_type == 'narrative_review':
            bibliography, _, _, _, quote = selected_pubmed_reference(client, project, 'en')
        root, base = create_fact(client, project, body(title=plan['title'], methods={}, paper_plan_token=plan['token'],
                                                       citation_draft=bibliography))
        assert [item['id'] for item in base['sources']] == [figure['id']]
        evidence = []
        if bibliography:
            evidence = [base['citation_snapshot']['paragraphs'][0]['fragments'][0]['bindings'][0]['evidence'][0]['id']]
        capabilities = request(client, 'GET', root + '/writing-previews?capabilities_only=true')['capabilities']
        assert capabilities['max_input_tokens'] == 200_000
        preview = request(client, 'POST', root + '/writing-previews', status=201, key='preview',
                          json=article_request(article_type, selected_source_ids=[figure['id']], selected_evidence_ids=evidence))
        assert preview['execution_contract']['sci_initial_capacity'] is True
        assert preview['execution_contract']['max_input_allowance'] == 200_000
        payload = wire_payload(preview['wire_json'])
        assert [(image['number'], image['section_id']) for image in payload['illustrations']] == [(1, custom_id)]
        [figure_context] = payload['initial_figure_context']
        assert (figure_context['number'], figure_context['section_ids']) == (1, [custom_id])
        assert figure_context['caption'] == (caption or 'Author-supplied illustration.')
        [message] = json.loads(preview['wire_json'])['input']
        [visual] = [part for part in message['content'] if part['type'] == 'input_image']
        media, pixels = visual['image_url'].split(',', 1)
        assert media == 'data:image/png;base64' and visual['detail'] == 'high'
        with Image.open(BytesIO(b64decode(pixels))) as packed, Image.open(BytesIO(composed_png)) as source:
            with source.copy() as expected:
                expected.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                assert packed.size == expected.size
                assert packed.convert('RGB').tobytes() == expected.convert('RGB').tobytes()
        output = {sid: dict(text='Synthetic fixture prose.') for sid in payload['writing_scope']['output_section_ids']}
        if bibliography:
            output['themes'] = dict(text=quote, evidence_aliases=['e1'])
        reader, _ = submit_candidate(client, project, root, preview, SciFixtureProvider(output))

        def read_word():
            response = client.get(reader + '/word?revision=1')
            assert response.status_code == 200, response.text
            doc, embedded_sections = word_image_section(response.content)
            assert embedded_sections == ['Image record']
            assert any((caption or 'Author-supplied illustration.') in paragraph.text for paragraph in doc.paragraphs)
            assert [part.blob for part in doc.part.related_parts.values() if part.content_type == 'image/png'] == [composed_png]

        read_word()
        request(client, 'PUT', resources, json=dict(expected_revision=saved['revision'], placements=[]))
        read_word()
