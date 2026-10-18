"""Local-only frozen quality receipts for report provenance, never cloud material."""
from app.core.exceptions import StorageError
from app.domain.analysis_sources import prepared_dataset_source


def load_processing(store, project_id, source):
    if source.get('kind') != 'prepared_dataset_version' or source.get('schema_version') not in (2,3):
        return None
    from app.domain.dataset_preparation.service import DatasetPreparationService
    row, _, obj = DatasetPreparationService(store).load_version(project_id, source['file_id'], source['dataset_id'])
    if prepared_dataset_source(row, obj.parent_source.model_dump(), schema_version=obj.schema_version) != source:
        raise StorageError('source_conflict', '整理质量回执与报告来源不一致。', 409)
    processing=dict(schema_version=obj.schema_version, recipe=obj.recipe.model_dump(mode='json'), receipt=obj.summary.model_dump(mode='json'),
                manifest=obj.manifest.model_dump(mode='json'), base_source=obj.base_source.model_dump(mode='json'))
    if obj.schema_version==3:
        processing['operation']=obj.operation
        ancestors=[];parent=obj.base_source.model_dump(mode='json');seen={source['dataset_id']}
        while parent['schema_version'] in (2,3):
            if parent['dataset_id'] in seen:raise StorageError('source_conflict','整理版本链存在循环。',409)
            seen.add(parent['dataset_id'])
            _,_,previous=DatasetPreparationService(store).load_version(project_id,parent['file_id'],parent['dataset_id'])
            ancestors.append(dict(source=parent,operation=getattr(previous,'operation','quality'),recipe=previous.recipe.model_dump(mode='json'),
                receipt=previous.summary.model_dump(mode='json'),manifest=previous.manifest.model_dump(mode='json')))
            parent=previous.base_source.model_dump(mode='json')
        processing['ancestors']=ancestors
    return processing


def verify_processing(store, project_id, result, frozen):
    expected = load_processing(store, project_id, result.get('source', {}))
    if expected != frozen:
        raise StorageError('report_source_changed', '报告质量回执与冻结整理版本不一致。', 409)


def quality_lines(processing, language):
    """Bounded human summary; the complete receipt remains a downloadable asset."""
    en = language == 'en'
    def t(zh, english): return english if en else zh
    if not processing or processing.get('schema_version') not in (2,3):
        return [t('旧版本未记录此完整质量明细。', 'This older version did not record complete quality details.')]
    if processing.get('schema_version')==3:
        lines=derivation_lines(processing,language)
        for previous in reversed(processing.get('ancestors',[])):
            if previous['operation']=='population_filter':
                lines.append(t('继承的人群筛选（完整原回执保留）：','Inherited population filter (complete original receipt retained):'))
                lines.extend(derivation_lines({**previous,'schema_version':3},language))
        if processing.get('operation')=='population_filter':return lines
        return lines+quality_lines({**processing,'schema_version':2},language)
    receipt = processing['receipt']
    lines = []
    for key, zh, english in [
        ('root_record_count','原始选定区域记录数','Original selected records'),
        ('base_record_count','直接父版本保留记录数','Records retained in the direct parent'),
        ('retained_record_count','当前整理保留记录数','Records retained after preparation'),
        ('inherited_excluded_row_count','继承整理排除','Inherited preparation exclusions'),
        ('manual_excluded_row_count','本轮人工排除','Manual exclusions in this revision'),
        ('duplicate_excluded_row_count','本轮精确重复排除','Exact duplicate exclusions in this revision'),
        ('cumulative_excluded_row_count','累计整理排除','Cumulative preparation exclusions'),
        ('retained_changed_cell_count','最终保留数据变化单元格','Changed cells in retained data'),
        ('excluded_changed_cell_count','后来排除行上的变化单元格','Changed cells on subsequently excluded rows')]:
        lines.append(t(zh, english) + (': ' if en else '：') + str(receipt[key]))
    for key, zh, english in [('before_quality','处理前（直接父版本）','Before processing (direct parent)'),('after_quality','处理后（当前版本）','After processing (current version)')]:
        q = receipt[key]
        lines.append(t(zh, english) + ': ' + t(
            f'记录 {q["record_count"]}；缺失单元格 {q["missing_cell_count"]}；含缺失行 {q["missing_row_count"]}；空行 {q["blank_row_count"]}；重复组 {q["duplicate_group_count"]}；重复组成员 {q["duplicate_member_count"]}；额外重复行 {q["duplicate_extra_row_count"]}；异常候选 {q["outlier_candidate_count"]}。',
            f'Records {q["record_count"]}; missing cells {q["missing_cell_count"]}; rows with missing values {q["missing_row_count"]}; blank rows {q["blank_row_count"]}; duplicate groups {q["duplicate_group_count"]}; duplicate members {q["duplicate_member_count"]}; additional duplicate rows {q["duplicate_extra_row_count"]}; outlier candidates {q["outlier_candidate_count"]}.'))
    exact = processing['recipe']['duplicate_policy'] == 'exact'
    lines.append(t('批准的重复策略：全部字段类型敏感整行精确去重；保留手选排除后最早的有效源行。' if exact else '批准的重复策略：保留。',
                   'Approved duplicate policy: type-sensitive exact matching across every field; retain the earliest active source row after manual exclusions.' if exact else 'Approved duplicate policy: retain.'))
    lines.append(t('整理阶段不填补缺失，不按异常候选自动删行。统计阶段在当前保留记录中按本计划完整记录/完整对规则排除；不同计划的有效 n 可不同。',
                   'Preparation does not impute missing values or automatically remove outlier candidates. Analysis applies its own complete-case or complete-pair rule to retained records; effective n may differ by plan.'))
    reasons = list(dict.fromkeys(x['reason'] for x in processing['recipe']['manual_exclusions']))
    for reason in reasons[:20]:
        lines.append(t('人工排除理由（用户声明）：', 'Manual exclusion reason (user declaration): ') + reason)
    lines.append(t('正文最多显示前20种人工理由；完整影响明细、来源位置及继承回执可在应用中下载，未重新计算。',
                   'The body shows at most the first 20 distinct manual reasons. Download the complete frozen impacts, source locations and inherited receipts in the application.'))
    return lines


