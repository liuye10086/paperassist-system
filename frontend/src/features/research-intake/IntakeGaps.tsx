import { useI18n } from '../../shared/i18n'
import type { Gap } from './contracts'

export default function IntakeGaps({ gaps }: { gaps: Gap[] }) {
  const { t } = useI18n()
  const grouped = new Map<string, { gap: Gap; count: number }>()
  for (const gap of gaps) {
    const key = `${gap.blocking}:${gap.message}`
    const current = grouped.get(key)
    if (current) current.count++
    else grouped.set(key, { gap, count: 1 })
  }
  if (!gaps.length) return null
  return <section className="intake-gaps" aria-label={t('待补充信息')}>
    <h3>{t('还有 {number} 项信息待补充，可先保存需求', { number: gaps.length })}</h3>
    <ul>{[...grouped.entries()].map(([key, { gap, count }]) => <li key={key}>
      <span>{t(gap.message)}{count > 1 && ` × ${count}`}</span>
      <small>{t(gap.blocking ? '执行相关模块前需补充' : '可稍后补充')}</small>
    </li>)}</ul>
  </section>
}
