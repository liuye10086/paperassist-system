import { apiError, message } from '../../shared/i18n'
import type {AnalysisSelection} from '../analysis/analysisSelection'

export const numericIssues: Record<string, string> = Object.fromEntries([
  'numeric_input_limit', 'numeric_descriptive_limit', 'numeric_row_limit', 'numeric_effect_limit',
  'numeric_input_bytes_limit', 'numeric_output_limit', 'numeric_output_missing', 'numeric_output_invalid',
  'numeric_timeout_invalid', 'numeric_roles_missing', 'numeric_encoding', 'numeric_id_missing',
  'numeric_id_duplicate', 'numeric_invalid_input', 'numeric_sample_size', 'numeric_rank', 'numeric_constant',
  'numeric_perfect_fit', 'numeric_separation_check', 'numeric_separation', 'numeric_convergence',
  'numeric_unstable', 'numeric_overflow', 'numeric_timeout', 'numeric_failure',
].map(code => [code, apiError({ code }, '字段检查未通过，请修订字段后重审。')]))

const issues: Record<string, string> = {...numericIssues,
 comparison_sample_size:'比较有效记录不足，至少每组 3 条或 3 个完整对；Kruskal–Wallis 至少每组 5 条。',comparison_input_limit:'比较最多纳入 10,000 条记录或完整对、6 个组。',comparison_constant:'比较输入没有足够变化，无法计算可靠结果。',comparison_near_constant:'比较输入没有足够变化，无法计算可靠结果。',comparison_invalid_input:'请核对比较字段、数值类型和参与组。',pair_id_missing:'所有来源行的配对 ID 必须存在且唯一，包括缺测行。',pair_id_duplicate:'所有来源行的配对 ID 必须存在且唯一，包括缺测行。',pair_id_type:'请核对配对 ID 的数据类型；不自动合并不同类型。',groups_missing:'请核对比较字段、数值类型和参与组。',group_not_selected:'确认仅采用已选组；未选组排除并保留来源。',
 correlation_sample_size:'相关分析至少需要 3 条共同完整记录。',correlation_input_limit:'相关分析最多 10,000 条共同完整记录、10 个字段。',correlation_constant:'选定字段没有变化，无法计算可靠的相关系数。',correlation_near_constant:'选定字段变化过小，无法计算可靠的相关系数。',correlation_invalid_input:'相关字段或行结构无效，请核对整理数据。',
  unit_conflict: '声明单位与整理时确认的单位不同，请修订字段单位或重新整理；不会转换数值。',
  unit_unconfirmed: '单位未经核验；请明确保留未知，或确认当前标签仅为声明、不转换数值。',
  numeric_precision: '数值超出安全精度或可表示范围，请修订字段或重新整理。',
  outlier: 'IQR 范围外观测只是异常候选，仍参与计算，不自动剔除。',
  partial_metrics: '部分统计量超出可表示范围，将保留为无法计算。',
  numeric_type: '数值字段必须是实际数值；分组字段须为单一文本、数值或布尔类型，请修订选择或重新整理。',
  group_type: '数值字段必须是实际数值；分组字段须为单一文本、数值或布尔类型，请修订选择或重新整理。',
  no_complete_records: '选中字段没有完整有效记录，不能发布计划。',
  too_many_groups: '有效分组超过20个，请修订分类字段。',
  small_sample: '部分分组或全部数据不足2条完整记录，部分指标无法计算。',
  selected_missing: '明确采用所选字段的完整记录；缺失行排除，原整理数据保留。',
  invalid_column: '字段检查未通过，请修订字段后重审。',
  sheet_not_found: '字段检查未通过，请修订字段后重审。',
  invalid_analysis_selection: '字段检查未通过，请修订字段后重审。',
}
const limitations = new Set(['前提由用户声明，不证明独立性、因果或模型正确。','共同完整记录可能产生选择偏差；不插补、不删异常。',
 '研究设计及分布前提由用户确认，程序检查不能证明独立性、正态性或差值对称性。',
 '完整记录或完整对；不插补、不去重、不自动剔除异常候选。',
 '差值方向为第一组减第二组；配对为前测减后测。',
 '两两95%区间是普通区间，未作同时校正；全部预声明组对采用Holm校正。',
 '相关不代表因果；前提由用户声明，不是程序证明。','共同完整记录，不填补、不去重、不自动剔除异常值。','探索矩阵不做多重假设检验，不提供P值或星号。','双侧推断；小样本结果可能不稳定。',
  '数值最小值和最大值是观察范围，不是临床或业务合理范围。',
  '单位标签仅为声明，不转换数值，也不代表数据真实性已经核验。',
  '采用既有完整记录、binary64和IQR规则；不计算公式、不自动剔除异常候选，不生成研究方法或P值。',
  '存在合并单元格，覆盖格未自动补值。',
  '部分字段单位尚未确认；整理确认不代表数据真实性已核验。',
])
export function issueDescription(code: string, _serverMessage: string, selection?:AnalysisSelection): string {
  if(code==='small_sample'&&selection?.task_type==='group_comparison')return selection.design==='paired'?'不足 10 个完整对，小样本推断可能不稳定。':'至少一组不足 10 条完整观察，小样本推断可能不稳定。'
  if(code==='small_sample'&&selection?.task_type==='correlation')return '样本量较小，结果可能不稳定。'
  return issues[code] ?? '字段检查未通过，请修订字段后重审。'
}
export function resolutionDescription(code:string,resolution:string,selection?:AnalysisSelection):string {
  if(code==='small_sample'&&resolution==='accept_partial_metrics'&&selection?.task_type==='group_comparison')return '知悉小样本推断可能不稳定'
  if(code==='group_not_selected'&&resolution==='retain')return '确认仅纳入已选组'
  return ({exclude_selected_missing:'排除所选字段缺失行',retain:'保留观察到的异常值',accept_partial_metrics:'接受小样本的部分指标',unknown:'保持单位未知',declare_label:'声明单位标签，不转换数值'} as Record<string,string>)[resolution]??resolution
}
export function limitationDescription(value: string): string {
  if (limitations.has(value)) return value
  const prepared = /^分析使用已确认整理版本的 ([A-Z]+[1-9][0-9]*:[A-Z]+[1-9][0-9]*) 区域，保留区域内空行；普通小数采用 binary64，可能存在浮点误差。$/.exec(value)
  return prepared ? message('分析使用已确认整理版本的 {range} 区域，保留区域内空行；普通小数采用 binary64，可能存在浮点误差。', { range: prepared[1] }) : '还有未识别的数据检查限制，请重新读取分析计划。'
}
