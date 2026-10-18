"""Local checks from the existing scan/profile algorithms, without conversion."""
from fastapi import HTTPException
from openpyxl.utils.cell import column_index_from_string
from app.core.exceptions import StorageError
from app.domain.analysis import MAX_GROUPS
from app.domain.dataset_analysis import scan_dataset,kind_value,decimal_label
from app.domain.dataset_preparation.contracts import PreparedSheet
from app.domain.dataset_rows import source_rows
from app.domain.dataset_profile.scan import missing
from app.domain.analysis_plan.profile import PlanProfileScan as ProfileScan
from app.domain.analysis_plan.contracts import AnalysisPlanCheck, ResearchPlanCheck, ModernPlanCheck, RULES_VERSION
from app.domain.analysis_plan.research import missing_research, RESEARCH_RULES_VERSION


def build_check(sheet,selection,research_request=None,*,schema_version=None):
    if getattr(selection,'task_type',None) in ('regression','roc','survival'):
        from app.domain.regression.checks import build_check as build_modeling_check
        return build_modeling_check(sheet,selection,research_request)
    if getattr(selection,'task_type',None)=='group_comparison':
        from app.domain.comparison.checks import build_comparison_check
        return build_comparison_check(sheet,selection,research_request)
    if getattr(selection, "task_type", None)=="correlation":
        from app.domain.correlation.checks import build_correlation_check
        return build_correlation_check(sheet,selection,research_request)
    if not isinstance(sheet,PreparedSheet):
        raise StorageError('task_input_invalid','分析计划仅支持已确认整理数据。',422)
    chosen=[selection.numeric_column]+([selection.group_column] if selection.group_column else [])
    detailed=ProfileScan(sheet,selected_columns=chosen)
    issues=[]
    def issue(code,field,count,message,coordinates=(),resolution=None):
        issues.append(dict(id=code+':'+(field or 'all'),code=code,field=field,count=count,
            severity='warning' if resolution else 'blocking',message=message,
            coordinates=list(coordinates)[:5],allowed_resolutions=[resolution] if resolution else []))
    chosen=[selection.numeric_column]+([selection.group_column] if selection.group_column else [])
    fields=[]
    lookup={f['letter']:f for f in detailed.fields}
    for letter in dict.fromkeys(chosen):
        field=lookup.get(letter)
        if not field: continue
        numeric=field['numeric'] or {}
        unit=field['unit']
        label=selection.unit if letter==selection.numeric_column else unit['value'] or ''
        declaration=dict(status='label' if label else 'unknown',value=label or None)
        fields.append(dict(letter=letter,name=field['name'],type_counts=field['type_counts'],
            missing_count=field['missing_count'],non_missing_count=field['non_missing_count'],
            prepared_unit=unit,declared_unit=declaration,observed_min=numeric.get('min'),observed_max=numeric.get('max')))
        if letter==selection.numeric_column and unit['status']=='confirmed' and unit['value']!=selection.unit:
            issue('unit_conflict',letter,1,'声明单位与整理时确认的单位不同，请修订字段单位或重新整理；不会转换数值。')
        elif unit['status']=='unconfirmed':
            issue('unit_unconfirmed',letter,1,'单位未经核验；请明确保留未知，或确认当前标签仅为声明、不转换数值。',
                resolution='declare_label' if label else 'unknown')
        if letter==selection.numeric_column:
            for code,resolution,message in (
                ('numeric_precision',None,'数值超出安全精度或可表示范围，请修订字段或重新整理。'),
                ('outlier','retain','IQR 范围外观测只是异常候选，仍参与计算，不自动剔除。')):
                count,items=detailed.issues(code,field['column'],1)
                if count: issue(code,letter,count,message,[i['coordinate'] for i in items],resolution)
            if 'metric_unavailable' in numeric.get('warnings',[]):
                issue('partial_metrics',letter,field['non_missing_count'],'部分统计量超出可表示范围，将保留为无法计算。',resolution='accept_partial_metrics')
    check=None
    try:
        profile,scan=scan_dataset(sheet,selection,collect_values=True)
        check=scan.check(profile).model_dump(mode='json')
        columns={c.id:c for c in profile.columns}
        for letter,numeric in ((selection.numeric_column,True),(selection.group_column,False)):
            if letter is None: continue
            field=columns[letter]
            if not (field.can_be_numeric if numeric else field.can_be_group):
                issue('numeric_type' if numeric else 'group_type',letter,
                    field.non_missing_count-field.numeric_count if numeric else field.non_missing_count,
                    '数值字段必须是实际数值；分组字段须为单一文本、数值或布尔类型，请修订选择或重新整理。',field.issue_cells)
        if not scan.valid_count:
            issue('no_complete_records',None,0,'选中字段没有完整有效记录，不能发布计划。')
        if len(scan.groups)>MAX_GROUPS:
            numeric_cells=detailed.columns[column_index_from_string(selection.numeric_column)]
            group_cells=detailed.columns[column_index_from_string(selection.group_column)]
            groups=set()
            for row,cell in numeric_cells.items():
                if kind_value(cell)[0]!='number': continue
                kind,value=kind_value(group_cells.get(row))
                if kind in ('number','text','boolean'):
                    groups.add(decimal_label(value) if kind=='number' else value)
            issue('too_many_groups',selection.group_column,len(groups),'有效分组超过20个，请修订分类字段。')
        if scan.valid_count and (any(g['count']<2 for g in check['groups']) or not check['groups'] and scan.valid_count<2):
            issue('small_sample',None,scan.valid_count,'部分分组或全部数据不足2条完整记录，部分指标无法计算。',resolution='accept_partial_metrics')
        if check['excluded_count']:
            coordinates=[]
            missing_count=0
            for row in detailed.source_rows:
                row_missing=False
                for letter in chosen:
                    column=column_index_from_string(letter)
                    if missing(detailed.columns[column].get(row)):
                        row_missing=True
                        if len(coordinates)<5: coordinates.append(f'{letter}{row}')
                missing_count+=int(row_missing)
            if missing_count:
                issue('selected_missing',None,missing_count,'明确采用所选字段的完整记录；缺失行排除，原整理数据保留。',coordinates,'exclude_selected_missing')
    except HTTPException as exc:
        code=exc.detail.get('code','invalid_analysis_selection')
        if not any(i['code']==code for i in issues):
            issue(code,None,0,exc.detail.get('message','字段检查未通过，请修订字段后重审。'))
    model=ModernPlanCheck if schema_version==3 else ResearchPlanCheck if research_request is not None else AnalysisPlanCheck
    research=dict(research_missing=missing_research(research_request)) if research_request is not None else {}
    return model(rules_version='analysis_plan_rules_v3' if schema_version==3 else RESEARCH_RULES_VERSION if research_request is not None else RULES_VERSION,
        **research,data_range=sheet.data_range,row_count=sheet.row_count,
        selected_fields=fields,selection_check=check,issues=issues,limitations=[
            '数值最小值和最大值是观察范围，不是临床或业务合理范围。',
            '单位标签仅为声明，不转换数值，也不代表数据真实性已经核验。',
            '采用既有完整记录、binary64和IQR规则；不计算公式、不自动剔除异常候选，不生成研究方法或P值。',
            *([] if check is None else profile.warnings)]).model_dump(mode='json')


def validate_resolutions(check,resolutions):
    model=ModernPlanCheck if check.get('rules_version')=='analysis_plan_rules_v3' else ResearchPlanCheck if check.get('rules_version')==RESEARCH_RULES_VERSION else AnalysisPlanCheck
    check=model.model_validate(check,strict=True).model_dump(mode='json')
    if check.get('research_missing'):
        raise StorageError('task_input_invalid','研究资料仍不完整，请补充后重新检查。',422)
    if check['selection_check'] is None or not check['selection_check']['ready'] or any(i['severity']=='blocking' for i in check['issues']):
        raise StorageError('invalid_analysis_selection','仍有阻断问题，请修订字段或重新整理后再确认。',422)
    expected={i['id']:i for i in check['issues']}
    if set(resolutions)!=set(expected) or any(resolutions[key] not in issue['allowed_resolutions'] for key,issue in expected.items()):
        raise StorageError('task_input_invalid','请逐项明确处理当前计划的所有问题。',422)
