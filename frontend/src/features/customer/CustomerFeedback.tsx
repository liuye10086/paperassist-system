import { useEffect, useRef, useState, type FormEvent } from 'react'
import { createArtifactSubmission, type ArtifactSubmission } from '../../shared/api/artifactSubmission'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { IntakeError, intakeRequest } from '../research-intake/api'
import useResearchDraft from '../research-results/useResearchDraft'
import { customerBase, type Feedback } from './customerWorkspaceApi'

type Draft = { message: string; submission: ArtifactSubmission | null }
const emptyDraft = (): Draft => ({ message: '', submission: null })

export default function CustomerFeedback({ projectId, snapshotId, entries, onSaved, registerLeaveGuard }: {
  projectId: string
  snapshotId?: string
  entries: Feedback[]
  onSaved: () => void
  registerLeaveGuard?: RegisterLeaveGuard
}) {
  const { t, locale } = useI18n()
  const [draft, setDraft] = useResearchDraft(projectId, `customer-feedback:${snapshotId ?? 'project'}`, emptyDraft)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  useDraftLeaveGuard(registerLeaveGuard, !!draft.message.trim(), busy)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (request.current || !draft.message.trim()) return
    const submission = draft.submission ?? createArtifactSubmission({ message: draft.message.trim(), snapshot_id: snapshotId ?? null })
    setDraft({ ...draft, submission })
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setSaved(false)
    setError('')
    try {
      const result = await intakeRequest<Feedback>(customerBase(projectId) + '/feedback', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': submission.key },
        body: submission.body, signal: controller.signal,
      })
      if (controller.signal.aborted) return
      if (!result?.id || typeof result.message !== 'string' || !Number.isFinite(Date.parse(result.created_at))) {
        throw new Error('Invalid feedback receipt')
      }
      setDraft(emptyDraft())
      setSaved(true)
      onSaved()
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof IntakeError && cause.status < 500 && cause.status !== 408) {
        setDraft({ ...draft, submission: null })
        setError(safeError(cause, '反馈发送失败，请重试。'))
      } else {
        setError('反馈发送结果待确认，请重试原请求。')
      }
    } finally {
      request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <section className="customer-feedback" aria-label={t('反馈')}>
    <h3>{t('反馈')}</h3>
    <form onSubmit={event => void submit(event)}>
      <label>{t('反馈内容')}
        <textarea rows={3} maxLength={4000} required value={draft.message} readOnly={!!draft.submission}
          disabled={busy} onChange={event => { setDraft({ message: event.target.value, submission: null }); setSaved(false) }} />
      </label>
      <button type="submit" className="button-primary" disabled={busy || !draft.message.trim()}>
        {t(busy ? '正在发送……' : draft.submission ? '重试发送反馈' : '发送反馈')}
      </button>
    </form>
    {saved && <p role="status">{t('反馈已发送。')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {entries.length > 0 && <ul className="customer-feedback-history" aria-label={t('反馈记录')}>
      {entries.map(entry => <li key={entry.id}><time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString(locale)}</time>
        <p>{entry.message}</p></li>)}
    </ul>}
  </section>
}
