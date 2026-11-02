"""New presentation/export bindings only; old writing/scientific suites are reused."""
from io import BytesIO
from docx import Document

from tests.api.test_analysis import client
from tests.api.test_manuscripts import setup, body
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task


def test_bilingual_export_is_frozen_idempotent_downloadable_and_blind_is_distinct(client):
    path, _, _ = setup(client)
    versions = []
    for lang, text in [('zh-CN', '合成观察值 5 mg；单供体，不代表独立验证。'),
                       ('en', 'Synthetic observation 5 mg; single donor, not independent validation.')]:
        root = post(client, path, body(output_language=lang, methods={'study_design': text}), lang).json()
        version = root['versions'][0]
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        versions.append((root, version))
    (root, base), (_, peer) = versions
    endpoint = path+'/'+root['id']
    request = dict(base_version_id=base['id'], peer_version_id=peer['id'], config=dict(
        paragraph_groups=[dict(id='design', zh_ids=['methods:study_design'], en_ids=['methods:study_design'])],
        authors=[dict(name='合成作者甲', order=1, source='工程样例')], blind=dict(identity_terms=['合成作者甲'])))
    saved = post(client, endpoint+'/presentations', request, 'configuration')
    assert saved.status_code == 201, saved.text
    export_body = dict(presentation_version_id=saved.json()['id'], language_view='zh-CN-en', review_mode='identified')
    exports = endpoint+'/versions/1/exports'
    preview = post(client, exports+'/preview', export_body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['presentation']['binding']['peer_version_id'] == peer['id']
    created = post(client, exports, export_body, 'one-output')
    assert created.status_code == 201, created.text
    assert post(client, exports, export_body, 'one-output').status_code == 200
    assert post(client, exports, dict(export_body, review_mode='blind'), 'one-output').status_code == 409
    assert run_task(created.json()['task_id'], 1)['status'] == 'succeeded'
    done = client.get(endpoint+'/exports/'+created.json()['id']).json()
    assert done['presentation']['binding'] == preview.json()['presentation']['binding']
    assert done['presentation']['quality']['scientific_semantic'] == 'pending'
    response = client.get(done['download_url']); assert response.status_code == 200
    text = '\n'.join(p.text for p in Document(BytesIO(response.content)).paragraphs)
    assert '单供体' in text and 'single donor' in text and '合成作者甲' in text
    blind = post(client, exports, dict(export_body, review_mode='blind'), 'blind-output').json()
    assert run_task(blind['task_id'], 1)['status'] == 'succeeded'
    view = client.get(endpoint+'/exports/'+blind['id']).json()
    blind_bytes = client.get(view['download_url']).content
    assert view['sha256'] != done['sha256']
    assert view['presentation']['blind']['known_identity_check'] == 'passed'
    assert '合成作者甲' not in '\n'.join(p.text for p in Document(BytesIO(blind_bytes)).paragraphs)
    assert client.get(done['download_url']).content == response.content


def test_school_export_reuses_fixed_options_and_keeps_old_empty_contract(client):
    from tests.api.test_school_exports import published
    path, endpoint, _, root = published(client)
    version = root['versions'][0]
    saved = post(client, endpoint+'/presentations', dict(base_version_id=version['id'], config=dict(
        school=dict(options=dict(include_toc=False, manual_fields=dict(author='合成作者乙'))),
        blind=dict(identity_terms=['合成作者乙']))), 'school-config')
    assert saved.status_code == 201, saved.text
    request = dict(presentation_version_id=saved.json()['id'], language_view='zh-CN', review_mode='blind')
    created = post(client, endpoint+'/versions/1/exports', request, 'school-blind')
    assert created.status_code == 201, created.text
    assert run_task(created.json()['task_id'], 1)['status'] == 'succeeded'
    result = client.get(endpoint+'/exports/'+created.json()['id']).json()
    assert result['school']['field_update']['status'] == 'not_requested'
    assert result['presentation']['blind']['known_identity_check'] == 'passed'
    assert client.get(result['download_url']).status_code == 200
    assert post(client, endpoint+'/versions/1/exports', dict(request, school=dict(manual_fields=dict(author='changed'))), 'different').status_code == 422
    assert post(client, endpoint+'/versions/1/exports', dict(review_mode='blind'), 'missing-config').status_code == 422
