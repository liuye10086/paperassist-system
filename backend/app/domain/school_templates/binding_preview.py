"""D6 read-only impact preview before (re)binding a thesis school template.

Nothing here writes: no confirmation row, no profile binding. An unconfirmed
target is evaluated with the same validation and snapshot composition as
``SchoolTemplateService.confirm`` (``build_snapshot``)."""
from datetime import datetime, timezone

from app.adapters.school_template_parser import rendered_story_segments
from app.core.exceptions import StorageError
from app.domain.manuscripts.school_changes import matching_chapter
from app.domain.manuscripts.sources import require_visible_snapshot
from .service import SchoolTemplateService


def _summary(db, service, project, confirmation_id):
    saved = db.execute('SELECT id,template_version_id,created_at FROM school_template_confirmations WHERE id=%s AND project_id=%s AND user_id=%s',
                       (confirmation_id, project, service.store.user_id)).fetchone()
    if not saved:
        return None, None
    row = service.row(db, project, saved['template_version_id'])
    snap = service.confirmation(db, row)
    return dict(confirmation_id=saved['id'], template_name=row['name'], confirmed_at=saved['created_at']), (row, snap)


def _change(title, change, **params):
    return dict(title=title, change=change, detail_key='chapter.' + change, detail_params=params)


def chapter_changes(current, next_):
    """Match like template migration: same id first, otherwise the same title."""
    old = {c['id']: c for c in current}
    pairs, used, result = [], set(), []
    for chapter in next_:
        match = matching_chapter(old, chapter)
        if match is None or match['id'] in used:
            result.append(_change(chapter['title'], 'added'))
            continue
        used.add(match['id'])
        pairs.append((match, chapter))
        if match['id'] == chapter['id'] and match['title'] != chapter['title']:
            result.append(_change(chapter['title'], 'title_changed', **{'from': match['title'], 'to': chapter['title']}))
        if match.get('level') != chapter.get('level'):
            result.append(_change(chapter['title'], 'level_changed', **{'from': match.get('level'), 'to': chapter.get('level')}))
    before = [c['id'] for c in current if c['id'] in used]
    for position, (match, chapter) in enumerate(pairs):
        if before.index(match['id']) != position:
            result.append(_change(chapter['title'], 'order_changed', **{'from': before.index(match['id']) + 1, 'to': position + 1}))
    result.extend(_change(c['title'], 'removed') for c in current if c['id'] not in used)
    return result


def _format(key, before, after, **extra):
    return dict(kind='word_format', detail_key='format.' + key, detail_params={'from': before, 'to': after}, **extra)


def _layout(analysis):
    sections = (analysis or {}).get('sections', [])
    stories = [[(story['type'], list(rendered_story_segments(story))) for story in section.get(key, [])]
               for section in sections for key in ('headers', 'footers')]
    numbers = [section.get('page_number') for section in sections]
    return stories, numbers


def output_changes(current, next_, current_analysis=None, next_analysis=None):
    """Compare the confirmed Word format by stable rule identity; values stay raw."""
    result = []
    before = {r['id']: r for r in (current or {}).get('rules', [])}
    after = {r['id']: r for r in next_.get('rules', [])}
    for identity in sorted(set(before) | set(after)):
        old, new = before.get(identity), after.get(identity)
        if (old or {}).get('value') == (new or {}).get('value') and bool(old) == bool(new):
            continue
        rule = new or old
        result.append(_format('rule', old.get('value') if old else None, new.get('value') if new else None,
                              rule_id=identity, category=rule.get('category'), label=rule.get('label')))
    if (current or {}).get('format_profile') != next_.get('format_profile'):
        result.append(_format('format_profile', (current or {}).get('format_profile'), next_.get('format_profile')))
    if bool((current or {}).get('front_matter')) != bool(next_.get('front_matter')):
        result.append(_format('front_matter', bool((current or {}).get('front_matter')), bool(next_.get('front_matter'))))
    if current is not None:
        (old_stories, old_numbers), (new_stories, new_numbers) = _layout(current_analysis), _layout(next_analysis)
        if old_stories != new_stories:
            result.append(_format('headers_footers', old_stories, new_stories))
        if old_numbers != new_numbers:
            result.append(_format('page_numbers', old_numbers, new_numbers))
    return result


def _manuscripts(db, service, project, next_id):
    rows = db.execute('''SELECT m.id,m.title,m.current_revision,v.snapshot_json FROM manuscripts m
        JOIN manuscript_versions v ON v.manuscript_id=m.id AND v.revision=m.current_revision
        WHERE m.project_id=%s AND m.user_id=%s ORDER BY m.updated_at DESC,m.id''', (project, service.store.user_id)).fetchall()
    items = []
    for row in rows:
        context = row['snapshot_json'].get('thesis_context')
        if not context or context.get('confirmation_id') == next_id:
            continue
        try:
            require_visible_snapshot(service.assets, db, project, row['snapshot_json'])
        except StorageError as exc:
            if exc.code != 'manuscript_source_not_visible':
                raise
            continue
        items.append(dict(manuscript_id=row['id'], title=row['title'], revision=row['current_revision'],
                          keeps_template=True, next_action='migrate'))
    return items


def preview_binding(assets, project, request):
    service = SchoolTemplateService(assets)
    with service.store.connection() as db:
        service.project(db, project)
        profile = service.profile_view(db, project)
        if profile['revision'] != request.expected_revision:
            raise StorageError('task_revision_conflict', '学校资料已更新，请刷新。', 409)
        row = service.row(db, project, request.template_version_id)
        sources, task = service.require_current(db, row)
        saved = db.execute('SELECT id,created_at FROM school_template_confirmations WHERE template_version_id=%s', (row['id'],)).fetchone()
        if saved:
            snap = service.confirmation(db, row)
            next_ = dict(confirmation_id=saved['id'], template_name=row['name'], confirmed_at=saved['created_at'])
        else:
            if request.analysis_sha256 is None or request.chapters is None:
                raise StorageError('task_input_invalid', '模板尚未确认，预览需要填写确认内容。', 422)
            from .contracts import ConfirmRequest
            confirm = ConfirmRequest.model_validate_json(request.model_dump_json(exclude={'template_version_id', 'expected_revision'}))
            snap = service.build_snapshot(db, project, row, confirm, service.request_body(confirm), sources, task,
                                          cid='preview', timestamp=datetime.now(timezone.utc))
            next_ = dict(confirmation_id=None, template_name=row['name'], confirmed_at=None)
        current, bound = _summary(db, service, project, profile['bound_confirmation_id']) if profile['bound_confirmation_id'] else (None, None)
        current_row, current_snap = bound or (None, None)
        return dict(current=current, next=next_,
                    chapters=chapter_changes(current_snap['chapters'] if current_snap else [], snap['chapters']),
                    outputs=output_changes(current_snap, snap, current_row['analysis_json'] if current_row else None, row['analysis_json']),
                    manuscripts=_manuscripts(db, service, project, next_['confirmation_id']))
