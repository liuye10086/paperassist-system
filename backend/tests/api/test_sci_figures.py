from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.adapters.research_figure_render import render_figure
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.research_results.figures import ResearchFigureService
from app.domain.research_results.execution import retry_in_transaction, run_research_figure_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_project_types import create, project_body, project_path
from tests.api.test_customer_sci_workflow import sci_project
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_file_batches import register
from tests.helpers.ocr_samples import ocr_result


def upload_image(client, project, filename, image_format, color='red', *, second_page=False):
    content = BytesIO()
    options = {'save_all': True, 'append_images': [Image.new('RGB', (30, 90), 'yellow')]} if second_page else {}
    Image.new('RGB', (90, 60), color).save(content, image_format, **options)
    raw = content.getvalue()
    path, batch, item, _ = register(client, {'id': project.rsplit('/', 1)[-1]}, raw, filename, filename)
    response = client.post(f"{path}/{batch['id']}/items/{item['client_id']}", files={'file': (filename, raw)})
    assert response.status_code == 202, response.text
    saved = response.json()
    if parse := saved.get('task'):
        result = run_parse_file_task(parse['id'], parse['revision'], parser=ocr_result)
        assert result is not None and result['status'] == 'succeeded', result
    return saved['file_id'], raw


def compose(client, path, body, key):
    return client.post(path, json=body, headers={'Idempotency-Key': key})


def assembly(client, path, **params):
    response = client.get(path + '/assembly', params=params)
    assert response.status_code == 200, response.text
    return response.json()


def figure_project(client, kind, key):
    if kind == 'sci':
        return sci_project(client, key=key)
    return project_path(create(client, key, **project_body(kind)))


@pytest.mark.parametrize(('kind', 'columns'), (('sci', 2), ('thesis', 3)))
def test_customer_figure_renders_ten_originals(tmp_path, kind, columns):
    with TestClient(app) as owner:
        sign_in(owner, 'ten-figure-owner@example.test', 'customer')
        project = figure_project(owner, kind, 'ten-figure-project')
        path = project + f'/{kind}-figures'
        originals = [upload_image(owner, project, f'panel-{number}.png', 'PNG', (number, 30, 80))[0]
                     for number in range(1, 11)]
        body = dict(title='Ten-panel figure', file_ids=originals, columns=columns)
        rejected = compose(owner, path, dict(body, file_ids=[*originals, 'extra-file']), 'too-many-panels')
        assert rejected.status_code == 422, rejected.text

        response = compose(owner, path, body, 'compose-ten-panels')
        assert response.status_code == 201, response.text
        figure = response.json()
        assert [panel['source']['source_id'] for panel in figure['config']['panels']] == originals
        result = run_research_figure_task(figure['task_id'], figure['task']['revision'], engine=render_figure,
                                          staging_directory=tmp_path / 'staging')
        assert result is not None and result['status'] == 'succeeded', result

        saved = owner.get(path + '/' + figure['id'])
        assert saved.status_code == 200, saved.text
        saved_figure = saved.json()
        manifest = saved_figure['manifest']
        assert [panel['label'] for panel in manifest['panels']] == list('ABCDEFGHIJ')
        preview = next(member for member in saved_figure['members'] if member['key'] == 'figure_png')
        download = owner.get(preview['download_url'])
        assert download.status_code == 200, download.text
        with Image.open(BytesIO(download.content)) as rendered:
            assert rendered.format == 'PNG'
            assert rendered.size == (manifest['width_pixels'], manifest['height_pixels'])


