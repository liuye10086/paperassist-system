"""Owner-only figure and table notes for paper projects."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dataset_preparation import Store
from app.auth.permissions import require_customer_role
from app.domain.paper_materials import (
    FileId, PaperMaterialNote, PaperMaterialWrite, PaperMaterialsView,
    list_paper_materials, paper_worksheets, save_paper_material,
)


router = APIRouter(prefix='/api/v1/projects/{project_id}/paper-materials', tags=['论文图表资料'],
                   dependencies=[Depends(require_customer_role)])


@router.get('', response_model=PaperMaterialsView)
def materials(project_id: str, store: Store,
              file_id: Annotated[list[FileId] | None, Query(min_length=1, max_length=100)] = None):
    return list_paper_materials(store, project_id, file_id)


@router.put('/{note_id}', response_model=PaperMaterialNote)
def save_material(project_id: str, note_id: UUID, changes: PaperMaterialWrite, store: Store):
    return save_paper_material(store, project_id, str(note_id), changes)


@router.get('/worksheets/{file_id}')
def worksheets(project_id: str, file_id: FileId, store: Store):
    return paper_worksheets(store, project_id, file_id)
