from decimal import Decimal
from openpyxl.utils.cell import column_index_from_string,get_column_letter
from app.core.exceptions import StorageError
from app.domain.dataset_profile.scan import missing
from app.domain.analysis_plan.profile import PlanProfileScan as ProfileScan
from app.domain.datasets.contracts import rectangle
from app.domain.dataset_rows import source_rows
from app.domain.dataset_analysis import binary64
from app.domain.comparison.contracts import GroupIdentity
from app.domain.regression.common import NumericError,payload

def missing_roles(selection):
    s=payload(selection);kind=s['task_type'];missing_fields=[]
    required={'regression':['outcome_column','covariates'],'roc':['outcome_column','score_column','positive','negative','direction','score_kind','score_source','score_version','formation','outcome_time'],'survival':['id_column','time_column','status_column','event','censored','time_unit','time_origin']}[kind]
    missing_fields.extend(k for k in required if not s.get(k))
    if not s['assumptions']['independent_units']:missing_fields.append('independent_units')
    if not s['assumptions']['inference_confirmed']:missing_fields.append('inference_confirmed')
    if kind=='regression':
        if s['method']=='logistic':missing_fields.extend(k for k in ['positive','negative'] if not s[k])
        for c in s['covariates']:
            if c['type']=='categorical':
                if len(c['levels'])<2:missing_fields.append('covariate_levels')
                if c['reference'] is None:missing_fields.append('covariate_reference')
    if kind=='roc' and s['evaluation_role'] in ('external_validation','held_out_validation') and not s['independence_confirmed']:missing_fields.append('independence_confirmed')
    if kind=='survival':
        if not s['noninformative_censoring']:missing_fields.append('noninformative_censoring')
        if s['group_column'] and not 2<=len(s['groups'])<=6:missing_fields.append('groups')
    return list(dict.fromkeys(missing_fields))

def selected_records(sheet,selection):
    s=payload(selection);kind=s['task_type']
    if missing_roles(selection):raise StorageError('numeric_roles_missing','分析角色或研究前提尚未完整。',422)
    if kind=='regression' and sum(1 if c['type']=='continuous' else len(c['levels'])-1 for c in s['covariates'])>20:raise StorageError('numeric_effect_limit','回归超过20个展开效应项。',422)
    module=__import__('app.domain.'+kind+'.contracts',fromlist=['selected_columns']);cols=module.selected_columns(selection)
    fields={get_column_letter(f.column):f for f in sheet.fields}
    if sheet.name!=s['sheet_name']:raise StorageError('sheet_not_found','工作表不一致。',422)
    if any(c not in fields for c in cols):raise StorageError('invalid_column','字段不存在。',422)
    start,end=rectangle(sheet.data_range)
    if end[0]-start[0]+1>10000:raise StorageError('numeric_row_limit','建模统计最多10000行。',422)
    cells={(c.row,c.column):c for c in sheet.cells};rows=[];included=[];excluded=[];ids=set();level_counts={c['column']:{str((l['kind'],l['value'])):0 for l in c['levels']} for c in s.get('covariates',[]) if c['type']=='categorical'}
    def identity(cell):
        try:return GroupIdentity(kind=cell.kind,value=('true' if cell.value else 'false') if cell.kind=='boolean' else cell.value).model_dump(mode='json')
        except Exception as exc:raise StorageError('numeric_encoding','非法类别身份。',422) from exc
    def number(cell,c,row):
        if cell.kind!='number':raise StorageError('numeric_type',f'{c}{row}须为实际数值。',422)
        try:return binary64(Decimal(cell.value),c,row,cell.value)
        except Exception as exc:raise StorageError('numeric_precision',f'{c}{row}数值非法。',422) from exc
    for row in source_rows(sheet):
        values={c:cells.get((row,column_index_from_string(c))) for c in cols};absent=[f'{c}{row}' for c,v in values.items() if missing(v)]
        # Validate every nonmissing numeric/encoding cell even in incomplete records.
        parsed={}
        for c,v in values.items():
            if missing(v):continue
            numeric=(kind=='regression' and (s['method']=='ols' and c==s['outcome_column'] or any(x['column']==c and x['type']=='continuous' for x in s['covariates'])) or kind=='roc' and c==s['score_column'] or kind=='survival' and c==s['time_column'])
            parsed[c]=number(v,c,row) if numeric else identity(v)
        if kind=='regression':
            if s['method']=='logistic' and s['outcome_column'] in parsed and parsed[s['outcome_column']] not in [s['positive'],s['negative']]:raise StorageError('numeric_encoding','未知二元结局编码。',422)
            for c in s['covariates']:
                if c['type']=='categorical' and c['column'] in parsed and parsed[c['column']] not in c['levels']:raise StorageError('numeric_encoding','协变量出现未冻结水平。',422)
        if kind=='roc':
            if s['outcome_column'] in parsed and parsed[s['outcome_column']] not in [s['positive'],s['negative']]:raise StorageError('numeric_encoding','未知结局编码。',422)
            if s['score_kind']=='probability' and s['score_column'] in parsed and not 0<=parsed[s['score_column']]<=1:raise StorageError('numeric_invalid_input','概率超出[0,1]。',422)
        if kind=='survival':
            if s['status_column'] in parsed and parsed[s['status_column']] not in [s['event'],s['censored']]:raise StorageError('numeric_encoding','未知事件编码。',422)
            if s['time_column'] in parsed and parsed[s['time_column']]<0:raise StorageError('numeric_invalid_input','随访时间为负。',422)
        id_column=s.get('id_column')
        if id_column:
            if id_column not in parsed:raise StorageError('numeric_id_missing','主体ID不能缺失。',422)
            key=(parsed[id_column]['kind'],parsed[id_column]['value'])
            if key in ids:raise StorageError('numeric_id_duplicate','主体ID必须唯一。',422)
            ids.add(key)
        if absent:excluded.append(dict(row=row,coordinates=absent,reason='selected_missing'));continue
        if kind=='regression':
            x=[]
            for c in s['covariates']:
                value=parsed[c['column']]
                if c['type']=='continuous':x.append(value)
                else:
                    level_counts[c['column']][str((value['kind'],value['value']))]+=1
                    x.extend(float(value==level) for level in c['levels'] if level!=c['reference'])
            y=parsed[s['outcome_column']] if s['method']=='ols' else float(parsed[s['outcome_column']]==s['positive'])
            rows.append(dict(y=y,x=x,row=row))
        elif kind=='roc':rows.append(dict(outcome=int(parsed[s['outcome_column']]==s['positive']),score=parsed[s['score_column']],row=row))
        else:
            group=parsed[s['group_column']] if s['group_column'] else None
            if group is not None and group not in s['groups']:excluded.append(dict(row=row,coordinates=[f"{s['group_column']}{row}"],reason='group_not_selected'));continue
            rows.append(dict(time=parsed[s['time_column']],event=parsed[s['status_column']]==s['event'],group=s['groups'].index(group) if group is not None else 0,row=row))
        included.append(row)
    if any(not count for levels in level_counts.values() for count in levels.values()):raise StorageError('numeric_encoding','完整记录筛选后冻结分类水平消失。',422)
    units={c['column']:c['unit'] for c in s.get('covariates',[])}
    if kind=='regression':units[s['outcome_column']]=s['outcome_unit']
    if kind=='survival':units[s['time_column']]=s['time_unit']
    variables=[dict(column=c,name=fields[c].name,unit=units.get(c,'')) for c in cols]
    return rows,variables,dict(included_rows=included,excluded_rows=excluded,missing_policy='complete_cases',encoding_counts=level_counts)

