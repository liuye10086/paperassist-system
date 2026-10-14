import { message } from '../../shared/i18n'

const issues: Record<string, string> = {
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
const limitations = new Set([
  '数值最小值和最大值是观察范围，不是临床或业务合理范围。',
  '单位标签仅为声明，不转换数值，也不代表数据真实性已经核验。',
  '采用既有完整记录、binary64和IQR规则；不计算公式、不自动剔除异常候选，不生成研究方法或P值。',
  '存在合并单元格，覆盖格未自动补值。',
  '部分字段单位尚未确认；整理确认不代表数据真实性已核验。',
])
export function issueDescription(code: string, _serverMessage: string): string { return issues[code] ?? '字段检查未通过，请修订字段后重审。' }
export function limitationDescription(value: string): string {
  if (limitations.has(value)) return value
  const prepared = /^分析使用已确认整理版本的 ([A-Z]+[1-9][0-9]*:[A-Z]+[1-9][0-9]*) 区域，保留区域内空行；普通小数采用 binary64，可能存在浮点误差。$/.exec(value)
  return prepared ? message('分析使用已确认整理版本的 {range} 区域，保留区域内空行；普通小数采用 binary64，可能存在浮点误差。', { range: prepared[1] }) : '还有未识别的数据检查限制，请重新读取分析计划。'
}
