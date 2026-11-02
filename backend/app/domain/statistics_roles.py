"""Explicit metadata and repeat checks over frozen records; never average repeats."""
from typing import Annotated, Literal
from math import isfinite
from pydantic import BaseModel,ConfigDict,Field,model_validator,model_serializer
from app.core.exceptions import StorageError

Column=Annotated[str,Field(pattern=r'^[A-Z]{1,3}$')]
class RoleField(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    column:Column
    name:str=Field(default='',max_length=200)
    unit:str=Field(default='',max_length=80)
    unit_status:Literal['unknown','declared','confirmed']='unknown'
    missing_definition:str=Field(default='blank only; no automatic recoding',max_length=500)
    inclusion:str=Field(default='frozen prepared rows; selected complete records',max_length=500)
    exclusion:str=Field(default='',max_length=500)
class StatisticsDataRoles(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    schema_version:Literal[1]=1
    individual_id:Column|None=None
    endpoint:Column|None=None
    group:Column|None=None
    pair:Column|None=None
    time:Column|None=None
    dose:Column|None=None
    structure:Literal['unknown','independent','paired_wide','paired_long','repeated_long']='unknown'
    time_order:list[str]=Field(default_factory=list,max_length=100)
    dictionary:list[RoleField]=Field(default_factory=list,max_length=100)
    test_family:str=Field(default='',max_length=500)
    @model_validator(mode='after')
    def coherent(self):
        if len({x.column for x in self.dictionary})!=len(self.dictionary):raise ValueError('Duplicate dictionary column')
        if len(set(self.time_order))!=len(self.time_order):raise ValueError('Duplicate time order')
        if self.structure in ('paired_long','repeated_long') and not all((self.individual_id,self.endpoint,self.time)):
            raise ValueError('Long repeats require individual, endpoint and time roles')
        if self.structure=='paired_long' and len(self.time_order)!=2:raise ValueError('Paired long requires two explicit time labels')
        return self
class RoleSelection(BaseModel):
    data_roles:StatisticsDataRoles|None=None
    @model_serializer(mode='wrap')
    def serialize_roles(self,handler):
        value=handler(self)
        if self.data_roles is None:value.pop('data_roles',None)
        return value

def identity(value):return (type(value).__name__,str(value))
def validate_role_records(rows,roles,*,inference=False):
    roles=StatisticsDataRoles.model_validate(roles)
    seen=set();people=set();repeated=False
    for row in rows:
        person=row.get(roles.individual_id) if roles.individual_id else None
        if roles.individual_id and person is None:raise StorageError('numeric_id_missing','个体ID缺失；请核对数据角色。',422)
        key=identity(person)
        if roles.individual_id:
            repeated|=key in people;people.add(key)
        if roles.time:
            time=row.get(roles.time)
            if time is None:raise StorageError('numeric_roles_missing','时间字段缺失。',422)
            if roles.individual_id:
                pair=(key,identity(time),roles.endpoint)
                if pair in seen:raise StorageError('pair_id_duplicate','个体×时点×终点重复；不会自动取均值。',422)
                seen.add(pair)
    if inference and (roles.structure=='repeated_long' or repeated and roles.structure!='paired_long'):
        raise StorageError('numeric_roles_missing','重复测量仅支持描述轨迹或两个时点的完整配对；不能作为独立组推断。',422)
    return dict(individual_n=len(people) if roles.individual_id else None,row_n=len(rows),repeated=repeated)

def long_pairs(rows,roles):
    roles=StatisticsDataRoles.model_validate(roles);validate_role_records(rows,roles)
    if roles.structure!='paired_long':raise StorageError('numeric_roles_missing','仅支持两个预设时点的完整配对。',422)
    grouped={};excluded=[]
    for row in rows:
        label=str(row[roles.time]);key=identity(row[roles.individual_id])
        if label not in roles.time_order:raise StorageError('numeric_roles_missing','存在未声明时点；多时点仅支持描述。',422)
        grouped.setdefault(key,{})[label]=row
    groups=[[],[]];group_rows=[[],[]]
    for records in grouped.values():
        if any(t not in records or records[t].get(roles.endpoint) is None for t in roles.time_order):
            excluded.extend(dict(row=r['row'],coordinates=[f"{roles.endpoint}{r['row']}"],reason='incomplete_pair') for r in records.values());continue
        for index,time in enumerate(roles.time_order):
            row=records[time];value=row[roles.endpoint]
            if type(value) not in (int,float) or not isfinite(value):raise StorageError('numeric_type','配对终点必须为有限数值。',422)
            groups[index].append(float(value));group_rows[index].append(row['row'])
    return dict(groups=groups,group_rows=group_rows,excluded_rows=excluded,individual_n=len(groups[0]))

def sheet_records(sheet,roles):
    """Read all active rows with typed identities and original coordinates."""
    from decimal import Decimal
    from openpyxl.utils.cell import get_column_letter
    from app.domain.dataset_analysis import binary64
    from app.domain.dataset_profile.scan import missing
    from app.domain.dataset_rows import source_rows
    fields={get_column_letter(f.column):f for f in sheet.fields}
    chosen={x for x in (roles.individual_id,roles.endpoint,roles.group,roles.pair,roles.time,roles.dose) if x}|{f.column for f in roles.dictionary}
    if not chosen<=fields.keys():raise StorageError('invalid_column','数据角色或字典字段不存在。',422)
    for field in roles.dictionary:
        actual=fields[field.column].unit
        if (field.unit_status=='confirmed' and (actual.status!='confirmed' or actual.value!=field.unit)
            or actual.status=='confirmed' and field.unit and field.unit!=actual.value):
            raise StorageError('unit_conflict','数据字典单位与冻结字段不一致。',422)
    cells={(c.row,get_column_letter(c.column)):c for c in sheet.cells};rows=[]
    for index in source_rows(sheet):
        row={'row':index}
        for letter in chosen:
            cell=cells.get((index,letter))
            if missing(cell):value=None
            elif cell.kind=='number':value=binary64(Decimal(cell.value),letter,index,cell.value)
            elif cell.kind in ('text','boolean','date','datetime'):value=cell.value
            else:raise StorageError('numeric_type','数据角色包含不支持的字段类型。',422)
            row[letter]=value
        rows.append(row)
    return rows

def validate_sheet_roles(sheet,selection):
    roles=getattr(selection,'data_roles',None)
    if roles is None:return
    endpoint=getattr(selection,'numeric_column',None) or getattr(selection,'outcome_column',None)
    if roles.endpoint and endpoint and roles.endpoint!=endpoint:raise StorageError('numeric_roles_missing','终点数据角色与分析终点不一致。',422)
    infer=selection.task_type!='descriptive_boxplot'
    if roles.structure=='paired_long' and infer and not (selection.task_type=='group_comparison' and selection.design=='paired'):
        raise StorageError('numeric_roles_missing','长表配对只能采用已支持的两时点配对方法。',422)
    validate_role_records(sheet_records(sheet,roles),roles,inference=infer)
