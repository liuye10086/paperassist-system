"""Compose and read formal figures for customer paper projects."""
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field, StringConstraints, model_validator

from app.adapters.project_images import IMAGE_MEDIA_TYPES
from app.api.bio_datasets import Key, Page, Store
from app.auth.permissions import require_customer_role
from app.domain.research_results.contracts import Identifier, MAX_PAPER_FIGURE_PANELS, PaperFigureRequest, StrictModel
from app.domain.research_results.figures import ResearchFigureService, SCI_FIGURE_ENTRYPOINT, THESIS_FIGURE_ENTRYPOINT


class SciFigureWrite(StrictModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    file_ids: list[Identifier] = Field(min_length=1, max_length=MAX_PAPER_FIGURE_PANELS)
    columns: int = Field(ge=1, le=3)
    root_id: Identifier | None = None
    expected_revision: int = Field(default=0, ge=0, lt=2147483647)

    @model_validator(mode='after')
    def validate_selection(self):
        if len(self.file_ids) != len(set(self.file_ids)):
            raise ValueError('同一张原图只能选择一次。')
        if (self.root_id is None) != (self.expected_revision == 0):
            raise ValueError('修订图件时需提交当前版本号。')
        return self

    def figure_request(self):
        composite = len(self.file_ids) > 1
        return PaperFigureRequest.model_validate(dict(
            title=self.title, columns=self.columns, root_id=self.root_id, expected_revision=self.expected_revision,
            mode='composite' if composite else 'reuse',
            panels=[dict(label=chr(ord('A') + index) if composite else '',
                         source=dict(source_kind='original_file', source_id=file_id))
                    for index, file_id in enumerate(self.file_ids)],
        ))


class FigureAssemblyCancel(StrictModel):
    expected_revision: int = Field(ge=1, lt=2147483647)


def _paper_figure_router(entrypoint: str, tag: str) -> APIRouter:
    workspace = entrypoint.removesuffix('_figures')
    figure_router = APIRouter(prefix=f'/api/v1/projects/{{project_id}}/{workspace}-figures', tags=[tag],
                              dependencies=[Depends(require_customer_role)])

    @figure_router.get('', name=f'list_{workspace}_figures')
    def list_figures(project_id: str, store: Store, page: Page = 1,
                     page_size: int = Query(default=20, ge=1, le=50)):
        return ResearchFigureService(store, entrypoint=entrypoint).list(project_id, page, page_size)

    @figure_router.post('', status_code=201, name=f'create_{workspace}_figure')
    def create_figure(project_id: str, request: SciFigureWrite, store: Store, idempotency_key: Key, response: Response):
        result, response.status_code = ResearchFigureService(store, entrypoint=entrypoint).create(
            project_id, request.figure_request(), idempotency_key)
        return result

    @figure_router.get('/assembly', name=f'list_{workspace}_figure_assembly')
    def list_assembly(project_id: str, store: Store, page: Page = 1, group_page: Page = 1,
                      page_size: int = Query(default=20, ge=1, le=50)):
        return ResearchFigureService(store, entrypoint=entrypoint).assembly(project_id, page, group_page, page_size)

    @figure_router.post('/{root_id}/cancel', status_code=204, response_class=Response, name=f'cancel_{workspace}_figure_assembly')
    def cancel_assembly(project_id: str, root_id: Identifier, request: FigureAssemblyCancel, store: Store):
        ResearchFigureService(store, entrypoint=entrypoint).cancel_assembly(project_id, root_id, request.expected_revision)
        return Response(status_code=204)

    @figure_router.get('/{version_id}', name=f'get_{workspace}_figure')
    def get_figure(project_id: str, version_id: str, store: Store):
        return ResearchFigureService(store, entrypoint=entrypoint).get(project_id, version_id)

    @figure_router.get('/{version_id}/members/{member_id}/download', response_class=Response,
                       name=f'download_{workspace}_figure_member')
    def download_figure_member(project_id: str, version_id: str, member_id: str, store: Store):
        member, content = ResearchFigureService(store, entrypoint=entrypoint).member(project_id, version_id, member_id)
        media_types = {**IMAGE_MEDIA_TYPES, 'json': 'application/json', 'py': 'text/plain'}
        filename = f"{member['key']}.{member['format']}"
        return Response(content, media_type=media_types.get(member['format'], 'application/octet-stream'), headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            'X-Content-Type-Options': 'nosniff',
        })

    return figure_router


router = _paper_figure_router(SCI_FIGURE_ENTRYPOINT, 'SCI 图件拼版')
thesis_router = _paper_figure_router(THESIS_FIGURE_ENTRYPOINT, '毕业论文图件拼版')
