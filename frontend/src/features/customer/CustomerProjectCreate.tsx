import { useEffect, useRef, useState, type FormEvent } from 'react'
import { createArtifactSubmission, type ArtifactSubmission } from '../../shared/api/artifactSubmission'
import { safeError, useI18n } from '../../shared/i18n'
import ProjectCreateDialog from '../projects/ProjectCreateDialog'
import { isProject, type Project } from '../projects/projectTypes'
import { IntakeError, intakeRequest } from '../research-intake/api'
import useResearchDraft from '../research-results/useResearchDraft'

type Draft = { name: string; goal: string; submission: ArtifactSubmission | null }
const emptyDraft = (): Draft => ({ name: '', goal: '', submission: null })

export default function CustomerProjectCreate({ onCreated, onClose }: {
  onCreated: (project: Project) => void
  onClose: () => void
}) {
  const { t, locale } = useI18n()
  const [draft, setDraft] = useResearchDraft('new-project', 'customer-project-create', emptyDraft)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (request.current) return
    const name = draft.name.trim()
    const goal = draft.goal.trim()
    if (!name || !goal) {
      setError('请填写项目名称和研究目标。')
      return
    }
    const submission = draft.submission ?? createArtifactSubmission({
      name, research_topic: goal, project_type: 'research', delivery_kinds: ['analysis'], default_output_language: locale,
    })
    setDraft({ ...draft, submission })
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    try {
      const project = await intakeRequest<Project>('/api/v1/projects', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': submission.key },
        body: submission.body, signal: controller.signal,
      })
      if (controller.signal.aborted) return
      if (!isProject(project)) throw new Error('项目响应格式不正确，请刷新项目列表。')
      setDraft(emptyDraft())
      onCreated(project)
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof IntakeError && cause.status < 500 && cause.status !== 408) {
        setDraft({ ...draft, submission: null })
        setError(safeError(cause, '创建项目失败，请检查输入后重试。'))
      } else {
        setError('项目创建结果待确认，请重试原请求。')
      }
    } finally {
      request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <ProjectCreateDialog busy={busy} onClose={onClose}>
    <form onSubmit={event => void create(event)}>
      <div className="project-fields">
        <label>{t('项目名称')}<input required value={draft.name} maxLength={120} readOnly={!!draft.submission} disabled={busy}
          onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
        <label>{t('研究目标')}<textarea required value={draft.goal} maxLength={500} rows={3} readOnly={!!draft.submission} disabled={busy}
          onChange={event => setDraft({ ...draft, goal: event.target.value })} /></label>
      </div>
      {error && <p className="error-panel" role="alert">{t(error)}</p>}
      <div className="customer-actions">
        <button type="submit" className="button-primary" disabled={busy}>
          {t(busy ? '正在创建……' : draft.submission ? '重试创建项目' : '创建项目')}
        </button>
        <button type="button" className="button-quiet" onClick={onClose} disabled={busy}>{t('取消')}</button>
      </div>
    </form>
  </ProjectCreateDialog>
}
