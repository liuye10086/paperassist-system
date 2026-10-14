import { useEffect, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import SourceSummary from '../analysis/SourceSummary'
import { isProfile, profileBase, profileRequest } from './profileApi'
import { type IssueKind, type Profile, type ProfileBinding } from './profileTypes'
import FieldDetails from './FieldDetails'
import IssuePanel from './IssuePanel'
import './profile.css'

// Key the entire response/selection tree by all source identity metadata. This also
// clears visible state synchronously before effects run on a version change.
export default function DatasetProfile(props: { base: string; binding: ProfileBinding }) {
 return <BoundProfile key={`${props.base}:${JSON.stringify(props.binding)}`} {...props} />
}
function BoundProfile({ base, binding }: { base: string; binding: ProfileBinding }) {
 const [selectedBinding] = useState(binding)
 const { t } = useI18n(); const [profile, setProfile] = useState<Profile | null>(null); const [error, setError] = useState(false); const [attempt, setAttempt] = useState(0); const [fieldColumn, setFieldColumn] = useState<number | null>(null); const [issue, setIssue] = useState<{ kind: IssueKind; column: number | null } | null>(null)
 useEffect(() => {
  const controller = new AbortController(); let active = true
  profileRequest(`${profileBase(base, selectedBinding.dataset_id)}/profile`, controller, (v): v is Profile => isProfile(v, selectedBinding))
   .then(value => { if (active && !controller.signal.aborted) setProfile(value) }).catch(() => { if (active) setError(true) })
  return () => { active = false; controller.abort() }
 }, [base, selectedBinding, attempt])
 if (error) return <div className="dataset-profile error-panel" role="alert">{t('数据概况读取失败，请重试。')} <button type="button" onClick={() => { setError(false); setAttempt(n => n + 1) }}>{t('重试概况')}</button></div>
 if (!profile) return <p className="dataset-profile" role="status">{t('正在读取字段详细概况……')}</p>
 const field = profile.fields.find(f => f.column === fieldColumn)
 return <section className="dataset-profile" aria-label={t('字段详细概况')}>
  <h3>{t('字段详细概况')}</h3><SourceSummary filename={profile.filename} source={profile.source} />
  <p>{t('数据区域 {range}；记录 {count} 行；空行 {blank} 行。', { range: profile.data_range ?? t('无数据区域'), count: profile.record_count, blank: profile.blank_row_count })}</p>
  <p>{t('重复 {groups} 组；涉及 {rows} 行；除首条外 {extra} 行。', { groups: profile.duplicate_groups, rows: profile.duplicate_rows, extra: profile.duplicate_extra_rows })}</p>
  {profile.duplicate_rows > 0 && <button type="button" onClick={() => setIssue({ kind: 'duplicate', column: null })}>{t('查看重复行')}</button>}
  <p className="muted">{t('选择字段展开详细概况，点击问题坐标核对当前版本。')}</p>
  <div className="profile-field-picker">{profile.fields.map(f => <button type="button" key={f.column} aria-expanded={fieldColumn === f.column} onClick={() => { setFieldColumn(fieldColumn === f.column ? null : f.column); setIssue(null) }}>{f.letter} · {f.name}</button>)}</div>
  {field && <FieldDetails field={field} onIssue={(kind, column) => setIssue({ kind, column })} />}
  {issue && <IssuePanel key={`${issue.kind}:${issue.column}`} base={base} profile={profile} {...issue} />}
 </section>
}
