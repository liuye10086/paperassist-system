"""Keep registered research deliveries out of the legacy manuscript workflows."""
from typing import Annotated
from fastapi import Depends
from app.adapters.storage import ProjectStore,get_request_project_store
from app.domain.research_intake.delivery_access import require_legacy_writing


def legacy_writing_project(project_id:str,store:Annotated[ProjectStore,Depends(get_request_project_store)]):
    return require_legacy_writing(store,project_id)
