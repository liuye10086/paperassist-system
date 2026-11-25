"""Read an exact customer writing request and render its unadopted body and sources."""
from difflib import SequenceMatcher
import re

from app.adapters.manuscript_docx import _document, _figure, _save_document, _table
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.manuscript_writing.article_contract import editable_draft_section_ids, illustration_groups, labels
from app.domain.manuscript_writing.authorization import revisable_draft
from app.domain.manuscript_writing.context import citation_fragments
from app.domain.manuscript_writing.live_contracts import scoped_draft_revision
from app.domain.manuscript_writing.service import WritingService
from app.domain.manuscripts.execution import images_for
from app.domain.manuscripts.illustrations import BODY_REFERENCE


def citation_links(entries, references):
    """Group exact excerpts by the frozen bibliography number, even when alias order differs."""
    linked = {}
    for binding, evidence_ids in entries:
        reference_id = binding['project_reference_id']
        reference = references[reference_id]
        link = linked.setdefault(reference_id, dict(
            project_reference_id=reference_id, number=reference['number'], title=binding['metadata']['title'], excerpts=[]))
        evidence = {item['id']: item for item in binding['evidence']}
        for identity in evidence_ids:
            item = evidence[identity]
            excerpt = {key: item[key] for key in ('id', 'quote', 'reading_scope')}
            if excerpt not in link['excerpts']:
                link['excerpts'].append(excerpt)
    return sorted(linked.values(), key=lambda link: link['number'])


def paragraph_parts(paragraph, snapshot, manifest, references):
    if paragraph.get('citations'):
        # Frozen scientific numbers in the original prose must not be parsed as citation markers.
        prefix = next((value for value in ('Literature finding (not this study’s results): ', '文献发现（并非本研究结果）：')
                       if paragraph['origin'] == 'literature' and paragraph['text'].startswith(value)), '')
        parts = []
        for fragment in citation_fragments(snapshot, {**paragraph, 'text': paragraph['text'][len(prefix):]}):
            entries = [(b, [e['id'] for e in b['evidence']]) for b in fragment.get('bindings', [])]
            parts.append(dict(text=fragment['text'], citations=citation_links(entries, references)))
        parts[0]['text'] = prefix + parts[0]['text']
        return parts
    selected = [manifest[alias] for alias in paragraph.get('suggested_evidence_aliases', [])]
    if 'suggested_citation_anchors' in paragraph:
        parts = []
        cursor = 0
        for anchor in paragraph['suggested_citation_anchors']:
            end = paragraph['text'].index(anchor['sentence'], cursor) + len(anchor['sentence'])
            evidence = [manifest[alias] for alias in anchor['evidence_aliases']]
            parts.append(dict(text=paragraph['text'][cursor:end], citations=citation_links(
                [(item['binding'], [item['evidence_id']]) for item in evidence], references)))
            cursor = end
        if cursor < len(paragraph['text']):
            parts.append(dict(text=paragraph['text'][cursor:], citations=[]))
        return parts
    entries = [(item['binding'], [item['evidence_id']]) for item in selected]
    return [dict(text=paragraph['text'], citations=citation_links(entries, references))]


def paragraph_text(paragraph):
    return ''.join(part['text'] + ''.join(f'[{c["number"]}]' for c in part['citations']) for part in paragraph['parts'])


def section_groups(snapshot, section):
    if snapshot.get('thesis_context'):
        from app.domain.manuscripts.school import chapter_groups
        return chapter_groups(snapshot, section)
    return snapshot['results_groups'] if section['id'] == 'validation' else illustration_groups(snapshot, section)


def place_review_figures(paragraphs, groups):
    """Place each figure once, at its first mention in its own section."""
    remaining = {f['number']: f for group in groups for f in group['figures']}
    for paragraph in paragraphs:
        text = ''.join(part['text'] for part in paragraph['parts'])
        for match in BODY_REFERENCE.finditer(text):
            if match['kind'].lower() in ('table', '表'):
                continue
            figure = remaining.pop(int(match['number']), None)
            if figure is not None:
                paragraph.setdefault('figures', []).append(figure)
    for group in groups:
        group['figures'] = [f for f in group['figures'] if f['number'] in remaining]
    return [g for g in groups if g['figures'] or g['tables']]


