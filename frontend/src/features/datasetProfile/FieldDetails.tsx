import { useI18n } from '../../shared/i18n'
import { type FieldProfile, type IssueKind } from './profileTypes'

import { issueLabels, typeLabels } from './profileLabels'
const warnings: Record<string, string> = { numeric_precision: '部分数值超出安全精度，请核对对应位置。', numeric_unavailable: '本列数值摘要不可用；其他字段概况仍可查看。', std_insufficient: '有效数值不足，样本标准差不可用。', metric_unavailable: '部分摘要指标无法安全计算，显示为未提供。' }
export default function FieldDetails({ field, onIssue }: { field: FieldProfile; onIssue: (kind: IssueKind, column: number) => void }) {
 const { t, locale } = useI18n(); const number = (v: number | null) => v === null ? t('未提供') : v.toLocaleString(locale, { maximumSignificantDigits: 8 })
 const numeric = field.numeric; const total = field.missing_count + field.non_missing_count
 const unit = field.unit.status === 'unconfirmed' ? t('未确认') : field.unit.value ? t('已确认：{unit}', { unit: field.unit.value }) : t('已确认无单位')
 return <div className="profile-field-detail">
  <h4>{field.letter} · {field.name}</h4><p>{t('非缺失 {count}；不同值 {distinct}；单位 {unit}', { count: field.non_missing_count, distinct: field.distinct_count, unit })}</p>
  <p>{total > 0 ? t('缺失 {missing} / {total}（{ratio}）', { missing: field.missing_count, total, ratio: new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 2 }).format(field.missing_count / total) }) : t('无记录，缺失比例不可计算。')}</p>
  <dl className="profile-metrics">{Object.entries(field.type_counts).map(([kind, n]) => <div key={kind}><dt>{t(typeLabels[kind] ?? '其他类型')}</dt><dd>{n}</dd></div>)}</dl>
  {numeric && <><h5>{t('数值摘要（仅实际数值）')}</h5><p>{t('实际数值 {count} 个；异常候选按 1.5 × IQR 标记。', { count: numeric.n })}</p>
   {numeric.status === 'unavailable' && <p className="warning-panel">{t(warnings.numeric_unavailable)}</p>}
   <dl className="profile-metrics">{([['mean', '均值'], ['std', '样本标准差'], ['min', '最小值'], ['max', '最大值'], ['q1', 'Q1'], ['median', '中位数'], ['q3', 'Q3'], ['iqr', 'IQR']] as const).map(([key, label]) => <div key={key}><dt>{t(label)}</dt><dd>{number(numeric[key])}</dd></div>)}</dl>
   <p>{t('异常候选阈值：小于 {lower} 或大于 {upper}', { lower: numeric.lower_fence ?? t('未提供'), upper: numeric.upper_fence ?? t('未提供') })}</p>
   {numeric.warnings.length > 0 && <ul className="warning-panel">{numeric.warnings.map(warning => <li key={warning}>{t(warnings[warning] ?? warnings.metric_unavailable)}</li>)}</ul>}
  </>}
  {field.categories && <><h5>{t('分类频数（文本与布尔）')}</h5><p>{t('分类不同值 {count} 个；显示前 10 项，其余 {other} 条记录。', { count: field.categories.distinct_count, other: field.categories.other_count })}</p>
   <ul className="profile-categories">{field.categories.top.map((item, index) => <li key={index}><span>{typeof item.value === 'boolean' ? t(item.value ? '真' : '假') : item.value}</span> · {t(typeLabels[item.kind])} · {item.count}</li>)}</ul></>}
  {field.temporal.length > 0 && <><h5>{t('时间摘要（按原类型分别统计）')}</h5><dl className="profile-temporal">{field.temporal.map(item => <div key={item.kind}><dt>{t(typeLabels[item.kind])} · {item.count}</dt><dd>{item.min} → {item.max}</dd></div>)}</dl></>}
  <p className="muted">{t('文本日期识别仅作提示，不改变原类型。')}</p><p>{t('有效日期文本 {valid}；无效 {invalid}；歧义 {ambiguous}', { valid: field.time_candidates.valid_count, invalid: field.time_candidates.invalid_count, ambiguous: field.time_candidates.ambiguous_count })}</p>
  {field.issue_counts.mixed_type > 0 && <p className="muted">{t('类型组成列出本字段所有非缺失成员，不代表每个值有错误。')}</p>}
  <div className="profile-actions">{Object.entries(field.issue_counts).filter(([, count]) => count > 0).map(([kind, count]) => <button type="button" key={kind} onClick={() => onIssue(kind as IssueKind, field.column)}>{t(issueLabels[kind as IssueKind])} · {count}</button>)}</div>
 </div>
}
