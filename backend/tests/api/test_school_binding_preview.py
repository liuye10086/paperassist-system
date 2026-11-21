"""D6 read-only preview before changing the bound school template."""
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_school_templates import post, analysis, parsed
from tests.api.test_thesis_manuscripts import bound
from app.db.database import database_connection
from app.domain.tasks.execution import run_task

FIXTURE = Path(__file__).parents[1] / 'fixtures' / 'school_confirmation_snapshot.json'
CHAPTERS = [dict(id='school-intro', title='绪论', level=1), dict(id='school-methods', title='研究方法', level=1),
            dict(id='school-results', title='结果', level=1)]


def counts(project_id):
    with database_connection() as db:
        confirmations = db.execute('SELECT count(*) AS n FROM school_template_confirmations WHERE project_id=%s', (project_id,)).fetchone()['n']
        profile = db.execute('SELECT revision,bound_confirmation_id FROM thesis_profiles WHERE project_id=%s', (project_id,)).fetchone()
    return confirmations, dict(profile) if profile else None


def second_template(client, path, template, *, size=16):
    """Parse a later template version that adds a level-1 heading size (no note conflicts with it)."""
    from app.domain.school_templates.execution import run_school_template_task
    def changed(*args):
        result = analysis(*args)
        source = result['rules'][0]['source']
        result['rules'].append(dict(id='heading1.font_size_pt', category='heading1', label='字号', value=size, source=source))
        return result
    old = client.get(path+'/school-templates').json()['items'][0]
    response = post(client, path+'/school-templates', template | dict(name='工程更新', previous_version_id=old['id']), 'update')
    assert response.status_code == 202, response.text
    assert run_school_template_task(response.json()['task']['id'], 1, parser=changed)['status'] == 'succeeded'
    return next(i for i in client.get(path+'/school-templates').json()['items'] if i['id'] == response.json()['id'])


def changed_chapters():
    intro, methods, _ = deepcopy(CHAPTERS)
    intro['title'] = '研究背景'        # title_changed (same id)
    methods['level'] = 2               # level_changed; listed first -> order_changed
    # school-results is dropped -> removed; two new chapters -> added
    return [methods, intro, dict(id='school-appendix', title='附录', level=1), dict(id='new-results', title='研究结论', level=1)]


def preview_body(item, revision, chapters):
    return dict(template_version_id=item['id'], expected_revision=revision, analysis_sha256=item['analysis_sha256'],
                decisions=[dict(conflict_id='conflict-1', option_id='text-2')], chapters=chapters)


def frozen_confirmation(client, monkeypatch):
    """Confirm with fixed identity and time so the snapshot can be compared byte for byte."""
    from app.domain.school_templates import service
    path, _, item = parsed(client)
    monkeypatch.setattr(service, 'uuid4', lambda: UUID('00000000-0000-4000-8000-000000000001'))
    monkeypatch.setattr(service, 'now', lambda: datetime(2026, 11, 19, tzinfo=timezone.utc))
    body = dict(analysis_sha256=item['analysis_sha256'], decisions=[dict(conflict_id='conflict-1', option_id='text-2')], chapters=CHAPTERS,
                text_decisions=[], format_profile=None)
    confirmed = post(client, path+'/school-templates/'+item['id']+'/confirm', body, 'frozen')
    assert confirmed.status_code == 201, confirmed.text
    snap = confirmed.json()
    normalized = json.loads(json.dumps(snap, ensure_ascii=False).replace(item['id'], 'TEMPLATE').replace(item['analysis_sha256'], 'ANALYSIS'))
    return path, item, body, snap, normalized


def test_confirm_snapshot_is_byte_identical_after_build_snapshot_extraction(client, monkeypatch):
    path, item, body, snap, normalized = frozen_confirmation(client, monkeypatch)
    assert normalized == json.loads(FIXTURE.read_text(encoding='utf-8'))
    assert post(client, path+'/school-templates/'+item['id']+'/confirm', body, 'frozen').status_code == 200
    with database_connection() as db:
        stored = db.execute('SELECT snapshot_json,snapshot_sha256 FROM school_template_confirmations WHERE id=%s', (snap['id'],)).fetchone()
    from app.domain.literature.service import digest
    assert stored['snapshot_json'] == snap and stored['snapshot_sha256'] == digest(snap)


def test_first_binding_preview_has_no_current_and_does_not_write(client):
    path, _, item = parsed(client)
    project_id = path.rsplit('/', 1)[1]
    before = counts(project_id)
    response = post(client, path+'/thesis-template-binding/preview', preview_body(item, 0, CHAPTERS))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['current'] is None
    assert result['next'] == dict(confirmation_id=None, template_name='合成模板', confirmed_at=None)
    assert {c['change'] for c in result['chapters']} == {'added'}
    assert result['manuscripts'] == []
    assert counts(project_id) == before


