"""HTTP routes for analysis; business operations live in domain."""
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import Store, Settings
from app.domain import analysis as operations
from app.domain.analysis import AnalysisSelection, SaveSelection, SheetProfile, SelectionCheck, SavedSetup

router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}', tags=['分析配置'])


@router.get('/analysis-profile', response_model=SheetProfile)
def get_profile(project_id: str, file_id: str, store: Store, settings: Settings,
                sheet: Annotated[str, Query(min_length=1, max_length=31)]):
    return operations.get_profile(project_id, file_id, store, settings, sheet)

@router.post('/analysis-check', response_model=SelectionCheck)
def check_selection(project_id: str, file_id: str, selection: AnalysisSelection, store: Store, settings: Settings):
    return operations.check_selection(project_id, file_id, selection, store, settings)

@router.get('/analysis-setup', response_model=SavedSetup | None)
def get_setup(project_id: str, file_id: str, store: Store):
    return operations.get_setup(project_id, file_id, store)

@router.put('/analysis-setup', response_model=SavedSetup)
def save_setup(project_id: str, file_id: str, request: SaveSelection, store: Store, settings: Settings):
    return operations.save_setup(project_id, file_id, request, store, settings)
