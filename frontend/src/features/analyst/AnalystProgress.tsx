import { useState } from 'react'
import { useI18n } from '../../shared/i18n'
import { analystStatuses, type AnalystFeedback, type AnalystPublication, type AnalystWorkspace, type ProgressStatus } from './useAnalystWorkspace'
import './analystWorkspace.css'

export function AnalystFeedbackList({ feedback }: { feedback: AnalystFeedback[] }) {
  const { t, locale } = useI18n()
  return feedback.length ? <ul className="analyst-feedback-list">{feedback.map(item => <li key={item.id}>
    <p>{item.message}</p><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time>
  </li>)}</ul> : <p className="muted">{t('暂无客户反馈。')}</p>
}

export function AnalystPublications({ publications }: { publications: AnalystPublication[] }) {
  const { t, locale } = useI18n()
  return <section className="analyst-card" aria-label={t('已发布的分析交付')}>
    <h3>{t('已发布的分析交付')}</h3>
    {!publications.length && <p className="muted">{t('暂无已发布交付。')}</p>}
    {publications.map(item => <article key={item.id} className="analyst-publication">
      <h4>{item.title}</h4><time dateTime={item.published_at}>{new Date(item.published_at).toLocaleString(locale)}</time>
      <AnalystFeedbackList feedback={item.feedback}/>
    </article>)}
  </section>
}

export function AnalystWorkspaceStatus({ workspace }: { workspace: AnalystWorkspace }) {
  const { t } = useI18n()
  return <>
    <button type="button" className="button-quiet" onClick={workspace.refresh} disabled={workspace.busy}>{t('刷新进度与反馈')}</button>
    {workspace.busy && !workspace.value && <p role="status">{t('正在读取处理进度……')}</p>}
    {workspace.error && <p className="error-panel" role="alert">{t(workspace.error)}</p>}
    {workspace.notice && <p role="status">{t(workspace.notice)}</p>}
  </>
}

function ProgressForm({ workspace }: { workspace: AnalystWorkspace }) {
  const { t } = useI18n()
  const value = workspace.value!
  const [status, setStatus] = useState<ProgressStatus>(value.status === 'needs_materials' ? 'needs_materials' : 'analyzing')
  const [note, setNote] = useState(value.note ?? '')
  return <form className="analyst-form" onSubmit={event => {
    event.preventDefault()
    if (!workspace.busy && value.requirement) workspace.saveProgress(value.requirement.id, status, note)
  }}>
    <label>{t('更新进度')}<select value={status} disabled={workspace.busy} onChange={event => setStatus(event.target.value as ProgressStatus)}>
      <option value="analyzing">{t(analystStatuses.analyzing)}</option>
      <option value="needs_materials">{t(analystStatuses.needs_materials)}</option>
    </select></label>
    <label>{t('给客户的进度说明')}<textarea value={note} maxLength={4000} rows={3} disabled={workspace.busy} onChange={event => setNote(event.target.value)}/></label>
    <button type="submit" className="button-primary" disabled={workspace.busy}>{t('保存进度')}</button>
  </form>
}

export default function AnalystProgress({ workspace }: { workspace: AnalystWorkspace }) {
  const { t } = useI18n()
  const value = workspace.value
  return <>
    <section className="analyst-card" aria-label={t('处理进度')} aria-busy={workspace.busy}>
      <header className="analyst-card-heading"><h2>{t('处理进度')}</h2><AnalystWorkspaceStatus workspace={workspace}/></header>
      {value && <>
        <p><strong>{t(analystStatuses[value.status])}</strong>{value.requirement && <> · {t('需求版本 {version}', { version: value.requirement.version })}</>}</p>
        {value.note && <p className="analyst-note">{value.note}</p>}
        {value.requirement && value.status !== 'delivered' && <ProgressForm key={value.requirement.id} workspace={workspace}/>}
      </>}
    </section>
    {value && <>
      <section className="analyst-card" aria-label={t('客户反馈')}><h3>{t('客户反馈')}</h3><AnalystFeedbackList feedback={value.feedback}/></section>
      <AnalystPublications publications={value.publications}/>
    </>}
  </>
}
