"""Bind explicitly checked PubMed abstract excerpts to a manuscript citation draft."""
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.literature_citations.service import conflict
from .contracts import Strict


class SelectedReference(Strict):
    project_reference_id: str = Field(min_length=1, max_length=128)
    search_id: str = Field(min_length=1, max_length=128)
    # A paper shortlist selects the saved abstract; a passage selection carries an exact quote.
    quote: str | None = Field(default=None, min_length=1, max_length=6000)

    @field_validator('project_reference_id', 'search_id', 'quote')
    @classmethod
    def valid_text(cls, value):
        if value is not None and (not value.strip() or '\x00' in value):
            raise ValueError('A saved reference, search and exact excerpt are required.')
        return value


class SelectedReferencesRequest(Strict):
    references: list[SelectedReference] = Field(min_length=1, max_length=20)
    output_language: Literal['zh-CN', 'en'] | None = None

    @model_validator(mode='after')
    def unique_references(self):
        if len({ref.project_reference_id for ref in self.references}) != len(self.references):
            raise ValueError('Each selected PubMed reference must be distinct.')
        return self


def selected_metadata(citations, db, project, item, index, key):
    reference_id = item.project_reference_id
    reference = citations.literature.require_reference(db, project, reference_id)
    if reference['selection_status'] == 'excluded':
        raise StorageError('selected_reference_excluded', f'所选第 {index} 篇文献已排除，请重新选择。',
                           409, params={'position': index})

    latest = db.execute('''SELECT * FROM literature_citation_metadata_versions
        WHERE project_id=%s AND user_id=%s AND project_reference_id=%s ORDER BY revision DESC LIMIT 1''',
        (project, citations.store.user_id, reference_id)).fetchone()
    if latest and latest['request_json']['search_id'] == item.search_id:
        existing = citations.metadata_view(db, project, latest)
        if existing['usable']:
            return existing

    metadata, _ = citations.create_metadata(project, reference_id, dict(
        mode='extract', search_id=item.search_id, expected_revision=latest['revision'] if latest else 0,
    ), key, connection=db)
    if not metadata['usable']:
        raise StorageError('selected_reference_metadata_incomplete', f'所选第 {index} 篇文献缺少引用所需的书目信息。',
                           409, params={'position': index})
    return metadata


def abstract_excerpts(record, index, remaining):
    from app.domain.manuscript_writing.bundle import safe_text

    params = {'position': index, 'pmid': int(record['pmid'])}

    def too_long():
        return StorageError('selected_reference_abstract_limit', '此文献的摘要摘录超出本次写作支持的长度或段落数。', 422, params=params)

    def allowed(text):
        try:
            safe_text(text)
            return True
        except StorageError as exc:
            if exc.code != 'manuscript_writing_material_blocked':
                raise
            return False

    excerpts = []
    for number, section in enumerate(record['abstract']):
        text = section['text']
        if not text.strip():
            continue
        if len(text) <= 12000 and allowed(text):
            spans = [(0, len(text))]
        else:
            # Keep contiguous runs of complete eligible sentences. Never split a
            # path, URL or credential into fragments to make it pass inspection.
            spans = []
            start = 0
            run = None
            for boundary in [*re.finditer(r'(?<=[.!?。！？])\s+', text), None]:
                end = boundary.start() if boundary else len(text)
                sentence = text[start:end]
                if sentence.strip() and allowed(sentence):
                    if len(sentence) > 12000:
                        raise too_long()
                    if run is None or end - run[0] > 12000:
                        run = [start, end]
                        spans.append(run)
                    else:
                        run[1] = end
                else:
                    run = None
                start = boundary.end() if boundary else end
        for start, end in spans:
            quote = safe_text(text[start:end])
            excerpts.append(dict(quote=quote, abstract_location=dict(abstract_index=number, start=start)))
            if len(excerpts) > min(20, remaining):
                raise too_long()
    if not excerpts:
        raise StorageError('selected_reference_abstract_unusable', '此文献的摘要没有可用于初稿的原文。', 422, params=params)
    return excerpts