def reader_references(snapshot, sections, references):
    links = [c for s in sections for p in s['paragraphs'] for part in p['parts'] for c in part['citations']]
    ordered = list(dict.fromkeys(c['project_reference_id'] for c in links))
    # A historical author may have typed a numeric marker as prose without a stored binding.
    # Preserve its old bibliography instead of inferring a source or silently changing its number.
    unbound_markers = any(re.search(r'\[\s*\d+(?:\s*[-,–]\s*\d+)*\s*\]', part['text'])
                          for s in sections for p in s['paragraphs'] for part in p['parts'])
    if unbound_markers:
        return sorted(references.values(), key=lambda r: r['number'])
    keep_numbers = any(p.get('citations') for s in snapshot['sections'] for p in s['paragraphs'])
    numbers = {ref: references[ref]['number'] if keep_numbers else index for index, ref in enumerate(ordered, 1)}
    for cite in links:
        cite['number'] = numbers[cite['project_reference_id']]
    for section in sections:
        for paragraph in section['paragraphs']:
            for part in paragraph['parts']:
                part['citations'].sort(key=lambda c: c['number'])
    return sorted((dict(references[ref], number=numbers[ref]) for ref in ordered), key=lambda r: r['number'])


def draft_content(snapshot, evidence):
    en = snapshot['output_language'] == 'en'
    school = bool(snapshot.get('thesis_context'))
    plan = snapshot.get('paper_plan') or {}
    headings = {} if school else {sid: english if en else chinese
                for sid, english, chinese in labels(snapshot.get('article_type', 'research'), snapshot)}
    references = {item['project_reference_id']: item for item in snapshot['references']}
    sections = []
    reference_heading = None
    for section in snapshot['sections']:
        sid = section['id']
        if not school and sid == 'references':
            if plan.get('sci_template'):
                reference_heading = dict(heading=headings[sid], level=section.get('level', 1))
            continue
        role = section.get('purpose', sid)
        paragraphs = [dict(id=p['id'], parts=paragraph_parts(p, snapshot, evidence, references))
                      for p in section['paragraphs'] if role != 'references']
        combined = sid == 'themes' and plan.get('combine_review_topics')
        illustrations = [dict(id=g['id'], title=headings[sid] if combined else g['title'], tables=g['tables'], figures=g['figures'])
                         for g in section_groups(snapshot, section) if g['tables'] or g['figures']]
        if plan.get('review_figure_placement_version') == 1 or plan.get('sci_figures'):
            illustrations = place_review_figures(paragraphs, illustrations)
        default_level = 0 if not school and sid == 'title' else 1
        view = dict(id=sid, heading=section['title'] if school else headings[sid],
                    level=section.get('level', default_level), paragraphs=paragraphs, groups=illustrations)
        if school:
            view.update(purpose=role, output_language=section['output_language'])
        sections.append(view)
    return dict(title=snapshot['title'], output_language=snapshot['output_language'], sections=sections,
                keywords=snapshot.get('keywords', []), acknowledgements=snapshot.get('acknowledgements', ''),
                references=reader_references(snapshot, sections, references),
                **({'reference_heading': reference_heading} if reference_heading else {}))


def draft_changes(before, after):
    """Compare paragraphs within each section; a model can replace all paragraph IDs on a rewrite."""
    old_sections = {s['id']: s for s in before['sections']}
    new_sections = {s['id']: s for s in after['sections']}
    changes = []
    for sid in dict.fromkeys([*new_sections, *old_sections]):
        old = old_sections.get(sid, {}).get('paragraphs', [])
        new = new_sections.get(sid, {}).get('paragraphs', [])
        old_text = [paragraph_text(p) for p in old]
        new_text = [paragraph_text(p) for p in new]
        for operation, start, end, new_start, new_end in SequenceMatcher(None, old_text, new_text, autojunk=False).get_opcodes():
            if operation != 'equal':
                changes.append(dict(section_id=sid, heading=(new_sections.get(sid) or old_sections[sid])['heading'],
                                    before=old_text[start:end], after=new_text[new_start:new_end],
                                    paragraph_ids=[p['id'] for p in new[new_start:new_end]]))
    return changes