def test_changed_template_preview_lists_chapter_format_and_manuscript_effects(client):
    path, template, request = bound(client)
    project_id = path.rsplit('/', 1)[1]
    root = post(client, path+'/manuscripts', request, 'base').json()
    assert run_task(root['versions'][0]['task_id'], 1)['status'] == 'succeeded'
    for revision in (2, 3):
        appended = post(client, path+'/manuscripts/'+root['id']+'/versions', dict(request, expected_revision=revision-1), 'append-'+str(revision))
        assert appended.status_code == 201, appended.text
        assert run_task(appended.json()['versions'][0]['task_id'], 1)['status'] == 'succeeded'
    item = second_template(client, path, template)
    before = counts(project_id)
    profile = client.get(path+'/thesis-profile').json()
    response = post(client, path+'/thesis-template-binding/preview', preview_body(item, profile['revision'], changed_chapters()))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['current']['confirmation_id'] == profile['bound_confirmation_id']
    assert result['current']['template_name'] == '合成模板' and result['current']['confirmed_at']
    assert result['next']['confirmation_id'] is None and result['next']['template_name'] == '工程更新'
    changes = {(c['change'], c['title']): c for c in result['chapters']}
    assert changes[('title_changed', '研究背景')]['detail_params'] == {'from': '绪论', 'to': '研究背景'}
    assert changes[('title_changed', '研究背景')]['detail_key'] == 'chapter.title_changed'
    assert changes[('level_changed', '研究方法')]['detail_params'] == {'from': 1, 'to': 2}
    assert ('added', '附录') in changes and ('added', '研究结论') in changes
    assert ('removed', '结果') in changes
    assert changes[('order_changed', '研究方法')]['detail_params'] == {'from': 2, 'to': 1}
    assert changes[('order_changed', '研究背景')]['detail_params'] == {'from': 1, 'to': 2}
    size = next(o for o in result['outputs'] if o.get('rule_id') == 'heading1.font_size_pt')
    assert size['kind'] == 'word_format' and size['detail_key'] == 'format.rule' and size['detail_params'] == {'from': None, 'to': 16}
    assert size['category'] == 'heading1'
    assert result['manuscripts'] == [dict(manuscript_id=root['id'], title=root['title'], revision=3, keeps_template=True, next_action='migrate')]
    assert counts(project_id) == before


def test_preview_reuses_stored_confirmation_and_rejects_unresolved_or_stale_requests(client):
    path, template, _ = bound(client)
    project_id = path.rsplit('/', 1)[1]
    item = second_template(client, path, template)
    revision = client.get(path+'/thesis-profile').json()['revision']
    unresolved = dict(preview_body(item, revision, CHAPTERS), decisions=[])
    confirm_error = post(client, path+'/school-templates/'+item['id']+'/confirm', {k: v for k, v in unresolved.items() if k not in ('template_version_id', 'expected_revision')}, 'unresolved')
    preview_error = post(client, path+'/thesis-template-binding/preview', unresolved)
    assert preview_error.status_code == confirm_error.status_code
    assert preview_error.json()['detail']['code'] == confirm_error.json()['detail']['code'] == 'task_input_invalid'
    stale = post(client, path+'/thesis-template-binding/preview', preview_body(item, revision+5, CHAPTERS))
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'task_revision_conflict'
    renamed = deepcopy(CHAPTERS); renamed[2]['title'] = '已确认结果'
    confirmed = post(client, path+'/school-templates/'+item['id']+'/confirm', {k: v for k, v in preview_body(item, revision, renamed).items() if k not in ('template_version_id', 'expected_revision')}, 'confirm-second')
    assert confirmed.status_code == 201, confirmed.text
    before = counts(project_id)
    reused = post(client, path+'/thesis-template-binding/preview', dict(template_version_id=item['id'], expected_revision=revision))
    assert reused.status_code == 200, reused.text
    assert reused.json()['next']['confirmation_id'] == confirmed.json()['id'] and reused.json()['next']['confirmed_at']
    assert [c for c in reused.json()['chapters'] if c['change'] == 'title_changed'][0]['detail_params'] == {'from': '结果', 'to': '已确认结果'}
    ignored = post(client, path+'/thesis-template-binding/preview', dict(preview_body(item, revision, changed_chapters())))
    assert ignored.json()['chapters'] == reused.json()['chapters']
    assert counts(project_id) == before
    missing = post(client, path+'/thesis-template-binding/preview', dict(template_version_id='missing', expected_revision=revision))
    assert missing.status_code == 404


def test_unconfirmed_preview_requires_the_confirmation_fields(client):
    path, _, item = parsed(client)
    response = post(client, path+'/thesis-template-binding/preview', dict(template_version_id=item['id'], expected_revision=0))
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'task_input_invalid'


def test_header_footer_preview_compares_rendered_page_fields_and_their_positions():
    from app.domain.school_templates.binding_preview import output_changes

    def changes(old, new):
        before = dict(sections=[dict(footers=[dict(type='default', **old)])])
        after = dict(sections=[dict(footers=[dict(type='default', **new)])])
        return [change['detail_key'] for change in output_changes({}, {}, before, after)]

    page = dict(text='Page', fields=[' PAGE '])
    total = dict(text='Page', fields=['NUMPAGES'])
    assert changes(page, total) == ['format.headers_footers']
    text = dict(kind='text', text='Page')
    field = dict(kind='field', instruction='PAGE')
    assert changes(page, page | {'segments': [field, text]}) == ['format.headers_footers']
    assert changes(page, page | {'segments': [text, field]}) == []
    assert changes(page, dict(text='Page', fields=['PAGE', 'IGNORED'])) == []
