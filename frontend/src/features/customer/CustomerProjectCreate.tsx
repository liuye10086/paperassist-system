import { useEffect, useRef, useState, type FormEvent } from 'react'
import { createArtifactSubmission, type ArtifactSubmission } from '../../shared/api/artifactSubmission'
import { safeError, useI18n } from '../../shared/i18n'
import ProjectCreateDialog from '../projects/ProjectCreateDialog'
import { customerProjectTypeNames, isProject, type Project } from '../projects/projectTypes'
import { IntakeError, intakeRequest } from '../research-intake/api'
import useResearchDraft from '../research-results/useResearchDraft'
import SciSettingsFields from './SciSettingsFields'
import ThesisBasicsFields from './ThesisBasicsFields'
import { prepareSciSettings, restoreSciSettingsDraft, type StoredSciSettingsDraft } from './sciProjectSettings'
import { prepareThesisBasics, thesisBasicsDraft, type ThesisBasicsDraft } from './thesisProjectRequirements'

type Draft = {
  name: string
  goal: string
  submission: ArtifactSubmission | null
  projectType?: Project['project_type']
  sci?: StoredSciSettingsDraft
  thesis?: ThesisBasicsDraft
}
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
  const projectType = draft.projectType ?? 'research'
  const sci = restoreSciSettingsDraft(draft.sci)
  const thesis = draft.thesis ?? thesisBasicsDraft()
  const locked = busy || !!draft.submission

  function change(update: Partial<Draft>) {
    setDraft(previous => ({ ...previous, ...update }))
    setError('')
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (request.current) return
    const name = draft.name.trim()
    const goal = draft.goal.trim()
    if (!name || !goal) {
      setError('请填写项目名称和研究目标。')
      return
    }
    let submission = draft.submission
    if (!submission) {
      const validated = projectType === 'sci' ? prepareSciSettings(sci) : null
      if (validated && 'error' in validated) { setError(validated.error); return }
      const thesisRequirements = projectType === 'thesis' ? prepareThesisBasics(thesis) : null
      if (thesisRequirements && 'error' in thesisRequirements) { setError(thesisRequirements.error); return }
      submission = createArtifactSubmission({
        name, research_topic: goal, project_type: projectType, default_output_language: thesisRequirements?.language ?? locale,
        ...(projectType === 'research' ? { delivery_kinds: ['analysis'] } : {}),
        ...(validated ? { sci_settings: validated.settings } : {}),
        ...(thesisRequirements ? { thesis_requirements: thesisRequirements.basics } : {}),
      })
    }
    setDraft({ ...draft, submission })
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    let checkingReceipt = !!draft.submission
    try {
      let project: Project | undefined
      if (checkingReceipt) {
        try {
          project = await intakeRequest<Project>(`/api/v1/project-create-requests/${encodeURIComponent(submission.key)}`, {
            signal: controller.signal,
          })
        } catch (cause) {
          if (!(cause instanceof IntakeError) || cause.status !== 404) throw cause
          checkingReceipt = false
        }
      }
      if (!checkingReceipt) project = await intakeRequest<Project>('/api/v1/projects', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': submission.key },
        body: submission.body, signal: controller.signal,
      })
      if (controller.signal.aborted) return
      if (!isProject(project) || project.project_type !== projectType) throw new Error('项目响应格式不正确，请刷新项目列表。')
      setDraft(emptyDraft())
      onCreated(project)
    } catch (cause) {
      if (controller.signal.aborted) return
      if (!checkingReceipt && cause instanceof IntakeError && cause.status < 500 && cause.status !== 408) {
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
    <form className="project-form customer-project-form" noValidate aria-busy={busy} onSubmit={event => void create(event)}>
      <div className="project-fields">
        <label>{t('项目类型')}<select value={projectType} disabled={locked}
          onChange={event => change({ projectType: event.target.value as Project['project_type'] })}>
          {Object.entries(customerProjectTypeNames).map(([value, label]) =>
            <option value={value} key={value}>{t(label)}</option>)}
        </select></label>
        <label>{t('项目名称')}<input required value={draft.name} maxLength={120} readOnly={!!draft.submission} disabled={busy}
          onChange={event => change({ name: event.target.value })} /></label>
        <label>{t('研究目标')}<textarea required value={draft.goal} maxLength={500} rows={3} readOnly={!!draft.submission} disabled={busy}
          onChange={event => change({ goal: event.target.value })} /></label>
      </div>
      {projectType === 'sci' && <SciSettingsFields draft={sci} disabled={locked} onChange={value => change({ sci: value })} onError={setError} />}
      {projectType === 'thesis' && <ThesisBasicsFields draft={thesis} disabled={locked} onChange={value => change({ thesis: value })} onError={setError} />}
      {error && <p className="error-panel" role="alert">{t(error)}</p>}
      <div className="project-form-actions">
        <button type="submit" className="button-primary" disabled={busy}>
          {t(busy ? '正在创建……' : draft.submission ? '重试创建项目' : '创建项目')}
        </button>
        <button type="button" onClick={onClose} disabled={busy}>{t('取消')}</button>
      </div>
    </form>
  </ProjectCreateDialog>
}
