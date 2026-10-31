"""Keep registered research deliveries out of the legacy manuscript workflows."""
from typing import Annotated
from fastapi import Depends,Request
from app.adapters.storage import ProjectStore,get_request_project_store
from app.domain.research_intake.delivery_access import require_legacy_writing


def legacy_writing_project(project_id:str,request:Request,store:Annotated[ProjectStore,Depends(get_request_project_store)]):
    project=store.project(project_id)
    if project['project_type']=='research':
        from app.adapters.task_store import TaskStore
        from app.domain.manuscripts.delivery_context import resolve_document_context
        tasks=TaskStore(store.owner_id,store.db_config)
        with tasks.connection() as db:
            manuscript=request.path_params.get('manuscript_id')
            if manuscript:
                return resolve_document_context(db,project_id,store.owner_id,manuscript_id=manuscript,active=request.method not in ('GET','HEAD'))
            if request.method=='GET' and request.url.path.endswith('/manuscripts'):
                return project
            if '/writing-authorizations' in request.url.path:
                # This service validates every exact owner-scoped bundle and its
                # manuscript delivery before authorizing or admitting any call.
                return project
            if any(segment in request.url.path for segment in ('/school-templates','/thesis-profile','/thesis-template-binding')):
                row=db.execute("SELECT id FROM research_deliveries WHERE project_id=%s AND kind='thesis_draft' AND active",(project_id,)).fetchone()
                if row:return resolve_document_context(db,project_id,store.owner_id,delivery_id=row['id'])
    return require_legacy_writing(store,project_id)