@pytest.mark.parametrize('kind', ('sci', 'thesis'))
def test_customer_figure_composes_png_jpeg_and_tiff_before_independent_revision(tmp_path, kind):
    with TestClient(app) as owner:
        user_id = sign_in(owner, 'sci-figure-owner@example.test', 'customer')
        project = figure_project(owner, kind, 'first-paper-project')
        project_id = project.rsplit('/', 1)[-1]
        path = project + f'/{kind}-figures'
        response = owner.get(path)
        assert response.status_code == 200, response.text
        assert response.json() == dict(items=[], total=0, page=1, page_size=20)

        tiff, tiff_bytes = upload_image(owner, project, 'first.tiff', 'TIFF', 'blue', second_page=True)
        png, png_bytes = upload_image(owner, project, 'second.png', 'PNG', 'red')
        jpeg, jpeg_bytes = upload_image(owner, project, 'third.jpg', 'JPEG', 'green')
        body = dict(title='组织切片组合图', file_ids=[tiff, png, jpeg], columns=2)
        keys = ['compose', 'compose-in-another-tab']
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda key: compose(owner, path, body, key), keys))
        assert sorted(response.status_code for response in responses) == [201, 409]
        created = next(response for response in responses if response.status_code == 201)
        key = keys[responses.index(created)]
        rejected = next(response for response in responses if response.status_code == 409)
        assert rejected.json()['detail']['code'] == 'paper_figure_original_in_use'
        first = created.json()
        assert first['id'] == first['root_id'] and first['revision'] == 1 and first['members'] == []
        assert first['task']['status'] == 'queued'
        cancel_url = path + '/' + first['root_id'] + '/cancel'
        pending_cancel = owner.post(cancel_url, json={'expected_revision': 1})
        assert pending_cancel.status_code == 409, pending_cancel.text
        assert [p['label'] for p in first['config']['panels']] == ['A', 'B', 'C']
        assert [p['source']['source_id'] for p in first['config']['panels']] == body['file_ids']
        unused = assembly(owner, path)
        assert unused['available']['total'] == 0
        assert unused['has_pending']
        pending_group, = unused['groups']['items']
        assert pending_group['current'] is None
        assert [row['id'] for row in pending_group['pending_originals']] == body['file_ids']
        replayed = compose(owner, path, body, key)
        assert replayed.status_code == 200 and replayed.json() == first
        assert compose(owner, path, dict(body, columns=3), key).status_code == 409

        result = run_research_figure_task(first['task_id'], 1, engine=render_figure, staging_directory=tmp_path / 'staging')
        assert result is not None and result['status'] == 'succeeded', result
        response = owner.get(path + '/' + first['id'])
        assert response.status_code == 200, response.text
        fixed = response.json()
        assert [panel['label'] for panel in fixed['manifest']['panels']] == ['A', 'B', 'C']
        assert fixed['manifest']['panels'][0]['original_pixels'] == [90, 60]
        assert all(member['download_url'].startswith(f"{path}/{first['id']}/members/") for member in fixed['members'])
        members = {member['key']: member for member in fixed['members']}
        for index, (fmt, raw) in enumerate((('tiff', tiff_bytes), ('png', png_bytes), ('jpeg', jpeg_bytes)), 1):
            member = members[f'original_{index}']
            assert member['format'] == fmt and member['role'] == 'original_panel'
            saved = owner.get(member['download_url'])
            assert saved.status_code == 200 and saved.content == raw
            assert saved.headers['content-type'] == f'image/{fmt}'
        formal = members['figure_png']
        preview = owner.get(formal['download_url'])
        assert preview.status_code == 200 and preview.headers['content-type'] == 'image/png'
        with Image.open(BytesIO(preview.content)) as image:
            x, y, width, height = fixed['manifest']['panels'][0]['box']
            assert image.getpixel((x + width // 2, y + height // 2)) == (0, 0, 255)
        rebuild = owner.get(members['rebuild_config']['download_url']).json()
        assert [panel['path'] for panel in rebuild['panels']] == ['original_1.tiff', 'original_2.png', 'original_3.jpeg']
        store = ProjectStore(get_data_dir(), owner_id=user_id)
        _, internal = ResearchFigureService(store).member(project_id, first['id'], formal['id'])
        assert internal == preview.content

        revision = dict(body, file_ids=[png], columns=1, root_id=first['root_id'], expected_revision=1)
        response = compose(owner, path, revision, 'revise')
        assert response.status_code == 201, response.text
        second = response.json()
        assert second['revision'] == 2 and second['root_id'] == first['root_id'] and second['parent_id'] == first['id']
        assert second['config']['panels'][0]['label'] == ''
        assert compose(owner, path, revision, 'revise').json() == second
        conflict = compose(owner, path, revision, 'stale')
        assert conflict.status_code == 409 and conflict.json()['detail']['code'] == 'research_revision_conflict'
        generating = assembly(owner, path)
        assert generating['available']['total'] == 0
        current, = generating['groups']['items']
        assert current['current']['revision'] == 1 and current['latest_revision'] == 2
        assert [row['id'] for row in current['current']['originals']] == body['file_ids']
        loading = owner.get(path).json()
        assert loading['total'] == 1 and [item['id'] for item in loading['items']] == [second['id']]
        assert owner.post(cancel_url, json={'expected_revision': 2}).status_code == 409
        assert compose(owner, path, dict(body, file_ids=[tiff], columns=1), 'too-early').status_code == 409
        result = run_research_figure_task(second['task_id'], 1, engine=render_figure, staging_directory=tmp_path / 'staging')
        assert result is not None and result['status'] == 'succeeded', result
        finished = assembly(owner, path, page_size=1)
        assert not finished['has_pending'] and finished['available']['total'] == 2
        current, = finished['groups']['items']
        assert current['pending_originals'] == []
        assert current['current']['originals'] == [dict(id=png, filename='second.png', file_type='png')]
        page2 = assembly(owner, path, page=2, page_size=1)
        assert {row['id'] for data in (finished, page2) for row in data['available']['items']} == {tiff, jpeg}
        assert owner.get(path + '/' + first['id']).json() == fixed
        assert owner.get(formal['download_url']).content == preview.content
        pages = [owner.get(path, params={'page': page, 'page_size': 1}).json() for page in (1, 2)]
        assert [[item['id'] for item in page['items']] for page in pages] == [[second['id']], []]
        assert all(page['total'] == 1 and page['page_size'] == 1 for page in pages)
        assert pages[0]['items'][0]['latest_revision'] == 2
        assert owner.post(cancel_url, json={'expected_revision': 1}).status_code == 409
        for _ in range(2):
            cancelled = owner.post(cancel_url, json={'expected_revision': 2})
            assert cancelled.status_code == 204 and not cancelled.content, cancelled.text
        state = assembly(owner, path)
        assert {row['id'] for row in state['available']['items']} == {tiff, png, jpeg}
        assert state['groups']['total'] == 0 and owner.get(path).json()['total'] == 0
        assert owner.get(formal['download_url']).content == preview.content
        stale = compose(owner, path, dict(revision, expected_revision=2), 'cancelled-revision')
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'paper_figure_assembly_cancelled'
        recomposed = compose(owner, path, body, 'recompose-released')
        assert recomposed.status_code == 201 and recomposed.json()['root_id'] != first['root_id'], recomposed.text


def test_failed_revision_releases_only_its_new_originals(tmp_path):
    def timeout(*_):
        raise StorageError('research_render_timeout', '合成渲染超时', 409)

    staging = tmp_path / 'staging'
    with TestClient(app) as owner:
        owner_id = sign_in(owner, 'paper-figure-failure@example.test', 'customer')
        project = figure_project(owner, 'sci', 'paper')
        path = project + '/sci-figures'
        first, _ = upload_image(owner, project, 'first.png', 'PNG')
        replacement, _ = upload_image(owner, project, 'replacement.png', 'PNG', 'blue')
        body = dict(title='固定正图', file_ids=[first], columns=1)
        created = compose(owner, path, body, 'first')
        assert created.status_code == 201, created.text
        ready = created.json()
        result = run_research_figure_task(ready['task_id'], 1, engine=render_figure, staging_directory=staging)
        assert result is not None and result['status'] == 'succeeded', result

        updated = compose(owner, path, dict(body, file_ids=[replacement], root_id=ready['root_id'], expected_revision=1), 'update')
        assert updated.status_code == 201, updated.text
        state = assembly(owner, path)
        entry, = state['groups']['items']
        assert entry['current']['originals'][0]['id'] == first and entry['pending_originals'][0]['id'] == replacement
        assert state['available']['total'] == 0
        task_id = updated.json()['task_id']
        result = run_research_figure_task(task_id, 1, engine=timeout, staging_directory=staging)
        assert result is not None and result['status'] == 'failed', result
        state = assembly(owner, path)
        entry, = state['groups']['items']
        assert entry['current']['revision'] == 1 and entry['latest_revision'] == 2 and not state['has_pending']
        assert [row['id'] for row in state['available']['items']] == [replacement]
        current, = owner.get(path).json()['items']
        assert current['id'] == ready['id'] and current['latest_revision'] == 2
        assert current['task']['status'] == 'succeeded'
        new = compose(owner, path, dict(body, title='另一张正图', file_ids=[replacement]), 'other')
        assert new.status_code == 201, new.text

        store = ResearchFigureService(ProjectStore(get_data_dir(), owner_id=owner_id)).store
        with pytest.raises(StorageError) as conflict, store.connection(write=True) as db:
            failed = store.require_task(db, task_id)
            retry_in_transaction(store, db, failed, failed['revision'])
        assert conflict.value.code == 'paper_figure_original_in_use'
        edit = compose(owner, path, dict(body, title='继续编辑', root_id=ready['root_id'], expected_revision=entry['latest_revision']), 'edit-ready')
        assert edit.status_code == 201 and edit.json()['revision'] == 3, edit.text


@pytest.mark.parametrize('kind, other_kind', (('sci', 'thesis'), ('thesis', 'sci')))
def test_customer_figure_requires_customer_owner_project_and_original_images(kind, other_kind):
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as analyst, TestClient(app) as admin:
        owner_id = sign_in(owner, 'sci-figure-scope@example.test', 'customer')
        hidden_actor = sign_in(other, 'sci-figure-foreign@example.test', 'customer')
        sign_in(analyst, 'sci-figure-analyst@example.test', 'analyst')
        sign_in(admin, 'sci-figure-admin@example.test', 'admin')
        project = figure_project(owner, kind, 'first-paper-project')
        another = figure_project(owner, kind, 'second-paper-project')
        research = create_customer_project(owner)
        other_paper = figure_project(owner, other_kind, 'other-paper-project')
        visible, _ = upload_image(owner, project, 'visible.png', 'PNG')
        hidden, _ = upload_image(owner, project, 'hidden.png', 'PNG')
        foreign, _ = upload_image(owner, another, 'foreign.png', 'PNG')
        from tests.api.test_excel import workbook_bytes
        sheet = owner.post(project + '/files', files={'file': ('table.xlsx', workbook_bytes())})
        assert sheet.status_code == 201, sheet.text
        with database_connection(write=True) as db:
            db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (hidden_actor, hidden))

        route = f'/{kind}-figures'
        path = project + route
        body = dict(title='拼版', file_ids=[visible], columns=1)
        assert owner.get(project + '/research-figures').status_code == 403
        assert compose(owner, project + '/research-figures', body, 'blocked').status_code == 403
        assert other.get(path).status_code == 404
        assert other.get(path + '/assembly').status_code == 404
        assert assembly(owner, path)['available']['items'] == [dict(id=visible, filename='visible.png', file_type='png')]
        for client in (analyst, admin):
            assert client.get(path).status_code == 403
            assert client.get(path + '/assembly').status_code == 403
            assert compose(client, path, body, 'blocked').status_code == 403
        for wrong_project in (research, other_paper):
            assert owner.get(wrong_project + route).status_code == 403
            assert owner.get(wrong_project + route + '/assembly').status_code == 403
            assert compose(owner, wrong_project + route, body, 'blocked').status_code == 403

        for file_id in (hidden, foreign):
            assert compose(owner, path, dict(body, file_ids=[file_id]), 'inaccessible').status_code == 404
        assert compose(owner, path, dict(body, file_ids=[sheet.json()['file']['id']]), 'spreadsheet').status_code == 422
        for invalid_body in (dict(body, file_ids=[]), dict(body, file_ids=[visible] * 7),
                             dict(body, file_ids=[visible, visible]), dict(body, columns=4),
                             dict(body, title=' '), dict(body, expected_revision=1)):
            assert compose(owner, path, invalid_body, 'invalid').status_code == 422

        store = ProjectStore(get_data_dir(), owner_id=owner_id)
        project_id = project.rsplit('/', 1)[-1]
        legacy, _ = ResearchFigureService(store).create(project_id, {
            'mode': 'reuse', 'panels': [{'source': {'source_kind': 'original_file', 'source_id': visible}}],
        }, 'same-key')
        accepted = compose(owner, path, body, 'same-key')
        assert accepted.status_code == 201, accepted.text
        version = accepted.json()
        assert owner.get(path + '/' + legacy['id']).status_code == 404
        assert owner.get(path + f"/{legacy['id']}/members/anything/download").status_code == 404
        assert compose(owner, path, dict(body, root_id=legacy['root_id'], expected_revision=1), 'legacy').status_code == 404
        assert other.get(path + '/' + version['id']).status_code == 404
        assert owner.get(another + route + '/' + version['id']).status_code == 404
        cancel_suffix = f"/{version['root_id']}/cancel"
        assert other.post(path + cancel_suffix, json={'expected_revision': 1}).status_code == 404
        assert owner.post(another + route + cancel_suffix, json={'expected_revision': 1}).status_code == 404
        assert analyst.post(path + cancel_suffix, json={'expected_revision': 1}).status_code == 403
        assert [item['id'] for item in owner.get(path).json()['items']] == [version['id']]
        assert ResearchFigureService(store, entrypoint=f'{other_kind}_figures').list(project_id)['items'] == []
        with pytest.raises(StorageError) as rejected:
            ResearchFigureService(store, entrypoint=f'{other_kind}_figures').get(project_id, version['id'])
        assert rejected.value.status == 404
