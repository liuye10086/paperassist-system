import { useEffect, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import { isIssuePage, profileBase, profileRequest } from './profileApi'
import { type IssueKind, type IssueItem, type IssuePage, type Profile } from './profileTypes'
import { issueLabels, typeLabels } from './profileLabels'
import LocationPreview from './LocationPreview'

export default function IssuePanel({ base, profile, kind, column }: { base: string; profile: Profile; kind: IssueKind; column: number | null }) {
 const { t } = useI18n(); const [page, setPage] = useState(1); const [result, setResult] = useState<IssuePage | null>(null); const [error, setError] = useState(false); const [attempt, setAttempt] = useState(0); const [item, setItem] = useState<IssueItem | null>(null)
 useEffect(() => {
  const controller = new AbortController(); let active = true
  const query = `kind=${kind}${column === null ? '' : `&column=${column}`}&page=${page}&page_size=20`
  profileRequest(`${profileBase(base, profile.source.dataset_id)}/profile/issues?${query}`, controller, (v): v is IssuePage => isIssuePage(v, profile.source, kind, column, page))
   .then(value => { if (active && !controller.signal.aborted) setResult(value) }).catch(() => { if (active) setError(true) })
  return () => { active = false; controller.abort() }
 }, [base, profile, kind, column, page, attempt])
 function change(next: number) { setResult(null); setItem(null); setError(false); setPage(next) }
 return <section className="profile-issues" aria-label={t('问题位置')}>
  <h4>{t(issueLabels[kind])}{column !== null && ` · ${profile.fields.find(f => f.column === column)?.letter}`}</h4>
  {kind === 'mixed_type' && <p>{t('类型组成列出本字段所有非缺失成员，不代表每个值有错误。')}</p>}
  {kind === 'outlier' && <><p>{t('异常候选使用 Q1 − 1.5 × IQR 与 Q3 + 1.5 × IQR 阈值。')}</p><p>{t('规则命中仅为异常候选，不代表数值有错误。')}</p></>}
  {kind === 'duplicate' && <p>{t('按首次出现行标识各重复组，列出全部成员，不删除记录。')}</p>}
  {error ? <p role="alert">{t('问题位置读取失败，请重试。')} <button type="button" onClick={() => { setError(false); setAttempt(n => n + 1) }}>{t('重试问题读取')}</button></p> : !result ? <p role="status">{t('正在读取问题位置……')}</p> : <>
   <p>{t('共 {total} 个位置；第 {page} 页，每页 20 条。', { total: result.total, page })}</p>
   {!result.items.length && <p>{t('当前没有此类问题位置。')}</p>}
   <ul className="profile-issue-list">{result.items.map((position, index) => <li key={`${position.row}:${position.column}`}>
    {position.group_first_row !== null && (index === 0 || result.items[index - 1].group_first_row !== position.group_first_row) && <span>{t('起始行 {row} · 共 {count} 行', { row: position.group_first_row, count: position.group_size! })}</span>}
    <button type="button" onClick={() => setItem(position)}>{position.coordinate ?? t('第 {row} 行', { row: position.row })}</button>
    {position.kind && <span>{t(typeLabels[position.kind] ?? '其他类型')} · {position.value === null ? t('空值') : typeof position.value === 'boolean' ? t(position.value ? '真' : '假') : position.value}</span>}
   </li>)}</ul>
   <div className="profile-actions"><button type="button" disabled={page <= 1} onClick={() => change(page - 1)}>{t('上一页问题')}</button><button type="button" disabled={page * 20 >= result.total} onClick={() => change(page + 1)}>{t('下一页问题')}</button></div>
  </>}
  {item && <LocationPreview key={`${item.row}:${item.column}`} base={base} profile={profile} item={item} />}
 </section>
}
