"""New presentation/export bindings only; old writing/scientific suites are reused."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from docx import Document
from psycopg.types.json import Jsonb

from tests.api.test_analysis import client
from tests.api.test_manuscripts import setup, body
from tests.api.test_literature_evidence import post
from app.db.database import database_connection
from app.domain.literature.service import digest
from app.domain.tasks.execution import run_task

REMOVED = '盲审已移出产品范围，请交第三方处理。'
HISTORICAL_BLIND = dict(identity_terms=['合成作者甲'], hidden_chapter_ids=[], exceptions=[], manual_image_review=True)


def removed(response):
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'blind_review_removed'
    assert response.json()['detail']['message'] == REMOVED


def bilingual(client):
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
    config = dict(paragraph_groups=[dict(id='design', zh_ids=['methods:study_design'], en_ids=['methods:study_design'])],
                  authors=[dict(name='合成作者甲', order=1, source='工程样例')])
    return endpoint, base, peer, dict(base_version_id=base['id'], peer_version_id=peer['id'], config=config)


def historical_presentation(saved_id):
    """Append a row shaped like a pre-removal configuration with real blind rules."""
    with database_connection(write=True) as db:
        row = dict(db.execute('SELECT * FROM manuscript_presentation_versions WHERE id=%s', (saved_id,)).fetchone())
        latest = db.execute('SELECT max(revision) AS revision FROM manuscript_presentation_versions WHERE manuscript_id=%s',
                            (row['manuscript_id'],)).fetchone()['revision']
        request, snapshot = deepcopy(row['request_json']), deepcopy(row['snapshot_json'])
        request['config']['blind'] = deepcopy(HISTORICAL_BLIND)
        snapshot['config'] = deepcopy(request['config'])
        snapshot['checks'] += [dict(code='blind:images', status='passed', message='图片、扫描签名及嵌入对象须人工检查。'),
                               dict(code='blind:rules', status='passed', message='盲审须明确身份词和例外；自动扫描不能保证匿名。')]
        identity = str(uuid4())
        db.execute('''INSERT INTO manuscript_presentation_versions(id,manuscript_id,project_id,user_id,revision,base_version_id,peer_version_id,
            idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (identity, row['manuscript_id'], row['project_id'], row['user_id'], latest+1, row['base_version_id'], row['peer_version_id'],
             'historical-'+identity, Jsonb(request), digest(request), Jsonb(snapshot), digest(snapshot), row['created_at']))
    return identity


def historical_blind_export(export_id, *, status=None):
    """Rewrite one fresh fixture into the stored shape of a pre-removal blind export."""
    with database_connection(write=True) as db:
        export = db.execute('SELECT * FROM manuscript_exports WHERE id=%s', (export_id,)).fetchone()
        task = db.execute('SELECT * FROM tasks WHERE id=%s', (export['task_id'],)).fetchone()
        snapshot = deepcopy(task['input_snapshot'])
        snapshot['presentation']['binding']['review_mode'] = 'blind'
        db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s', (Jsonb(snapshot), digest(snapshot), task['id']))
        if status is not None:
            db.execute("UPDATE tasks SET status=%s,error_code='storage_unavailable' WHERE id=%s", (status, task['id']))
        metadata = deepcopy(export['metadata_json'])
        if metadata:
            metadata['presentation']['binding']['review_mode'] = 'blind'
            metadata['presentation']['blind'] = dict(known_identity_check='passed', remaining=[], images='not_present',
                                                     exceptions=[], anonymity_verified=False)
            metadata['presentation']['blind_rules'] = deepcopy(HISTORICAL_BLIND)
            metadata['filename'] = 'Blind-' + metadata['filename'].removeprefix('Manuscript-')
            db.execute('UPDATE manuscript_exports SET metadata_json=%s WHERE id=%s', (Jsonb(metadata), export_id))
        return task['id'], metadata


def test_bilingual_export_is_frozen_idempotent_downloadable_and_blind_is_removed(client):
    endpoint, base, peer, request = bilingual(client)
    saved = post(client, endpoint+'/presentations', request, 'configuration')
    assert saved.status_code == 201, saved.text
    assert 'blind' not in saved.json()['config']
    assert not any(c['code'].startswith('blind:') for c in saved.json()['checks'])
    with database_connection() as db:
        stored = db.execute('SELECT request_json,snapshot_json FROM manuscript_presentation_versions WHERE id=%s', (saved.json()['id'],)).fetchone()
    assert 'blind' not in stored['request_json']['config'] and 'blind' not in stored['snapshot_json']['config']
    export_body = dict(presentation_version_id=saved.json()['id'], language_view='zh-CN-en')
    exports = endpoint+'/versions/1/exports'
    preview = post(client, exports+'/preview', export_body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['presentation']['binding']['peer_version_id'] == peer['id']
    assert preview.json()['presentation']['binding']['review_mode'] == 'identified'
    assert 'blind_rules' not in preview.json()['presentation']
    created = post(client, exports, export_body, 'one-output')
    assert created.status_code == 201, created.text
    assert post(client, exports, export_body, 'one-output').status_code == 200
    removed(post(client, exports, dict(export_body, review_mode='blind'), 'one-output'))
    removed(post(client, exports+'/preview', dict(export_body, review_mode='blind')))
    removed(post(client, exports, dict(export_body, review_mode='blind'), 'blind-output'))
    assert run_task(created.json()['task_id'], 1)['status'] == 'succeeded'
    done = client.get(endpoint+'/exports/'+created.json()['id']).json()
    assert done['presentation']['binding'] == preview.json()['presentation']['binding']
    assert done['presentation']['quality']['scientific_semantic'] == 'pending'
    assert 'blind' not in done['presentation'] and done['filename'].startswith('Manuscript-zh-CN-en-v1-')
    response = client.get(done['download_url']); assert response.status_code == 200
    text = '\n'.join(p.text for p in Document(BytesIO(response.content)).paragraphs)
    assert '单供体' in text and 'single donor' in text and '合成作者甲' in text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscript_exports WHERE version_id=%s', (base['id'],)).fetchone()['n'] == 1


def test_school_export_reuses_fixed_options_and_keeps_old_empty_contract(client):
    from tests.api.test_school_exports import published
    path, endpoint, _, root = published(client)
    version = root['versions'][0]
    saved = post(client, endpoint+'/presentations', dict(base_version_id=version['id'], config=dict(
        school=dict(options=dict(include_toc=False, manual_fields=dict(author='合成作者乙', department='合成院系'))),
        authors=[dict(name='署名作者丙', order=1, source='工程样例')])), 'school-config')
    assert saved.status_code == 201, saved.text
    request = dict(presentation_version_id=saved.json()['id'], language_view='zh-CN')
    removed(post(client, endpoint+'/versions/1/exports', dict(request, review_mode='blind'), 'school-blind'))
    created = post(client, endpoint+'/versions/1/exports', request, 'school-signed')
    assert created.status_code == 201, created.text
    assert run_task(created.json()['task_id'], 1)['status'] == 'succeeded'
    result = client.get(endpoint+'/exports/'+created.json()['id']).json()
    assert result['school']['field_update']['status'] == 'not_requested'
    assert result['presentation']['binding']['review_mode'] == 'identified'
    downloaded = client.get(result['download_url'])
    assert downloaded.status_code == 200
    text = '\n'.join(paragraph.text for paragraph in Document(BytesIO(downloaded.content)).paragraphs)
    assert '合成作者乙' in text and '署名作者丙' in text and '合成院系' in text
    assert '[已隐去]' not in text
    assert post(client, endpoint+'/versions/1/exports', dict(request, school=dict(manual_fields=dict(author='changed'))), 'different').status_code == 422
    removed(post(client, endpoint+'/versions/1/exports', dict(review_mode='blind'), 'missing-config'))


def test_new_presentation_rejects_blind_rules_and_blind_language_review(client):
    endpoint, _, _, request = bilingual(client)
    for index, blind in enumerate((dict(identity_terms=['合成作者甲']), dict(hidden_chapter_ids=['methods']), dict(manual_image_review=True))):
        changed = dict(request, config=dict(request['config'], blind=blind))
        removed(post(client, endpoint+'/presentations/preview', changed))
        removed(post(client, endpoint+'/presentations', changed, 'blind-'+str(index)))
    empty = post(client, endpoint+'/presentations', dict(request, config=dict(request['config'], blind=dict(identity_terms=[]))), 'empty-blind')
    assert empty.status_code == 201, empty.text
    assert 'blind' not in empty.json()['config']
    review = dict(source_export_id='unused', source_sha256='a'*64, language_view='zh-CN-en', review_mode='blind',
                  decisions=[dict(location='word/document.xml:paragraph:0', content_sha256='b'*64, decision='target_language', reason='合成', exceptions=[])])
    removed(post(client, endpoint+'/presentations/preview', dict(request, config=dict(request['config'], language_review=review))))


def test_historical_blind_configuration_and_export_remain_listed_detailed_and_downloadable(client):
    endpoint, _, _, request = bilingual(client)
    saved = post(client, endpoint+'/presentations', request, 'configuration').json()
    historical = historical_presentation(saved['id'])
    listed = client.get(endpoint+'/presentations')
    assert listed.status_code == 200, listed.text
    item = next(i for i in listed.json()['items'] if i['id'] == historical)
    assert item['config']['blind'] == HISTORICAL_BLIND
    assert {'blind:images', 'blind:rules'} <= {c['code'] for c in item['checks']}
    assert client.get(endpoint+'/presentations/'+historical).json()['config']['blind'] == HISTORICAL_BLIND
    exported = post(client, endpoint+'/versions/1/exports', dict(presentation_version_id=historical, language_view='zh-CN'), 'historical')
    assert exported.status_code == 201, exported.text
    assert run_task(exported.json()['task_id'], 1)['status'] == 'succeeded'
    signed = client.get(endpoint+'/exports/'+exported.json()['id']).json()
    raw = client.get(signed['download_url']).content
    _, metadata = historical_blind_export(exported.json()['id'])
    listing = client.get(endpoint+'/versions/1/exports')
    assert listing.status_code == 200, listing.text
    view = next(i for i in listing.json()['items'] if i['id'] == exported.json()['id'])
    assert view['presentation']['binding']['review_mode'] == 'blind'
    assert view['filename'] == metadata['filename'] and view['filename'].startswith('Blind-zh-CN-v1-')
    assert client.get(endpoint+'/exports/'+view['id']).json()['presentation']['blind_rules'] == HISTORICAL_BLIND
    downloaded = client.get(view['download_url'])
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == raw and sha256(downloaded.content).hexdigest() == view['sha256']


def test_failed_historical_blind_export_retry_is_rejected_without_new_output(client):
    endpoint, _, _, request = bilingual(client)
    saved = post(client, endpoint+'/presentations', request, 'configuration').json()
    exported = post(client, endpoint+'/versions/1/exports', dict(presentation_version_id=saved['id'], language_view='zh-CN'), 'failed-blind')
    assert exported.status_code == 201, exported.text
    task_id, _ = historical_blind_export(exported.json()['id'], status='failed')
    task = client.get('/api/v1/tasks/'+task_id).json()
    removed(client.post('/api/v1/tasks/'+task_id+'/retry', json={'expected_revision': task['revision']}))
    recovered = client.post(endpoint+'/recover', json={})
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()['requeued'] == 0
    assert recovered.json()['skipped'] == [dict(task_id=task_id, error_code='blind_review_removed')]
    with database_connection() as db:
        row = db.execute('SELECT t.status,e.metadata_json FROM manuscript_exports e JOIN tasks t ON t.id=e.task_id WHERE e.id=%s',
                         (exported.json()['id'],)).fetchone()
    assert row['status'] == 'failed' and row['metadata_json'] is None


def test_queued_historical_blind_export_fails_closed_in_the_worker(client):
    endpoint, _, _, request = bilingual(client)
    saved = post(client, endpoint+'/presentations', request, 'configuration').json()
    exported = post(client, endpoint+'/versions/1/exports', dict(presentation_version_id=saved['id'], language_view='zh-CN'), 'queued-blind')
    task_id, _ = historical_blind_export(exported.json()['id'])
    result = run_task(task_id, 1)
    assert result['status'] == 'failed' and result['error_code'] == 'blind_review_removed'
    with database_connection() as db:
        assert db.execute('SELECT metadata_json FROM manuscript_exports WHERE id=%s', (exported.json()['id'],)).fetchone()['metadata_json'] is None


def test_historical_blind_export_cannot_be_a_language_review_source(client):
    endpoint, _, _, request = bilingual(client)
    saved = post(client, endpoint+'/presentations', request, 'configuration').json()
    exported = post(client, endpoint+'/versions/1/exports', dict(presentation_version_id=saved['id'], language_view='zh-CN'), 'review-source')
    assert run_task(exported.json()['task_id'], 1)['status'] == 'succeeded'
    _, metadata = historical_blind_export(exported.json()['id'])
    decisions = [dict(location=i['location'], content_sha256=i['content_sha256'], decision='target_language', reason='合成确认', exceptions=[])
                 for i in metadata['presentation']['language_inventory']]
    review = dict(source_export_id=exported.json()['id'], source_sha256=metadata['sha256'], language_view='zh-CN', decisions=decisions)
    identified = post(client, endpoint+'/presentations/preview', dict(request, config=dict(request['config'], language_review=dict(review, review_mode='identified'))))
    assert identified.status_code == 409 and identified.json()['detail']['code'] == 'task_source_conflict', identified.text
    removed(post(client, endpoint+'/presentations/preview', dict(request, config=dict(request['config'], language_review=dict(review, review_mode='blind')))))


def test_historical_blind_export_cannot_be_a_new_layout_source_but_stays_downloadable(client):
    endpoint, _, _, request = bilingual(client)
    saved = post(client, endpoint+'/presentations', request, 'configuration').json()
    exported = post(client, endpoint+'/versions/1/exports', dict(presentation_version_id=saved['id'], language_view='zh-CN'), 'layout-source')
    assert run_task(exported.json()['task_id'], 1)['status'] == 'succeeded'
    _, metadata = historical_blind_export(exported.json()['id'])
    layouts = endpoint.split('/manuscripts/')[0]+'/layout-exports'
    removed(client.get(layouts+'/sources/manuscript_export/'+exported.json()['id']+'/catalog'))
    removed(post(client, layouts, dict(source_kind='manuscript_export', source_id=exported.json()['id'],
                                       request_key='blind-layout', layout={'source_sha256': metadata['sha256']})))
    sources = client.get(layouts+'/sources')
    assert sources.status_code == 200, sources.text
    assert exported.json()['id'] not in {item['source_id'] for item in sources.json()['items']}
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM layout_exports WHERE manuscript_export_id=%s', (exported.json()['id'],)).fetchone()['n'] == 0
    # Historical blind exports stay listed and downloadable.
    view = next(i for i in client.get(endpoint+'/versions/1/exports').json()['items'] if i['id'] == exported.json()['id'])
    assert view['presentation']['binding']['review_mode'] == 'blind'
    downloaded = client.get(view['download_url'])
    assert downloaded.status_code == 200 and sha256(downloaded.content).hexdigest() == view['sha256']
