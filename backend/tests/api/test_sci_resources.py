from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.adapters.research_figure_render import render_figure
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.db.database import database_connection
from app.domain.paper_materials import read_sci_settings
from app.domain.research_intake.sci_templates import configured_template
from app.domain.research_results.execution import run_research_figure_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_project_types import create, project_body, project_path
from tests.api.test_customer_sci_workflow import sci_project
from tests.api.test_customer_workspace import sign_in
from tests.api.test_file_batches import register
from tests.helpers.ocr_samples import ocr_result


CUSTOM_SECTION = 'sci-section-0123456789abcdef0123456789abcdef'


def upload_png(client, project, name, *, finish_parse=False):
    stream = BytesIO()
    Image.new('RGB', (80, 40), 'red').save(stream, 'PNG')
    base, batch, item, content = register(client, {'id': project.rsplit('/', 1)[-1]}, stream.getvalue(), name, key=name)
    response = client.post(f'{base}/{batch["id"]}/items/{item["client_id"]}', files={'file': (name, content)})
    assert response.status_code == 202, response.text
    saved = response.json()
    if finish_parse:
        task = saved['task']
        assert run_parse_file_task(task['id'], task['revision'], parser=ocr_result)['status'] == 'succeeded'
    return saved['file_id']


def confirm_template(client, project, template_id, *, sections=None, workflow=None):
    path = project + '/sci-template'
    state = client.get(path).json()
    body = dict(expected_revision=state['revision'], template_id=template_id)
    if sections is not None:
        body['sections'] = sections
    if workflow is not None:
        body['figure_workflow'] = workflow
    response = client.put(path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def resolved_placements(project, owner):
    from app.domain.research_intake.sci_resources import resolve_sci_figures

    assets = ProjectStore(get_data_dir(), owner_id=owner, customer=True)
    with database_connection() as db:
        row = db.execute('SELECT * FROM projects WHERE id=%s', (project.rsplit('/', 1)[-1],)).fetchone()
        settings = read_sci_settings(db, row)
        template = configured_template(settings['article_type'], settings['template_id'], settings.get('template_sections'))
        return resolve_sci_figures(db, assets, row, settings, template)


@pytest.mark.parametrize(('kind', 'target', 'template_id', 'chapter_id'), [
    ('research', 'sci:figure:synthetic-figure-1', 'frontiers-genetics-research-v1', 'results'),
    ('narrative_review', 'sci:review:synthetic-section-1', 'frontiers-genetics-review-v1', 'themes'),
    ('narrative_review', 'sci:section:introduction', 'frontiers-genetics-review-v1', 'introduction'),
])
def test_sci_resources_preserve_legacy_notes_and_stale_placements(kind, target, template_id, chapter_id):
    with TestClient(app) as customer:
        owner = sign_in(customer, 'resource-owner@example.test', 'customer')
        project = sci_project(customer, kind)
        resource = project + '/sci-resources'
        empty = customer.get(resource)
        assert empty.status_code == 200, empty.text
        assert empty.json() == dict(revision=1, template_id=None, chapters=[], figures=[], placements=[])
        assert customer.put(resource, json=dict(expected_revision=1, placements=[])).status_code == 422

        old_figure = upload_png(customer, project, 'specified.png')
        unassigned_figure = upload_png(customer, project, 'source.png')
        note = customer.put(project + '/paper-materials/' + str(uuid4()), json=dict(
            expected_revision=0, file_id=old_figure, result='Saved image caption.', target_id=target))
        assert note.status_code == 200, note.text

        template = confirm_template(customer, project, template_id, workflow=True)
        assert template['figure_workflow'] is True
        sections = template['selected_sections']
        custom = dict(id=CUSTOM_SECTION, zh='特定小节', en='Specific subsection', level=2)
        template = confirm_template(customer, project, template_id, sections=[*sections[:-1], custom, sections[-1]])
        state = customer.get(resource).json()
        assert state['revision'] == template['revision']
        assert state['template_id'] == template_id
        assert [chapter['id'] for chapter in state['chapters']] == [s['id'] for s in sections[1:-1]] + [CUSTOM_SECTION]
        assert state['chapters'][-1]['label'] == '特定小节'
        assert [figure['id'] for figure in state['figures']] == [old_figure]
        assert customer.get(state['figures'][0]['preview_url']).status_code == 200
        assert state['placements'] == [dict(figure_id=old_figure, chapter_id=chapter_id, caption='Saved image caption.')]
        assert resolved_placements(project, owner) == ([], True)

        placement = dict(figure_id=old_figure, chapter_id=CUSTOM_SECTION, caption='Edited caption.')
        write = dict(expected_revision=state['revision'], placements=[placement])
        for rejected in (dict(placement, figure_id=unassigned_figure), dict(placement, chapter_id='references')):
            response = customer.put(resource, json=dict(write, placements=[rejected]))
            assert response.status_code == 422, response.text
            assert response.json()['detail']['code'] == 'sci_resources_invalid'
        assert customer.put(resource, json=dict(write, placements=[placement, placement])).status_code == 422
        saved = customer.put(resource, json=write)
        assert saved.status_code == 200, saved.text
        assert saved.json()['revision'] == state['revision'] + 1
        assert customer.put(resource, json=write).json() == saved.json()
        assert customer.put(resource, json=dict(write, placements=[])).status_code == 409
        frozen, unconfigured = resolved_placements(project, owner)
        assert not unconfigured
        assert {key: frozen[0][key] for key in placement} == placement
        assert frozen[0]['source_kind'] == 'original'
        assert frozen[0]['chapter_label'] == '特定小节'

        settings_path = project + '/sci-settings'
        settings = customer.get(settings_path).json()
        assert set(settings) == {'revision', 'settings'}
        assert 'figure_workflow' not in settings['settings'] and 'sci_figure_placements' not in settings['settings']
        update = customer.put(settings_path, json=dict(expected_revision=settings['revision'],
            settings=dict(settings['settings'], proposed_title='Changed project title')))
        assert update.status_code == 200, update.text
        assert customer.get(resource).json()['placements'] == [placement]

        template = confirm_template(customer, project, template_id, sections=sections)
        assert template['figure_workflow'] is True
        stale = customer.get(resource).json()
        assert CUSTOM_SECTION not in {chapter['id'] for chapter in stale['chapters']}
        assert stale['placements'] == [placement]
        assert resolved_placements(project, owner) == ([], True)
        removed = customer.put(resource, json=dict(expected_revision=stale['revision'], placements=[]))
        assert removed.status_code == 200, removed.text
        assert removed.json()['placements'] == []
        assert customer.get(resource).json()['placements'] == []
        assert resolved_placements(project, owner) == ([], False)


def test_sci_resources_is_customer_owner_scoped():
    with TestClient(app) as customer, TestClient(app) as other, TestClient(app) as analyst:
        sign_in(customer, 'resources-owner@example.test', 'customer')
        sign_in(other, 'resources-other@example.test', 'customer')
        sign_in(analyst, 'resources-analyst@example.test', 'analyst')
        sci = sci_project(customer) + '/sci-resources'
        thesis = project_path(create(customer, 'thesis', **project_body('thesis'))) + '/sci-resources'
        body = dict(expected_revision=1, placements=[])
        assert other.get(sci).status_code == other.put(sci, json=body).status_code == 404
        assert analyst.get(sci).status_code == analyst.put(sci, json=body).status_code == 403
        assert customer.get(thesis).status_code == customer.put(thesis, json=body).status_code == 403


def test_sci_resources_follow_edited_figure_and_keep_chapter_order(tmp_path):
    with TestClient(app) as customer:
        owner = sign_in(customer, 'resource-figures@example.test', 'customer')
        project = sci_project(customer)
        figures = project + '/sci-figures'
        resource = project + '/sci-resources'
        template = confirm_template(customer, project, 'frontiers-genetics-research-v1', workflow=True)
        pictured = upload_png(customer, project, 'picture.png', finish_parse=True)
        earlier = upload_png(customer, project, 'noted.png', finish_parse=True)
        note = customer.put(project + '/paper-materials/' + str(uuid4()), json=dict(
            expected_revision=0, file_id=earlier, result='Earlier caption.', target_id='sci:figure:synthetic-figure-1'))
        assert note.status_code == 200, note.text

        def create_figure(key, title, **revision):
            response = customer.post(figures, headers={'Idempotency-Key': key},
                                     json=dict(title=title, file_ids=[pictured, earlier], columns=2, **revision))
            assert response.status_code == 201, response.text
            return response.json()

        def finish(figure):
            task = run_research_figure_task(figure['task_id'], figure['task']['revision'], engine=render_figure,
                                            staging_directory=tmp_path / 'staging')
            assert task['status'] == 'succeeded', task
            return customer.get(figures + '/' + figure['id']).json()

        first = create_figure('figure-initial', 'Synthetic composite')
        revised = dict(figure_id=first['id'], chapter_id='introduction', caption='Composite caption.')
        write = dict(expected_revision=template['revision'], placements=[revised])
        assert customer.put(resource, json=write).status_code == 422
        assert first['id'] not in {figure['id'] for figure in customer.get(resource).json()['figures']}
        first = finish(first)
        assert customer.put(resource, json=dict(write, placements=[dict(revised, caption=' ')])).status_code == 422
        legacy = dict(figure_id=earlier, chapter_id='results', caption='Earlier caption.')
        saved = customer.put(resource, json=dict(write, placements=[legacy, revised]))
        assert saved.status_code == 200, saved.text
        assert [row['figure_id'] for row in saved.json()['placements']] == [first['id'], earlier]
        frozen, unconfigured = resolved_placements(project, owner)
        assert not unconfigured
        assert [row['figure_id'] for row in frozen] == [first['id'], earlier]
        assert frozen[0]['sha256'] == first['manifest_sha256']
        assert frozen[0]['source_kind'] == 'research_figure_version'
        assert [panel['label'] for panel in frozen[0]['panels']] == ['A', 'B']
        assert customer.get(frozen[0]['preview_url']).headers['content-type'] == 'image/png'

        second = create_figure('figure-revised', 'Revised synthetic composite', root_id=first['root_id'], expected_revision=1)
        assert {figure['id'] for figure in customer.get(resource).json()['figures']} == {first['id'], earlier}
        assert resolved_placements(project, owner)[0][0]['sha256'] == first['manifest_sha256']
        second = finish(second)
        current = customer.get(resource).json()
        assert {figure['id'] for figure in current['figures']} == {first['root_id'], earlier}
        updated = next(figure for figure in current['figures'] if figure['id'] == first['root_id'])
        assert updated['title'] == 'Revised synthetic composite' and second['id'] in updated['preview_url']
        assert current['placements'] == saved.json()['placements']
        assert resolved_placements(project, owner)[0][0]['sha256'] == second['manifest_sha256']

        first_chapter = 'introduction'
        sections = template['selected_sections']
        reshuffled = [sections[0], *(row for row in sections[1:] if row['id'] != first_chapter)]
        reshuffled.insert(-1, dict(next(row for row in sections if row['id'] == first_chapter), zh='改名后的小节'))
        template = confirm_template(customer, project, template['selected_template_id'], sections=reshuffled)
        frozen, unconfigured = resolved_placements(project, owner)
        assert not unconfigured
        assert [row['figure_id'] for row in frozen] == [earlier, second['id']]
        assert frozen[1]['chapter_label'] == '改名后的小节'

        same_chapter = [revised, dict(legacy, chapter_id='introduction')]
        # A request using the previous client contract can still send a version ID.
        response = customer.put(resource, json=dict(expected_revision=template['revision'],
            placements=[dict(revised, figure_id=second['id']), same_chapter[1]]))
        assert response.status_code == 200, response.text
        assert response.json()['placements'] == same_chapter
        assert [row['figure_id'] for row in resolved_placements(project, owner)[0]] == [second['id'], earlier]

        with database_connection(write=True) as db:
            db.execute('''UPDATE storage_objects SET state='missing' WHERE id=(
                SELECT storage_object_id FROM research_figure_members WHERE id=%s)''', (frozen[1]['member_id'],))
        stale = customer.get(resource).json()
        assert stale['placements'] == same_chapter
        assert {figure['id'] for figure in stale['figures']} == {earlier}
        valid, unconfigured = resolved_placements(project, owner)
        assert unconfigured and [row['figure_id'] for row in valid] == [earlier]

        cancelled = customer.post(figures + '/' + first['root_id'] + '/cancel', json={'expected_revision': second['revision']})
        assert cancelled.status_code == 204, cancelled.text
        current = customer.get(resource).json()
        assert current['revision'] == stale['revision'] + 1 and current['placements'] == [same_chapter[1]]
        assert [item['id'] for item in current['figures']] == [earlier]
        valid, unconfigured = resolved_placements(project, owner)
        assert not unconfigured and [row['figure_id'] for row in valid] == [earlier]