def build_check(sheet,selection,research):
    from app.domain.analysis_plan.contracts import ModernPlanCheck
    from app.domain.analysis_plan.research import missing_research
    from app.domain.regression.bounded import compute_bounded
    s=payload(selection);module=__import__('app.domain.'+s['task_type']+'.contracts',fromlist=['selected_columns']);profile=ProfileScan(sheet,selected_columns=module.selected_columns(selection));selected=[];issues=[];missing_fields=missing_roles(selection)+missing_research(research);n=excluded_count=0
    if research['observation_structure']!='independent' and 'observation_structure' not in missing_fields:missing_fields.append('observation_structure')
    units={c['column']:c['unit'] for c in s.get('covariates',[])}
    if s['task_type']=='regression' and s['outcome_column']:units[s['outcome_column']]=s['outcome_unit']
    if s['task_type']=='survival' and s['time_column']:units[s['time_column']]=s['time_unit']
    def issue(code,message,count=1,coords=(),resolution=None,field=None):issues.append(dict(id=code+':'+(field or 'all'),code=code,field=field,count=count,severity='warning' if resolution else 'blocking',message=message,coordinates=list(coords)[:5],allowed_resolutions=[resolution] if resolution else []))
    for f in profile.fields:
        if f['letter'] not in module.selected_columns(selection):continue
        label=units.get(f['letter'],'');numeric=f['numeric'] or {}
        selected.append(dict(letter=f['letter'],name=f['name'],type_counts=f['type_counts'],missing_count=f['missing_count'],non_missing_count=f['non_missing_count'],prepared_unit=f['unit'],declared_unit=dict(status='label' if label else 'unknown',value=label or None),observed_min=numeric.get('min'),observed_max=numeric.get('max')))
        if f['letter'] in units and f['unit']['status']=='confirmed' and f['unit']['value']!=label:issue('unit_conflict','所声明单位与整理单位不同。',field=f['letter'])
        elif f['letter'] in units and f['unit']['status']=='unconfirmed':issue('unit_unconfirmed','声明单位仅为标签，不转换数值。',resolution='declare_label' if label else 'unknown',field=f['letter'])
    if not missing_fields:
        try:
            rows,_,audit=selected_records(sheet,selection);n=len(rows);excluded_count=len(audit['excluded_rows']);compute_bounded(s['task_type'],rows,s)
            for reason,resolution,message in [('selected_missing','exclude_selected_missing','完整记录缺失排除保留来源审计。'),('group_not_selected','retain','非参与组排除；不会作为缺失记录。')]:
                excluded=[r for r in audit['excluded_rows'] if r['reason']==reason]
                if excluded:issue(reason,message,len(excluded),[c for r in excluded for c in r['coordinates']],resolution)
        except (StorageError,NumericError) as exc:issue(exc.code,getattr(exc,'message',str(exc)))
    check=dict(ready=not missing_fields and not any(i['severity']=='blocking' for i in issues),row_count=sheet.row_count,valid_count=n,excluded_count=excluded_count,groups=[],issues=[i['message'] for i in issues if i['severity']=='blocking'],warnings=[i['message'] for i in issues if i['severity']=='warning'])
    return ModernPlanCheck(rules_version='analysis_plan_rules_v3',data_range=sheet.data_range,row_count=sheet.row_count,selected_fields=selected,selection_check=check,issues=issues,research_missing=list(dict.fromkeys(missing_fields)),limitations=['前提由用户声明，不证明独立性、因果或模型正确。',('当前整理保留行的共同完整记录可能产生选择偏差；统计阶段不新增插补或自动删异常。' if getattr(sheet,'active_source_rows',None) is not None else '共同完整记录可能产生选择偏差；不插补、不删异常。')]).model_dump(mode='json')
build_regression_check=build_check
