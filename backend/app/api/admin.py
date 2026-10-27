"""Admin safe projections and owner-only usage. Business recovery keeps existing routes."""
from datetime import datetime
from typing import Annotated,Literal

from fastapi import APIRouter,Depends,Query,Request
from pydantic import BaseModel,BeforeValidator,ConfigDict,Field,field_validator,model_validator

from app.api.tasks import decimal_query_integer
from app.db.database import database_connection
from app.domain.admin_operations import AdminOperations,require_identity
from app.domain.admin_usage import UsageReporting
from app.domain.tasks.contracts import TaskStatus,TaskType

router=APIRouter(prefix='/api/v1',tags=['运营后台'])
PageValue=Annotated[int,BeforeValidator(decimal_query_integer),Field(ge=1,le=1_000_000)]
PageSizeValue=Annotated[int,BeforeValidator(decimal_query_integer),Field(ge=1,le=50)]
Identifier=Annotated[str,Field(min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')]


class QueryContract(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Paging(QueryContract):
    page:PageValue=1
    page_size:PageSizeValue=10


class TimeRange(QueryContract):
    start:datetime|None=Field(default=None,alias='from')
    end:datetime|None=Field(default=None,alias='to')

    @model_validator(mode='after')
    def valid_bounds(self):
        # Pydantic validation raises ValueError; service validates again for direct calls.
        if any(value is not None and value.tzinfo is None for value in (self.start,self.end)):
            raise ValueError('查询时间必须包含时区。')
        if self.start and self.end and self.start>=self.end:raise ValueError('开始时间必须早于结束时间。')
        return self


class UsersQuery(Paging):
    q:str|None=Field(default=None,min_length=1,max_length=254)
    role:Literal['user','admin']|None=None
    active:bool|None=None

    @field_validator('active',mode='before')
    @classmethod
    def exact_boolean(cls,value):
        if value not in (None,True,False,'true','false'):raise ValueError('启用筛选须为true或false。')
        return value


class TaskQuery(Paging,TimeRange):
    status:TaskStatus|None=None
    task_type:TaskType|None=None
    user_id:Identifier|None=None


class OwnUsageQuery(Paging,TimeRange):
    project_id:Identifier|None=None
    task_id:Identifier|None=None
    model:str|None=Field(default=None,min_length=1,max_length=200,pattern=r'^\S+$')
    group_by:Literal['user','project','task','model','day','month']='model'
    group_page:PageValue=1
    group_page_size:PageSizeValue=50


class AdminUsageQuery(OwnUsageQuery):
    user_id:Identifier|None=None


class SaveUsageSummary(TimeRange):
    user_id:Identifier|None=None
    project_id:Identifier|None=None
    task_id:Identifier|None=None
    model:str|None=Field(default=None,min_length=1,max_length=200,pattern=r'^\S+$')
    group_by:Literal['user','project','task','model','day','month']='model'


class SavedSummaryPaging(Paging):
    group_page:PageValue=1
    group_page_size:PageSizeValue=50


class LogsQuery(Paging,TimeRange):
    request_id:str|None=Field(default=None,pattern=r'^[0-9a-f]{32}$')
    task_id:Identifier|None=None
    user_id:Identifier|None=None
    status:Annotated[int,BeforeValidator(decimal_query_integer),Field(ge=100,le=599)]|None=None


class AuditQuery(Paging,TimeRange):
    target_user_id:Identifier|None=None
    actor_user_id:Identifier|None=None


class AccountChange(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    role:Literal['user','admin']
    active:bool
    expected_revision:int=Field(ge=1,lt=2_147_483_647)
    reason:str=Field(min_length=5,max_length=500)

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls,value):
        value=value.strip()
        if len(value)<5 or any(ord(char)<32 or ord(char)==127 for char in value):
            raise ValueError('请填写至少5个字符的具体修改理由。')
        return value


def admin_service(request:Request):
    user_id=request.state.user['id']
    with database_connection() as db:require_identity(db,user_id)
    return AdminOperations(user_id)


Admin=Annotated[AdminOperations,Depends(admin_service)]


@router.get('/admin/users')
def users(service:Admin,query:Annotated[UsersQuery,Query()]):return service.list_users(**query.model_dump())


@router.patch('/admin/users/{user_id}')
def update_user(user_id:str,body:AccountChange,request:Request,service:Admin):
    return service.change_user(user_id,body,request.state.request_id)


@router.get('/admin/tasks')
def tasks(service:Admin,query:Annotated[TaskQuery,Query()]):return service.list_tasks(**query.model_dump())


@router.get('/admin/tasks/{task_id}')
def task(task_id:str,service:Admin):return service.task_detail(task_id)


@router.get('/admin/usage')
def admin_usage(service:Admin,query:Annotated[AdminUsageQuery,Query()]):
    return UsageReporting(service.user_id,admin=True).read(**query.model_dump())


@router.get('/me/usage')
def own_usage(request:Request,query:Annotated[OwnUsageQuery,Query()]):
    return UsageReporting(request.state.user['id']).read(**query.model_dump())


@router.post('/admin/usage/summaries',status_code=201)
def save_usage_summary(service:Admin,body:SaveUsageSummary):
    from app.domain.admin_usage_summaries import UsageSummaries
    return UsageSummaries(service.user_id).save(**body.model_dump())


@router.get('/admin/usage/summaries')
def saved_usage_summaries(service:Admin,query:Annotated[Paging,Query()]):
    from app.domain.admin_usage_summaries import UsageSummaries
    return UsageSummaries(service.user_id).list(**query.model_dump())


@router.get('/admin/usage/summaries/{identity}')
def saved_usage_summary(identity:str,service:Admin,query:Annotated[SavedSummaryPaging,Query()]):
    from app.domain.admin_usage_summaries import UsageSummaries
    return UsageSummaries(service.user_id).detail(identity,**query.model_dump())


@router.post('/admin/usage/summaries/{identity}/verify')
def verify_usage_summary(identity:str,service:Admin,body:QueryContract):
    from app.domain.admin_usage_summaries import UsageSummaries
    return UsageSummaries(service.user_id).verify(identity)


@router.get('/admin/logs')
def logs(service:Admin,query:Annotated[LogsQuery,Query()]):return service.logs(**query.model_dump())


@router.get('/admin/audit')
def audit(service:Admin,query:Annotated[AuditQuery,Query()]):return service.audits(**query.model_dump())


@router.get('/admin/metrics')
def metrics(service:Admin,query:Annotated[TimeRange,Query()]):return service.metrics(**query.model_dump())