class SciDraftReader:
    def __init__(self, assets):
        self.writing = WritingService(assets)
        self.store = self.writing.store

    def require_project(self, db, project):
        if self.store.require_project(db, project, role='customer')['project_type'] not in ('sci', 'thesis'):
            raise StorageError('customer_project_type_forbidden', '初稿阅读仅适用于论文项目。', 403)

    def history(self, project):
        with self.store.connection() as db:
            self.require_project(db, project)
            rows = db.execute("""SELECT r.manuscript_id, r.task_id FROM manuscript_writing_requests r
                JOIN tasks t ON t.id=r.task_id AND t.project_id=r.project_id AND t.user_id=r.user_id
                WHERE r.project_id=%s AND r.user_id=%s AND t.status='succeeded' AND r.candidate_json IS NOT NULL
                ORDER BY r.created_at DESC, r.task_id DESC""", (project, self.store.user_id)).fetchall()
            items = []
            for item in rows:
                try:
                    row, task = self.writing.row(db, project, item['manuscript_id'], item['task_id'])
                except StorageError as exc:
                    if exc.code not in ('manuscript_source_not_visible', 'manuscript_not_found'):
                        raise
                    continue
                original = row['request_json']
                items.append(dict(manuscript_id=row['manuscript_id'], revision=original['base_revision'],
                                  request_id=row['task_id'], published_revision=row['published_revision'],
                                  title=row['candidate_json']['title'], created_at=row['created_at'], status=task['status'],
                                  previous_request_id=original.get('revision_of_request_id')))
            return dict(items=items)

    def current(self, project, manuscript=None, revision=None):
        if (manuscript is None) != (revision is None):
            raise StorageError('task_input_invalid', '请同时指定稿件和版本。', 422)
        with self.store.connection() as db:
            self.require_project(db, project)
            scope = " AND r.request_json->>'mode'='full_draft'"
            published_first = ''
            params = [project, self.store.user_id]
            if manuscript is not None:
                scope = """ AND r.manuscript_id=%s
                    AND (r.request_json->>'base_revision'=%s OR r.published_revision=%s)
                    AND (r.request_json->>'mode'='full_draft' OR t.status='succeeded')"""
                published_first = 'CASE WHEN r.published_revision=%s THEN 0 ELSE 1 END, '
                params.extend([manuscript, str(revision), revision, revision])
            rows = db.execute("""SELECT r.manuscript_id, r.task_id FROM manuscript_writing_requests r
                JOIN tasks t ON t.id=r.task_id AND t.project_id=r.project_id AND t.user_id=r.user_id
                WHERE r.project_id=%s AND r.user_id=%s AND (r.request_json->>'draft_advice') IS DISTINCT FROM 'true'""" + scope + ' ORDER BY ' + published_first + """
                         CASE WHEN t.status IN ('failed','cancelled') THEN 1 ELSE 0 END,
                         r.created_at DESC, r.task_id DESC""", tuple(params)).fetchall()
            for item in rows:
                try:
                    row, task = self.writing.row(db, project, item['manuscript_id'], item['task_id'])
                except StorageError as exc:
                    if exc.code not in ('manuscript_source_not_visible', 'manuscript_not_found'):
                        raise
                    continue
                if task['status'] == 'succeeded' and not row['candidate_json']:
                    continue
                return dict(draft=dict(manuscript_id=item['manuscript_id'], revision=row['request_json']['base_revision'],
                                       request_id=item['task_id']))
            return dict(draft=None)

    def raw_content(self, db, project, manuscript, row, task):
        snapshot = row['candidate_json']
        execution = task['input_snapshot'].get('execution')
        manifest = {}
        if execution:
            # WritingService.row already replayed this bundle and candidate in this read transaction.
            bundle = db.execute("""SELECT bundle_json->'local_manifest'->'evidence' AS evidence
                FROM manuscript_writing_bundles WHERE id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s""",
                                (execution['bundle_id'], manuscript, project, self.store.user_id)).fetchone()
            if not bundle:
                raise source_conflict()
            manifest = bundle['evidence']
        try:
            return draft_content(snapshot, manifest)
        except (KeyError, ValueError, TypeError) as exc:
            raise source_conflict() from exc

    def school_edits(self, row, explicit=None):
        from app.domain.manuscripts.school_draft_edits import SchoolDraftEdits

        stored = row.get('school_draft_edits_json')
        if stored and stored['candidate_sha256'] != row['candidate_sha256']:
            raise source_conflict()
        generated = row['candidate_json'].get('school_presentation') or {}
        manual = stored['edits'] if stored else {}
        edits = {**generated, **manual}
        if explicit:
            edits.update(explicit.model_dump(mode='json', exclude_unset=True))
        return SchoolDraftEdits.model_validate(edits) if edits else None

    def content(self, db, project, manuscript, row, task):
        from app.domain.manuscripts.school_draft_edits import apply_export_edits

        draft = self.raw_content(db, project, manuscript, row, task)
        adjusted, _ = apply_export_edits(row['candidate_json'], draft, {}, self.school_edits(row))
        return adjusted

    def save_school_edits(self, project, manuscript, request_id, revision, edits):
        from psycopg.types.json import Jsonb
        from app.domain.manuscripts.school_draft_edits import apply_export_edits, invalid

        with self.store.connection(write=True) as db:
            row, task = self.exact_request(db, project, manuscript, request_id, revision)
            candidate = row['candidate_json']
            if (task['status'] != 'succeeded' or not candidate or not candidate.get('thesis_context')
                    or row['published_revision'] is not None or candidate['writing_provenance'].get('language_review_id')):
                raise invalid('只能调整当前可编辑的毕业论文初稿。')
            raw = self.raw_content(db, project, manuscript, row, task)
            effective = self.school_edits(row, edits)
            apply_export_edits(candidate, raw, {}, effective)
            previous = row['school_draft_edits_json']
            changes = {**(previous['edits'] if previous else {}), **edits.model_dump(mode='json', exclude_unset=True)}
            record = dict(candidate_sha256=row['candidate_sha256'], edits=changes)
            if record != previous:
                updated = db.execute("""UPDATE manuscript_writing_requests SET school_draft_edits_json=%s
                    WHERE task_id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s AND candidate_sha256=%s
                      AND published_revision IS NULL AND school_draft_edits_json IS NOT DISTINCT FROM %s
                    RETURNING task_id""", (Jsonb(record), request_id, manuscript, project, self.store.user_id,
                    row['candidate_sha256'], Jsonb(previous) if previous is not None else None)).fetchone()
                if not updated:
                    raise source_conflict()

    def exact_request(self, db, project, manuscript, request_id, revision):
        self.require_project(db, project)
        row, task = self.writing.row(db, project, manuscript, request_id)
        if row['request_json']['base_revision'] != revision:
            raise StorageError('manuscript_not_found', '指定版本没有这份初稿。', 404)
        return row, task

    def word(self, project, manuscript, request_id, revision, *, school_edits=None):
        with self.store.connection() as db:
            row, task = self.exact_request(db, project, manuscript, request_id, revision)
            if task['status'] != 'succeeded' or row['candidate_json'] is None:
                raise StorageError('task_revision_conflict', '正文尚未生成，请稍后查看。', 409)
            draft = self.raw_content(db, project, manuscript, row, task)
            snapshot = row['candidate_json']
            school = snapshot.get('thesis_context')
            if school_edits is not None and not school:
                raise StorageError('school_export_input_invalid', '学校排版修改仅适用于毕业论文。', 422)
            if school:
                school_edits = self.school_edits(row, school_edits)
                version = dict(project_id=project, snapshot_json=snapshot)
                options = self.writing.manuscripts.school_options(version, None)
                analysis = self.writing.manuscripts.school_analysis(db, version, current=False)
        images = images_for(self.writing.manuscripts, project, snapshot)
        content = (school_draft_word(self.writing.assets, snapshot, draft, images, options, analysis, edits=school_edits)
                   if school else draft_word(draft, images))
        return draft['title'], content

    def figure(self, project, manuscript, request_id, revision, number):
        with self.store.connection() as db:
            row, task = self.exact_request(db, project, manuscript, request_id, revision)
            snapshot = row['candidate_json']
            if task['status'] != 'succeeded' or snapshot is None:
                raise StorageError('task_revision_conflict', '正文尚未生成，请稍后查看。', 409)
            figure = next((f for s in snapshot['sections'] for g in section_groups(snapshot, s) for f in g['figures']
                           if f['number'] == number), None)
            if not figure:
                raise StorageError('figure_missing', '这份初稿没有指定图件。', 404)
            raw = images_for(self.writing.manuscripts, project, {**snapshot, 'results_groups': [{'figures': [figure]}]})[figure['id']]
        if figure.get('original_image_format') == 'tiff' and not figure.get('language_version_id'):
            from app.adapters.project_images import PREVIEW_MAX_SIDE, tiff_as_png
            raw = tiff_as_png(raw, max_side=PREVIEW_MAX_SIDE)
        elif figure.get('research_member_format') and not figure.get('language_version_id'):
            from app.adapters.research_report_images import as_png
            try:
                raw = as_png(raw, figure['research_member_format'])
            except (ValueError, OSError) as exc:
                raise source_conflict() from exc
        return raw

    def detail(self, project, manuscript, request_id, revision):
        with self.store.connection() as db:
            row, task = self.exact_request(db, project, manuscript, request_id, revision)
            request = row['request_json']
            advice = request.get('draft_advice') is True
            scoped = scoped_draft_revision(request)
            result = dict(project_id=project, manuscript_id=manuscript, request_id=request_id, revision=revision,
                          status=task['status'], error_code=self.store.public_task(task)['error_code'], draft=None,
                          previous_request_id=request.get('revision_of_request_id'), changes=[], can_revise=False)
            if scoped:
                result['target_sections'] = request['target_sections']
            if advice:
                result['draft_advice'] = True
            if scoped and task['status'] in ('queued', 'running'):
                result['partial_reply'] = (row.get('draft_chat_json') or {}).get('preview', [])
            if task['status'] != 'succeeded':
                return result
            if advice:
                from app.domain.manuscript_writing.live_contracts import DraftAdviceOutput
                try:
                    reply = {key: value for key, value in (row.get('draft_chat_json') or {}).items()
                             if key != 'first_preview_at'}
                    result['advice'] = DraftAdviceOutput.model_validate(reply).advice
                except ValueError as exc:
                    raise source_conflict() from exc
                return result
            if row['candidate_json'] is None:
                raise source_conflict()
            result['draft'] = self.content(db, project, manuscript, row, task)
            result['can_revise'] = (
                revisable_draft(row, task)
                and self.writing.manuscripts.root(db, project, manuscript)['current_revision'] == revision
            )
            if result['can_revise']:
                result['editable_section_ids'] = editable_draft_section_ids(row['candidate_json'])
            if result['previous_request_id']:
                previous, previous_task = self.writing.row(db, project, manuscript, result['previous_request_id'])
                if previous_task['status'] != 'succeeded' or previous['candidate_json'] is None:
                    raise source_conflict()
                before = self.content(db, project, manuscript, previous, previous_task)
                changes = draft_changes(before, result['draft'])
                if scoped:
                    targets = set(request['target_sections'])
                    changes = [change for change in changes if change['section_id'] in targets]
                result['changes'] = changes
            return result