def append_quality(document, snapshot, language):
    if snapshot['result'].get('source', {}).get('schema_version') not in (2,3):
        return False
    processing = snapshot.get('processing')
    if not processing or processing.get('schema_version') not in (2,3):
        raise StorageError('report_source_changed', '新质量版本报告缺少冻结处理回执。', 409)
    from app.adapters.report_docx import paragraph
    for line in quality_lines(processing, language): paragraph(document, line)
    return True


def analysis_stage_text(text, result):
    if result.get('source', {}).get('schema_version') not in (2,3):
        return text
    for old in ('未插补、去重或剔除离群值', '未插补、去重或删除离群值'):
        text = text.replace(old, '统计阶段未新增插补、去重或自动剔除离群值；整理处理见冻结质量回执')
    text = text.replace('no imputation, deduplication or outlier removal',
                        'no additional imputation, deduplication or automatic outlier removal during statistical analysis; preparation is documented in the frozen quality receipt')
    text = text.replace('without imputation, deduplication or outlier removal',
                        'without additional imputation, deduplication or automatic outlier removal during statistical analysis; preparation is documented in the frozen quality receipt')
    return text


def retained_fact_labels(facts, result, language):
    """Keep the authorized fact keys and values; clarify their existing meaning."""
    if result.get('source', {}).get('schema_version') in (2,3):
        en = language == 'en'
        for key, zh, english in [('data.total', '整理后保留记录数', 'Records retained after preparation'),
                                 ('data.excluded', '本分析排除记录数', 'Records excluded by this analysis')]:
            if key in facts: facts[key]['label'] = english if en else zh


def derivation_lines(processing,language):
    from openpyxl.utils.cell import get_column_letter
    en=language=='en'
    def t(zh,english):return english if en else zh
    r=processing['receipt']
    lines=[]
    for key,zh,english in [('root_record_count','原始区域记录数','Original selected records'),('inherited_excluded_row_count','继承整理排除','Inherited preparation exclusions'),('base_record_count','本轮处理前有效记录数','Active records before this operation'),('retained_record_count','当前整理记录数','Current prepared records')]:
        lines.append(t(zh,english)+(': ' if en else '：')+str(r[key]))
    if processing.get('operation')=='population_filter':
        lines.append(t('本轮筛选不匹配排除：','Excluded as FALSE in this filter: ')+str(r['mismatch_excluded_row_count']))
        lines.append(t('本轮筛选缺失未决排除：','Excluded as UNKNOWN in this filter: ')+str(r['unknown_excluded_row_count']))
        lines.append(t('用户筛选理由：','User population rationale: ')+processing['recipe']['reason'])
        for c in processing['recipe']['conditions']:
            field=t('列 ','Column ')+get_column_letter(c['column'])
            def operand(value):
                if type(value) is bool:return ('TRUE' if value else 'FALSE')+t('（布尔）',' (boolean)')
                if c['kind']=='number':return value
                return '“'+value+'”'+t('（文本，精确匹配）',' (text, exact match)')
            op=c['operator']
            if op=='between':condition=field+t(' 在闭区间 [',' in inclusive interval [')+c['lower']+', '+c['upper']+']'
            elif op=='in':condition=field+t(' 属于集合 {',' in set {')+', '.join(operand(v) for v in c['values'])+'}'
            elif op=='is_missing':condition=field+t(' 为缺失',' is missing')
            elif op=='is_not_missing':condition=field+t(' 非缺失',' is not missing')
            else:condition=field+' '+{'eq':'=','ne':'≠','gt':'>','ge':'≥','lt':'<','le':'≤'}[op]+' '+operand(c['value'])
            lines.append(t('批准的人群条件（AND）：','Approved population condition (AND): ')+condition)
        lines.append(t('数值沿用字段已有单位；未知单位确认不代表单位转换。普通比较缺失为UNKNOWN，AND中FALSE优先。条件命中可重叠，不相加当总排除数。','Numeric thresholds use existing field units; acknowledgement of unknown units does not convert units. Missing ordinary comparisons are UNKNOWN; FALSE takes precedence in AND. Condition counts can overlap and must not be summed as exclusions.'))
    lines.append(t('完整回执及真实源坐标可在应用中下载核对。','Download the complete receipt and original source coordinates in the application for verification.'))
    lines.append(t('本分析仍按独立确认计划进行完整记录/完整对检查；方法有效n不等同人数。','This analysis applies complete-case/complete-pair checks under its independently confirmed plan; method-specific n is not a participant count.'))
    return lines