def selected_paragraph(citations, db, project, item, language, index, key, remaining):
    metadata = selected_metadata(citations, db, project, item, index, key)
    if item.quote is None:
        reference = citations.literature.require_reference(db, project, item.project_reference_id)
        record = citations.literature.reference_view(db, reference, item.search_id)['record']
        excerpts = abstract_excerpts(record, index, remaining)
        context = ('Verbatim source text from the selected PubMed abstract.' if language == 'en'
                   else '所选文献保存在 PubMed 检索回执中的摘要原文。')
        limitation = ('Abstract only. New manuscript claims require review.' if language == 'en'
                      else '阅读范围仅为摘要。根据摘要撰写的新论述仍需核对。')
    else:
        excerpts = [dict(quote=item.quote)]
        context = ('Excerpt checked against the saved PubMed abstract.' if language == 'en'
                   else '已对照保存的 PubMed 摘要核对摘录。')
        limitation = ('Only the selected abstract excerpt was checked.' if language == 'en' else '阅读范围仅为所选摘要摘录。')
    evidence = citations.evidence
    first = excerpts[0]['quote']
    # Public citation links are valid only in full. End the claim at a word
    # boundary when the evidence is longer than a claim can hold.
    content = first if len(first) <= 6000 else re.sub(r'\s+\S*$', '', first[:6000]).strip() or first[:6000]
    claim, _ = evidence.create_claim(project, dict(
        content=content, context=context, output_language=language,
    ), key, connection=db)
    evidence_ids = []
    try:
        for position, excerpt in enumerate(excerpts):
            source, _ = evidence.create_evidence(project, claim['id'], dict(
                claim_revision=1, source_kind='abstract', project_reference_id=item.project_reference_id,
                search_id=item.search_id, **excerpt,
            ), f'{key}-part-{position}' if item.quote is None else key, connection=db)
            evidence_ids.append(source['id'])
    except StorageError as exc:
        if exc.code != 'task_input_invalid':
            raise
        raise StorageError('selected_reference_quote_invalid', f'所选第 {index} 篇文献的摘录与摘要原文不符。',
                           422, params={'position': index}) from exc
    review, _ = evidence.create_review(project, claim['id'], dict(
        claim_revision=1, project_reference_id=item.project_reference_id, evidence_ids=evidence_ids,
        status='supported', relevance='related', reason=context, limitations=limitation,
    ), key, connection=db)
    binding = dict(review_id=review['id'], metadata_version_id=metadata['id'])
    paragraph = dict(id=f'abstract-{index}', fragments=[dict(
        kind='claim', claim_id=claim['id'], claim_revision=1, bindings=[binding],
    )])
    return paragraph, len(evidence_ids)


def select_references(service, project, request, key):
    require_key(key)
    citations = service.citations
    # The draft root identifies this operation; its immutable first version records
    # the input fingerprint so retries survive source, language or metadata changes.
    draft_key = 'selected-references-' + digest(key)
    version_key = digest(request.model_dump(mode='json'))
    with service.store.connection(write=True) as db:
        citations.evidence.lock(db, project)
        paper = service.require_project(db, project)
        if paper['project_type'] not in ('sci', 'thesis'):
            raise StorageError('customer_project_type_forbidden', '此功能用于 SCI 和毕业论文项目。', 403)
        existing = citations.rows(db, 'literature_citation_drafts', project, ' AND idempotency_key=%s', (draft_key,))
        if existing:
            _, first = citations.draft_row(db, project, existing[0]['id'], 1)
            if first['idempotency_key'] != version_key:
                raise StorageError('task_idempotency_conflict', '请求标识已用于其他文献或摘录。', 409)
            return dict(id=first['draft_id'], revision=1), 200

        if any(item.quote is None for item in request.references):
            shortlist = db.execute("""SELECT id FROM project_references WHERE project_id=%s
                AND user_id=%s AND selection_status='shortlisted' FOR SHARE""", (project, citations.store.user_id)).fetchall()
            if any(item.quote is not None for item in request.references):
                raise StorageError('task_input_invalid', '请使用同一方式选择本项目的文献。', 422)
            if {row['id'] for row in shortlist} != {item.project_reference_id for item in request.references}:
                raise StorageError('literature_revision_conflict', '已选文献发生变化，请重新读取。', 409)
        language = request.output_language or paper['default_output_language']
        paragraphs = []
        remaining = 100
        for index, item in enumerate(request.references, 1):
            paragraph, count = selected_paragraph(citations, db, project, item, language, index, f'{draft_key}-{index}', remaining)
            paragraphs.append(paragraph)
            remaining -= count
        draft, status = citations.create_draft_in_transaction(db, project, dict(
            title='Selected PubMed abstracts' if language == 'en' else '所选 PubMed 摘要',
            output_language=language, paragraphs=paragraphs,
        ), draft_key, version_key=version_key)
        if draft['current_changes']:
            raise conflict('文献的当前检索来源已变化，请重新读取候选文献并核对摘要。')
        return dict(id=draft['id'], revision=draft['revision']), status
