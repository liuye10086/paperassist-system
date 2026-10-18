"""HTTP routes for analysis; business operations live in domain."""
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import Store, Settings
from app.domain import analysis as operations
from app.domain.analysis import CheckSelection, SaveSelection, SheetProfile, SelectionCheck, SavedSetup
from app.domain.comparison.contracts import GroupOptions

router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}', tags=['分析配置'])


@router.get('/comparison-group-options', response_model=GroupOptions)
def comparison_group_options(project_id: str,file_id: str,store: Store,
        dataset_id: Annotated[str,Query(min_length=1,max_length=64)],
        sheet: Annotated[str,Query(min_length=1,max_length=31)],
        group_column: Annotated[str,Query(pattern=r'^[A-Z]{1,3}$')]):
    from app.domain.dataset_analysis import load_dataset
    from app.domain.comparison.checks import group_options
    _,source,prepared=load_dataset(store,project_id,file_id,dataset_id)
    if source['kind']!='prepared_dataset_version':
        from app.core.exceptions import StorageError
        raise StorageError('task_input_invalid','组值读取仅支持已确认整理版本。',422)
    return group_options(prepared,dataset_id,sheet,group_column)


@router.get('/analysis-profile', response_model=SheetProfile)
def get_profile(project_id: str, file_id: str, store: Store, settings: Settings,
                sheet: Annotated[str, Query(min_length=1, max_length=31)],
                dataset_id: Annotated[str | None, Query(min_length=1)] = None):
    return operations.get_profile(project_id, file_id, store, settings, sheet, dataset_id)

@router.post('/analysis-check', response_model=SelectionCheck)
def check_selection(project_id: str, file_id: str, selection: CheckSelection, store: Store, settings: Settings):
    return operations.check_selection(project_id, file_id, selection, store, settings)

@router.get('/analysis-setup', response_model=SavedSetup | None)
def get_setup(project_id: str, file_id: str, store: Store):
    return operations.get_setup(project_id, file_id, store)

@router.put('/analysis-setup', response_model=SavedSetup)
def save_setup(project_id: str, file_id: str, request: SaveSelection, store: Store, settings: Settings):
    return operations.save_setup(project_id, file_id, request, store, settings)
