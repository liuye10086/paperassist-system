from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response

from app.api.dataset_preparation import Store
from app.auth.permissions import require_customer_role
from app.domain.sci_draft_reader import SciDraftReader
from app.domain.manuscripts.school_draft_edits import SchoolDraftEdits


router = APIRouter(prefix='/api/v1/projects/{project_id}', tags=['论文初稿'], dependencies=[Depends(require_customer_role)])
READER = '/manuscripts/{manuscript_id}/writing-requests/{request_id}/draft-reader'
Revision = Annotated[int, Query(ge=1, le=2147483647)]


@router.get('/sci-current-draft')
def current(project_id: str, store: Store, manuscript_id: str | None = None, revision: Revision | None = None):
    return SciDraftReader(store).current(project_id, manuscript_id, revision)


@router.get('/draft-history')
def history(project_id: str, store: Store):
    return SciDraftReader(store).history(project_id)


@router.get(READER)
def read(project_id: str, manuscript_id: str, request_id: str, revision: Revision, store: Store):
    return SciDraftReader(store).detail(project_id, manuscript_id, request_id, revision)


@router.get(READER + '/figures/{number}')
def figure(project_id: str, manuscript_id: str, request_id: str, number: int, revision: Revision, store: Store):
    content = SciDraftReader(store).figure(project_id, manuscript_id, request_id, revision, number)
    return Response(content, media_type='image/png' if content.startswith(b'\x89PNG') else 'image/jpeg',
                    headers={'Cache-Control': 'private, no-store'})


@router.get(READER + '/word')
def download(project_id: str, manuscript_id: str, request_id: str, revision: Revision, store: Store):
    title, content = SciDraftReader(store).word(project_id, manuscript_id, request_id, revision)
    return word_response(title, content)


@router.post(READER + '/word')
def download_school_edits(project_id: str, manuscript_id: str, request_id: str, revision: Revision,
                          edits: SchoolDraftEdits, store: Store):
    title, content = SciDraftReader(store).word(project_id, manuscript_id, request_id, revision, school_edits=edits)
    return word_response(title, content)


def word_response(title, content):
    name = ''.join(c for c in title if c.isprintable() and c not in '<>:"/\\|?*').strip(' .')[:80] or '论文初稿'
    return Response(content=content,
                    media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name + '.docx', safe=''),
                             'Cache-Control': 'private, no-store'})