def school_export_projection(snapshot, references):
    from app.domain.literature.service import digest
    from app.domain.school_templates import bsu_gs501

    context = snapshot['thesis_context']
    confirmation = context['confirmation']
    projected = {**snapshot, 'references': references}
    if (not confirmation.get('format_profile') and bsu_gs501.available(context['source_files'])
            and not snapshot.get('writing_provenance', {}).get('language_review_id')):
        # The exact uploaded template identifies the profile in the simplified flow.
        # Keep the stored confirmation and the model candidate immutable.
        local = {**confirmation, 'format_profile': bsu_gs501.PROFILE}
        projected['thesis_context'] = {**context, 'confirmation': local, 'confirmation_sha256': digest(local)}
    return projected


def school_draft_word(assets, snapshot, draft, images, options, analysis, *, edits=None):
    from app.adapters.school_docx import build_school_docx, complete_school_fields
    from app.domain.manuscripts.school_export import compile_school_export
    from app.domain.manuscripts.school_draft_edits import apply_export_edits, invalid
    from app.domain.school_templates import bsu_gs501

    if edits is not None and snapshot.get('writing_provenance', {}).get('language_review_id'):
        raise invalid('已完成语言审核的稿件须使用原审核版式。')
    draft, options = apply_export_edits(snapshot, draft, options, edits)
    projected = school_export_projection(snapshot, draft['references'])
    context = projected['thesis_context']
    if (bsu_gs501.selected(projected) and not context['confirmation'].get('front_matter')
            and not snapshot.get('writing_provenance', {}).get('language_review_id')):
        manual = dict(options.get('manual_fields', {}))
        for key in ('author', 'student_id', 'supervisor', 'submission_date', 'department'):
            if not manual.get(key) and context['profile'].get(key):
                manual[key] = context['profile'][key]
        options = {**options, 'manual_fields': manual}
    plan = compile_school_export(projected, analysis, options, submission_forms=True)
    template = (bsu_gs501.read_submission_template(assets, projected)
                if 'submission_forms_source_sha256' in plan else None)
    parts = {p['id']: p['parts'] for s in draft['sections'] for p in s['paragraphs']
             if any(part['citations'] for part in p['parts']) or edits and p['id'] in edits.citations}
    content = build_school_docx(projected, images, plan, school_template=template, draft_paragraphs=parts,
                                customer_revision=True, draft_edits=edits)
    content, _ = complete_school_fields(content, plan)
    return content


