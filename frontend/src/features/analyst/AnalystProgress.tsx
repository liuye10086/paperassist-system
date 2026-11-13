import { useEffect, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import useResearchDraft from '../research-results/useResearchDraft'
import { analystStatuses, type AnalystFeedback, type AnalystPublication, type AnalystWorkspace, type ProgressStatus } from './useAnalystWorkspace'
import './analystWorkspace.css'

export function AnalystFeedbackList({ feedback }: { feedback: AnalystFeedback[] }) {
  const { t, locale } = useI18n()
  return feedback.length ? <ul className="analyst-feedback-list">{feedback.map(item => <li key={item.id}>
    <p>{item.message}</p><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time>
  </li>)}</ul> : <p className="muted">{t('暂无客户反馈。')}</p>
}

export function AnalystPublications({ publications, headerAction }: { publications: AnalystPublication[]; headerAction?: ReactNode }) {
  const { t, locale } = useI18n()
  return <section className="analyst-card" aria-label={t('已发布的分析交付')}>
    <div className="analyst-card-heading"><h3>{t('已发布的分析交付')}</h3>{headerAction}</div>
    {!publications.length && <p className="muted">{t('暂无已发布交付。')}</p>}
    {publications.map(item => <article key={item.id} className="analyst-publication">
      <h4>{item.title}</h4><time dateTime={item.published_at}>{new Date(item.published_at).toLocaleString(locale)}</time>
      <AnalystFeedbackList feedback={item.feedback}/>
    </article>)}
  </section>
}

export function AnalystWorkspaceStatus({ workspace, showRefresh = true }: { workspace: AnalystWorkspace; showRefresh?: boolean }) {
  const { t } = useI18n()
  return <>
    {showRefresh && <button type="button" className="button-quiet" onClick={workspace.refresh} disabled={workspace.busy}>{t('刷新进度与反馈')}</button>}
    {workspace.busy && !workspace.value && <p role="status">{t('正在读取处理进度……')}</p>}
    {workspace.error && <p className="error-panel" role="alert">{t(workspace.error)}</p>}
    {workspace.notice && <p role="status">{t(workspace.notice)}</p>}
  </>
}

type ProgressDraft = { status: ProgressStatus; note: string }

type ProgressFormProps = { projectId: string; requirementId: string; workspace: AnalystWorkspace }

function ProgressForm({ projectId, requirementId, workspace, materialsOnly = false }: ProgressFormProps & { materialsOnly?: boolean }) {
  const { t } = useI18n()
  const value = workspace.value!
  const [draft, setDraft] = useResearchDraft<ProgressDraft | null>(projectId, `analyst-progress:${value.assignment_revision}:${requirementId}`, () => null)
  const synchronized = draft && draft.status === value.status && draft.note.trim() === (value.note ?? '')
  useEffect(() => {
    if (synchronized) setDraft(null)
  }, [setDraft, synchronized])
  const currentDraft = materialsOnly && draft?.status !== 'needs_materials' ? null : draft
  const status = materialsOnly || (currentDraft?.status ?? value.status) === 'needs_materials' ? 'needs_materials' : 'analyzing'
  const savedNote = materialsOnly && value.status !== 'needs_materials' ? null : value.note
  const note = currentDraft?.note ?? savedNote ?? ''
  return <form className="analyst-form" onSubmit={event => {
    event.preventDefault()
    if (!workspace.busy && (!materialsOnly || note.trim())) workspace.saveProgress(requirementId, status, note)
  }}>
    {!materialsOnly && <label>{t('更新进度')}<select value={status} disabled={workspace.busy} onChange={event => setDraft({ status: event.target.value as ProgressStatus, note })}>
      <option value="analyzing">{t(analystStatuses.analyzing)}</option>
      <option value="needs_materials">{t(analystStatuses.needs_materials)}</option>
    </select></label>}
    <label>{t('给客户的进度说明')}<textarea value={note} maxLength={4000} rows={materialsOnly ? 2 : 3} disabled={workspace.busy}
      placeholder={status === 'needs_materials' ? t('填写需要客户补交的文件或样本信息。') : undefined}
      onChange={event => setDraft({ status, note: event.target.value })}/></label>
    <button type="submit" className="button-primary" disabled={workspace.busy || (materialsOnly && !note.trim())}>{t(materialsOnly ? '标记待补材料' : '保存进度')}</button>
  </form>
}

export function AnalystMaterialsRequest({ projectId, workspace }: { projectId: string; workspace: AnalystWorkspace }) {
  const { t } = useI18n()
  const requirement = workspace.value?.requirement
  return <section className="analyst-material-request" aria-label={t('待补材料')} aria-busy={workspace.busy}>
    {requirement && <ProgressForm key={requirement.id} projectId={projectId} requirementId={requirement.id} workspace={workspace} materialsOnly/>}
    <AnalystWorkspaceStatus workspace={workspace} showRefresh={!workspace.value}/>
  </section>
}

export default function AnalystProgress({ projectId, workspace }: { projectId: string; workspace: AnalystWorkspace }) {
  const { t } = useI18n()
  const value = workspace.value
  return <>
    <section className="analyst-card" aria-label={t('处理进度')} aria-busy={workspace.busy}>
      <header className="analyst-card-heading"><h2>{t('处理进度')}</h2><AnalystWorkspaceStatus workspace={workspace}/></header>
      {value && <>
        <p><strong>{t(analystStatuses[value.status])}</strong></p>
        {value.note && <p className="analyst-note">{value.note}</p>}
        {value.requirement && value.status !== 'delivered' && <ProgressForm key={value.requirement.id}
          projectId={projectId} requirementId={value.requirement.id} workspace={workspace}/>}
      </>}
    </section>
    {value && <>
      <section className="analyst-card" aria-label={t('客户反馈')}><h3>{t('客户反馈')}</h3><AnalystFeedbackList feedback={value.feedback}/></section>
      <AnalystPublications publications={value.publications}/>
    </>}
  </>
}
