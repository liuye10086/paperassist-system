import { useI18n } from '../../shared/i18n'
import { formatMicroUsd, type CallReconciliation, type ReconciliationSummary } from './modelUsageTypes'

export function AccountedAmount({ amount }: { amount: number | undefined }) {
  const { t } = useI18n()
  return <>{amount === undefined ? t('暂不可用') : formatMicroUsd(amount)}</>
}

export function ReconciliationTotals({ summary }: { summary: ReconciliationSummary | undefined }) {
  const { t } = useI18n()
  if (!summary) return <p className="usage-scope-note">{t('实际核对数据暂不可用')}</p>
  const hasEvidence = summary.reconciled_count > 0 || summary.partial_count > 0
  return <div className="usage-reconciliation-summary">
    <dl className="usage-totals"><div><dt>{t('已核对部分合计')}</dt>
      <dd>{hasEvidence ? formatMicroUsd(summary.actual_micro_usd) : t('尚无已核对金额')}</dd></div>
      <div><dt>{t('全部已核对调用')}</dt><dd>{summary.reconciled_count}</dd></div>
      <div><dt>{t('部分已核对调用')}</dt><dd>{summary.partial_count}</dd></div>
      <div><dt>{t('实际待核对调用')}</dt><dd>{summary.pending_count}</dd></div></dl>
    <p className="usage-scope-note">{t('已核对部分合计仅含已确认分项；未知费用尚未计入，部分核对调用仍有费用待核对。')}</p>
    <p className="usage-scope-note">{t('部分核对仅记录已确认分项，不释放预留；全部核对后才按实际金额结算。')}</p>
  </div>
}

const labels: Record<CallReconciliation['status'], string> = {
  pending: '尚未核对', partial: '部分已核对', reconciled: '全部已核对', not_applicable: '不适用',
}
export function CallReconciliationDisplay({ reconciliation }: { reconciliation: CallReconciliation | undefined }) {
  const { t, locale } = useI18n()
  if (!reconciliation) return <span className="usage-unavailable">{t('暂不可用')}</span>
  if (reconciliation.status === 'not_applicable') return <span className="usage-reconciliation-status">{t('不适用')}</span>
  const amount = (value: number | null) => value === null ? t('待核对') : formatMicroUsd(value)
  return <div className="usage-reconciliation-call">
    <span className="usage-reconciliation-status">{t(labels[reconciliation.status])}</span>
    {reconciliation.actual_micro_usd !== null && <strong className="usage-actual-amount">{formatMicroUsd(reconciliation.actual_micro_usd)}</strong>}
    <small>{t('模型费用：{amount}', { amount: amount(reconciliation.token_micro_usd) })}</small>
    <small>{t('工具费用：{amount}', { amount: reconciliation.tool_applicable ? amount(reconciliation.tool_micro_usd) : t('不适用') })}</small>
    {reconciliation.reconciled_at !== null && <small className="usage-reconciled-time">{t('核对记录时间')}：<time dateTime={reconciliation.reconciled_at}>
      {new Date(reconciliation.reconciled_at).toLocaleString(locale)}</time></small>}
  </div>
}