def draft_word(draft, images):
    document = _document()
    document.core_properties.title = draft['title']
    en = draft['output_language'] == 'en'
    for section in draft['sections']:
        title = section['id'] == 'title'
        level = section['level']
        if not title:
            document.add_heading(section['heading'], level=level)
        for paragraph in section['paragraphs']:
            if title:
                document.add_heading(paragraph_text(paragraph), level=level)
            else:
                document.add_paragraph(paragraph_text(paragraph), style='Normal')
            for figure in paragraph.get('figures', ()):
                _figure(document, figure, images, en)
        if section['id'] == 'abstract' and draft['keywords']:
            document.add_paragraph(('Keywords: ' if en else '关键词：') + (', ' if en else '、').join(draft['keywords']))
        for group in section['groups']:
            if group['title'] != section['heading']:
                document.add_heading(group['title'], level=2)
            for table in group['tables']:
                _table(document, table)
            for figure in group['figures']:
                _figure(document, figure, images, en)
    if draft['acknowledgements']:
        document.add_heading('Acknowledgements' if en else '致谢', level=1)
        document.add_paragraph(draft['acknowledgements'])
    if draft['references']:
        reference_heading = draft.get('reference_heading', dict(heading='References' if en else '参考文献', level=1))
        document.add_heading(reference_heading['heading'], level=reference_heading['level'])
        for reference in draft['references']:
            document.add_paragraph(f'[{reference["number"]}] {reference["text"]}')
    return _save_document(document)
