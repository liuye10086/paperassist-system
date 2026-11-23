import {useEffect, useRef, useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError, useI18n} from '../../shared/i18n'
import {manuscriptBase} from '../manuscripts/manuscriptTypes'
import {findPaperDraft, isPaperDraftRejected, submitPaperDraftRevision} from '../manuscripts/submitPaperDraft'
import useResearchDraft from '../research-results/useResearchDraft'
import {taskRequest} from '../tasks/taskApi'
import './sciDraftRevision.css'

type Props = {projectId: string; manuscriptId: string; revision: number; requestId: string; thesis?: boolean;
  onCreated: (manuscriptId: string, revision: number, requestId: string) => void; onClose: () => void}
type Draft = {feedback: string; attemptKey?: string; createdId?: string}

export function SciDraftRevision(props: Props) {
  return <RevisionForm key={JSON.stringify([props.projectId, props.manuscriptId, props.revision, props.requestId])} {...props}/>
}

function RevisionForm({projectId, manuscriptId, revision, requestId, thesis, onCreated, onClose}: Props) {
  const {t} = useI18n()
  const [draft, setDraft] = useResearchDraft<Draft>(projectId, 'sci-revision:' + manuscriptId + ':' + requestId, () => ({feedback: ''}))
  const [consent, setConsent] = useState(false), [status, setStatus] = useState(''), [error, setError] = useState('')
  const pending = useRef<AbortController | null>(null)
  useEffect(() => {
    const abort = () => {pending.current?.abort(); pending.current = null; setStatus(''); setConsent(false)}
    const unsubscribe = onApiSessionChanged(abort)
    return () => {unsubscribe(); abort()}
  }, [])
  function edit(feedback: string) {
    setDraft({feedback}); setConsent(false); setError('')
  }
  async function upload(file: File) {
    if (pending.current || draft.attemptKey) return
    if (!/\.(docx|pdf|txt)$/i.test(file.name) || file.size > 10 * 1024 * 1024) {
      setError('请选择 10 MiB 以内的 Word、PDF 或 TXT 意见文件。'); return
    }
    const controller = new AbortController()
    pending.current = controller
    setStatus('正在读取意见文件……'); setError(''); setConsent(false)
    try {
      const form = new FormData()
      form.append('file', file)
      const url = manuscriptBase(projectId) + '/' + encodeURIComponent(manuscriptId) + '/writing-requests/' +
        encodeURIComponent(requestId) + '/draft-feedback'
      const data = await taskRequest(url, controller, (v): v is {text: string} => !!v && typeof v === 'object' &&
        'text' in v && typeof v.text === 'string' && !!v.text.trim(), '意见文件读取失败，请粘贴原文。', {method: 'POST', body: form})
      if (pending.current !== controller) return
      const combined = [draft.feedback.trimEnd(), data.text].filter(Boolean).join('\n\n')
      if (combined.length > 10000) {setError('意见超过一万字，请粘贴本次需要处理的内容。'); return}
      edit(combined)
    } catch (issue) {
      if (pending.current === controller) setError(safeError(issue, '意见文件读取失败，请粘贴原文。'))
    } finally {
      if (pending.current === controller) {pending.current = null; setStatus('')}
    }
  }
  async function submit(checkOnly = false) {
    if (pending.current || (!checkOnly && (!consent || !draft.feedback.trim()))) return
    const controller = new AbortController()
    pending.current = controller
    const attemptKey = draft.attemptKey ?? crypto.randomUUID()
    const feedback = draft.feedback.trim()
    const attempt = {projectId, manuscriptId, attemptKey, signal: controller.signal}
    setDraft({feedback, attemptKey}); setError(''); setConsent(false)
    setStatus(checkOnly ? '正在读取提交结果……' : '正在提交修改稿……')
    try {
      const result = checkOnly ? await findPaperDraft(attempt) :
        await submitPaperDraftRevision({...attempt, requestId, revision, feedback})
      controller.signal.throwIfAborted()
      if (!result || result.input.revision_of_request_id !== requestId || result.base_revision !== revision ||
          result.input.instructions !== feedback) {
        setError('尚未找到这次修改稿，可用原意见继续提交。'); return
      }
      setDraft({feedback, attemptKey, createdId: result.id})
      onCreated(manuscriptId, revision, result.id)
    } catch (issue) {
      if (controller.signal.aborted) return
      if (isPaperDraftRejected(issue)) setDraft({feedback})
      setError(safeError(issue, '修改稿提交结果待确认，请查看提交结果。'))
    } finally {
      if (pending.current === controller) {pending.current = null; setStatus('')}
    }
  }
  const title = t(thesis ? '按导师意见修改' : '按意见修改')
  return <section className="customer-section sci-draft-revision" aria-label={title}>
    <h2>{title}</h2>
    <fieldset disabled={!!status}><label>{t(thesis ? '导师意见' : '审稿意见')}<textarea rows={8} maxLength={10000}
      readOnly={!!draft.attemptKey} value={draft.feedback} onChange={event => edit(event.target.value)}/></label>
      {!draft.attemptKey && <label>{t('上传意见文件')}<input type="file" accept=".docx,.pdf,.txt"
        onChange={event => {const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload(file)}}/></label>}
      {!draft.createdId && <>
        <label className="sci-revision-consent"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)}/>
          {t(thesis ? '我同意将可修改章节的原文、所选来源和导师意见发给外部写作服务，接受服务商保存生成记录及本次写作费用。'
            : '我同意将原稿、所选来源和意见发给外部写作服务，接受服务商保存生成记录及本次写作费用。')}</label>
      </>}
      <div className="manuscript-actions">
      {!draft.createdId && <>
        <button type="button" className="button-primary" disabled={!consent || !draft.feedback.trim()}
          onClick={() => void submit()}>{t('生成修改稿')}</button>
        {draft.attemptKey && <button type="button" onClick={() => void submit(true)}>{t('查看提交结果')}</button>}
      </>}
      {draft.createdId && <>
        <button type="button" onClick={() => onCreated(manuscriptId, revision, draft.createdId!)}>{t('查看这次修改稿')}</button>
        <button type="button" onClick={() => edit('')}>{t('填写新意见')}</button>
      </>}
      <button type="button" onClick={onClose}>{t('返回正文')}</button>
      </div>
    </fieldset>
    {status && <p role="status">{t(status)}</p>}{error && <p role="alert">{t(error)}</p>}
  </section>
}
