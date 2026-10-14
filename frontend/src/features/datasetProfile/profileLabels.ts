import type { IssueKind } from './profileTypes'
export const typeLabels: Record<string, string> = { blank: '空值', number: '数值', text: '文本', boolean: '布尔', date: '日期', datetime: '日期时间', time: '时刻', duration: '时长', formula: '公式', error: 'Excel 错误' }
export const issueLabels: Record<IssueKind, string> = { missing: '缺失值', outlier: '异常候选', mixed_type: '类型组成', formula: '公式位置', error: '错误值', time_candidate: '有效日期文本', time_invalid: '无效日期文本', time_ambiguous: '歧义日期文本', numeric_precision: '数值精度问题', duplicate: '重复行' }
