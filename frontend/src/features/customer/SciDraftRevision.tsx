import {Fragment, useCallback, useEffect, useRef, useState, type UIEvent} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError, useI18n} from '../../shared/i18n'
import {manuscriptBase} from '../manuscripts/manuscriptTypes'
import {findPaperDraft, isPaperDraftRejected, matchesDraftRevisionScope, submitPaperDraftRevision} from '../manuscripts/submitPaperDraft'
import {WorkspaceIcon} from '../projects/WorkspaceShell'
import useResearchDraft from '../research-results/useResearchDraft'
import {taskRequest} from '../tasks/taskApi'
import {SciDraftChanges, SciDraftProgress, SciDraftView, SciDraftWordDownload} from './SciDraftReader'
import {resolveDraftChat, type DraftChatKind} from './sciDraftChatIntent'
import {useSciDraftRead, type DraftChange, type DraftRead, type DraftRequest} from './useSciDraftRead'
import './sciDraftRevision.css'

type Props = DraftRequest & {thesis?: boolean; onAdjustSources?: () => void}
type Turn = {requestId: string; feedback: string; sectionIds?: string[]; kind?: DraftChatKind; advice?: string}
type Scope = {kind: 'sections'; ids: string[]} | {kind: 'file'}
type Draft = {feedback: string; attemptKey?: string; createdId?: string; history?: Turn[]; scope?: Scope; submittedSections?: string[];
  submittedKind?: DraftChatKind; submittedInstructions?: string}
type Reply = {changes: DraftChange[]; advice?: string}

export function SciDraftRevision(props: Props) {
  return <RevisionForm key={JSON.stringify([props.projectId, props.manuscriptId, props.revision, props.requestId])} {...props}/>
}

function RevisionReply({changes, advice}: Reply) {
  const {t} = useI18n()
  if (advice !== undefined) return <p className="sci-revision-reply sci-revision-advice">{advice}</p>
  return <div className="sci-revision-reply sci-revision-comparison">
    <p>{t('修改稿已生成。')}</p>
    <SciDraftChanges changes={changes}/>
  </div>
}

function ArchivedRevisionReply({request, initial}: {request: DraftRequest; initial?: Reply}) {
  const [cached] = useState(() => initial && {changes:initial.changes, advice:initial.advice})
  const read = useSciDraftRead(request, !cached, true)
  const reply = cached ?? (read.data?.status === 'succeeded' ? read.data : null)
  return reply ? <RevisionReply {...reply}/>
    : <SciDraftProgress {...request} read={read} reply/>
}

function RevisionForm({projectId, manuscriptId, revision, requestId, thesis, onAdjustSources}: Props) {
  const {locale, t} = useI18n()
  const [draft, setDraft] = useResearchDraft<Draft>(projectId, 'sci-revision:' + manuscriptId + ':' + requestId, () => ({feedback: ''}))
  const [status, setStatus] = useState(''), [error, setError] = useState('')
  const [retained, setRetained] = useState<DraftRead | null>(null)
  const [readingSection, setReadingSection] = useState<string>()
  const pending = useRef<AbortController | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const log = useRef<HTMLDivElement>(null)
  const followingLog = useRef(true)
  const previous = draft.history?.at(-1)
  const sourceId = draft.history?.slice().reverse().find(turn => turn.kind !== 'advice')?.requestId ?? requestId
  const sourceRequest = {projectId, manuscriptId, revision, requestId: sourceId}
  const revisionRequest = {...sourceRequest, requestId: draft.createdId ?? ''}
  const source = useSciDraftRead(sourceRequest, true, true)
  const sentAdvice = draft.submittedKind === 'advice'
  const submitted = useSciDraftRead(revisionRequest, !!draft.createdId, true, draft.submittedSections?.length ? 1000 : 3000)
  const result = submitted.data && (submitted.data.previous_request_id !== sourceId || Boolean(submitted.data.draft_advice) !== sentAdvice)
    ? {...submitted, data:null, error:'指定初稿暂时无法读取。'} : submitted
  const completed = result.data?.status === 'succeeded' ? result.data : null
  const revised = completed && !completed.draft_advice
  const retainedSource = source.valid && !source.data && !source.error && retained?.data?.request_id === sourceId ? retained : null
  const visible = revised ? result : retainedSource ?? source
  const visibleRequest = revised ? revisionRequest : sourceRequest
  const writable = visible.data?.status === 'succeeded' && visible.data.can_revise && (!draft.createdId || !!completed)
  const awaitingReceipt = !!draft.attemptKey && !draft.createdId
  const feedback = completed ? '' : draft.feedback
  const editableIds = new Set(visible.data?.editable_section_ids)
  const editable = visible.data?.draft?.sections.filter(section => editableIds.has(section.id)) ?? []
  const active = editableIds.has(readingSection ?? '') ? readingSection : editable[0]?.id
  const scope = completed && draft.scope?.kind === 'file' ? undefined : draft.scope
  const choosing = scope?.kind === 'sections'
  const locked = !!draft.attemptKey && !completed
  const scopeDisabled = !writable || locked || !!status
  const selected = scope?.kind === 'file' ? editable.map(section => section.id)
    : scope?.kind === 'sections' ? editable.filter(section => scope.ids.includes(section.id)).map(section => section.id)
      : undefined
  const intent = resolveDraftChat(feedback, editable, {selected, active, previous:previous?.sectionIds ?? source.data?.target_sections,
    fromFile:scope?.kind === 'file', thesis})
  const selection = intent.sectionIds
  const targets = new Set(locked ? draft.submittedSections : selection)
  function sectionLabel(sectionIds: ReadonlySet<string>) {
    return editable.filter(section => sectionIds.has(section.id)).map(section => section.heading).join(locale === 'en' ? ', ' : '、')
  }
  const sentScope = draft.scope?.kind === 'file' ? t('全文')
    : draft.submittedSections?.length ? sectionLabel(new Set(draft.submittedSections)) : ''
  const scopeLabel = scope?.kind === 'file' ? t('全文（按意见文件）')
    : locked && !draft.submittedSections ? t('全文')
      : sectionLabel(targets) || t('请选择章节')
  const canSubmit = writable && !!feedback.trim() && (selection.length > 0 || awaitingReceipt)
  useEffect(() => {
    const abort = () => {pending.current?.abort(); pending.current = null; setStatus('')}
    const unsubscribe = onApiSessionChanged(abort)
    return () => {unsubscribe(); abort()}
  }, [])
  const scrollToLatest = useCallback(() => {
    const area = log.current
    if (followingLog.current && area) area.scrollTop = area.scrollHeight
  }, [])
  useEffect(() => {
    scrollToLatest()
  }, [draft.attemptKey, draft.createdId, result.data?.status, result.error, status, error, scrollToLatest])

  function followPreview(event: UIEvent<HTMLDivElement>) {
    const viewport = event.currentTarget
    const sections = Array.from(viewport.querySelectorAll<HTMLElement>('[data-sci-revision-section]'))
    const midpoint = viewport.getBoundingClientRect().top + viewport.clientHeight / 2
    const atBottom = viewport.scrollTop >= viewport.scrollHeight - viewport.clientHeight - 1
    const current = viewport.scrollTop <= 1 ? sections[0]
      : (atBottom ? undefined : sections.find(section => section.getBoundingClientRect().bottom > midpoint)) ?? sections.at(-1)
    setReadingSection(current?.dataset.sciRevisionSection)
  }

  function toggleMultiple() {
    const nextScope: Scope | undefined = choosing ? undefined : {kind:'sections', ids:active ? [active] : []}
    setDraft({...draft, scope:nextScope})
  }
  function toggleSection(sectionId: string) {
    if (scopeDisabled || scope?.kind !== 'sections') return
    const ids = scope.ids.includes(sectionId) ? scope.ids.filter(id => id !== sectionId) : [...scope.ids, sectionId]
    setDraft({...draft, scope:{kind:'sections', ids}})
  }
  function edit(feedback: string, nextScope = scope) {
    const history = completed ? [...(draft.history ?? []), {requestId:completed.request_id, feedback:draft.feedback,
      kind:draft.submittedKind, sectionIds:draft.submittedSections ?? completed.target_sections, advice:completed.advice}] : draft.history
    if (completed) setRetained(result)
    setDraft({feedback, history, scope:nextScope}); setError('')
  }
  async function upload(file: File) {
    if (pending.current || !writable || (draft.attemptKey && !completed)) return
    if (!/\.(docx|pdf|txt)$/i.test(file.name) || file.size > 10 * 1024 * 1024) {
      setError('请选择 10 MiB 以内的 Word、PDF 或 TXT 意见文件。'); return
    }
    const readFailure = '意见文件读取失败，请粘贴原文。'
    const controller = new AbortController()
    pending.current = controller
    setStatus('正在读取意见文件……'); setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const url = manuscriptBase(projectId) + '/' + encodeURIComponent(manuscriptId) + '/writing-requests/' +
        encodeURIComponent(visibleRequest.requestId) + '/draft-feedback'
      const data = await taskRequest(url, controller, (v): v is {text: string} => !!v && typeof v === 'object' &&
        'text' in v && typeof v.text === 'string' && !!v.text.trim(), readFailure, {method: 'POST', body: form})
      if (pending.current !== controller) return
      const combined = [feedback.trimEnd(), data.text].filter(Boolean).join('\n\n')
      if (combined.length > 10000) {
        setError('意见超过一万字，请粘贴本次需要处理的内容。'); return
      }
      edit(combined, {kind:'file'})
    } catch (issue) {
      if (pending.current === controller) setError(safeError(issue, readFailure))
    } finally {
      if (pending.current === controller) {pending.current = null; setStatus('')}
    }
  }
  async function submit(checkOnly = false) {
    if (pending.current || draft.createdId || (!checkOnly && !canSubmit)) return
    const controller = new AbortController()
    pending.current = controller
    followingLog.current = true
    const attemptKey = draft.attemptKey ?? crypto.randomUUID()
    const message = feedback.trim()
    const kind = draft.attemptKey ? draft.submittedKind ?? 'revision' : intent.kind
    const advice = kind === 'advice'
    const priorAdvice = !advice && intent.inherited ? previous?.advice : undefined
    const context = priorAdvice ? `\n\n${t('上一轮建议')}\n${priorAdvice}` : ''
    const instructions = draft.submittedInstructions ?? (message + context.slice(0, 10000 - message.length))
    const attempt = {projectId, manuscriptId, attemptKey, signal: controller.signal}
    const submittedSections = draft.attemptKey ? draft.submittedSections : selection
    const sentDraft = {...draft, feedback:message, attemptKey, submittedSections, submittedKind:kind, submittedInstructions:instructions}
    setDraft(sentDraft); setError('')
    setStatus(checkOnly ? '正在读取提交结果……' : advice ? '正在提交建议请求……' : '正在提交修改稿……')
    try {
      const result = checkOnly ? await findPaperDraft(attempt) :
        await submitPaperDraftRevision({...attempt, requestId:sourceId, revision, feedback:instructions,
          targetSections:submittedSections, advice, newAttempt:!draft.attemptKey})
      controller.signal.throwIfAborted()
      if (!result || result.input.revision_of_request_id !== sourceId || result.base_revision !== revision ||
          result.input.instructions !== instructions || !matchesDraftRevisionScope(result.input, submittedSections, advice)) {
        setError('尚未找到这次修改稿，可用原意见继续提交。'); return
      }
      setDraft({...sentDraft, createdId: result.id})
    } catch (issue) {
      if (controller.signal.aborted) return
      if (isPaperDraftRejected(issue)) setDraft({feedback:message, history:draft.history, scope})
      setError(safeError(issue, '修改稿提交结果待确认，请查看提交结果。'))
    } finally {
      if (pending.current === controller) {pending.current = null; setStatus('')}
    }
  }
  return <div className="sci-revision-workspace">
    <section className="sci-revision-pane sci-revision-preview" aria-label={t('稿件预览')}>
      <header className="sci-revision-heading">
        <h2>{t(visible.data?.previous_request_id ? '修改稿' : '初稿')}</h2>
        <div className="sci-revision-heading-actions">
          {onAdjustSources && <button type="button" className="sci-revision-adjust-sources" disabled={!!status}
            onClick={onAdjustSources}>{t('调整所选文献')}</button>}
          <SciDraftWordDownload key={visibleRequest.requestId} read={visible} thesis={thesis}/>
        </div>
      </header>
      <div className="sci-revision-scroll" data-sci-revision-single={choosing ? undefined : ''} onScroll={followPreview}>
        <SciDraftView {...visibleRequest} read={visible} thesis={thesis} bodyOnly revisionScope={{editable:editableIds,
          selected:scope?.kind === 'file' ? new Set() : targets, choosing:choosing && !scopeDisabled, toggle:toggleSection,
          focus:scopeDisabled || scope ? undefined : setReadingSection}}/>
      </div>
    </section>
    <section className="sci-revision-pane" aria-label={t('修改对话')}>
      <header className="sci-revision-heading">
        <h2>{t('修改初稿')}</h2>
        {editable.length > 0 && <p className="sci-revision-scope" title={scopeLabel}>
          <span>{t('目前修改范围：')}</span><strong>{scopeLabel}</strong>
        </p>}
      </header>
      <div className="sci-revision-scroll sci-revision-log" role="log" aria-label={t('修改记录')} ref={log}
        onScroll={({currentTarget}) => {
          followingLog.current = currentTarget.scrollHeight - currentTarget.clientHeight - currentTarget.scrollTop <= 24
        }}>
        {!draft.attemptKey && !draft.history?.length && (source.data?.previous_request_id
          ? source.data.status === 'succeeded' ? <RevisionReply {...source.data}/>
            : <SciDraftProgress {...sourceRequest} read={source} reply/>
          : writable && <p className="sci-revision-reply">{t('你希望怎么修改这部分？')}</p>)}
        {draft.history?.map(turn => <Fragment key={turn.requestId}>
          <p className="sci-revision-message">{turn.feedback}</p>
          <ArchivedRevisionReply request={{...sourceRequest, requestId:turn.requestId}}
            initial={retained?.data?.request_id === turn.requestId ? retained.data : undefined}/>
        </Fragment>)}
        {draft.attemptKey && <p className="sci-revision-message">{draft.feedback}</p>}
        {draft.attemptKey && sentScope && <p className="sci-revision-reply">{t(sentAdvice
          ? '我先看看 {section}，给出修改建议。' : '我会修改 {section}。', {section:sentScope})}</p>}
        {draft.createdId && (completed ? <RevisionReply {...completed}/>
          : <SciDraftProgress {...revisionRequest} read={result} reply sections={editable} onReveal={scrollToLatest}/>)}
        {status && <p className="sci-revision-reply" role="status">{t(status)}</p>}
        {error && <p className="error-panel" role="alert">{t(error)}</p>}
        {draft.createdId && ['failed', 'cancelled'].includes(result.data?.status ?? '') &&
          <button type="button" className="button-quiet" onClick={() => edit(draft.feedback)}>{t('编辑修改意见')}</button>}
      </div>
      <form className="sci-revision-composer" onSubmit={event => {event.preventDefault(); void submit()}}>
        <fieldset disabled={!!status}>
          <div className="sci-revision-prompt">
            <textarea rows={3} maxLength={10000} aria-label={t('修改意见')} placeholder={t('输入修改意见……')}
              disabled={!writable} readOnly={awaitingReceipt} value={draft.attemptKey ? '' : feedback}
              onChange={event => edit(event.target.value)}/>
            <div className="sci-revision-tools">
              <input type="file" ref={fileInput} hidden aria-label={t('上传意见文件')} accept=".docx,.pdf,.txt"
                onChange={event => {const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload(file)}}/>
              <button type="button" className="button-quiet" disabled={!writable || awaitingReceipt}
                onClick={() => fileInput.current?.click()}><WorkspaceIcon name="plus"/>{t('上传意见文件')}</button>
              <button type="button" className="button-quiet" disabled={scopeDisabled || !editable.length} aria-expanded={choosing && !scopeDisabled}
                onClick={toggleMultiple}>{t(choosing ? '取消多选' : '多选章节')}</button>
              {awaitingReceipt && <button type="button" className="button-quiet" onClick={() => void submit(true)}>{t('查看提交结果')}</button>}
              <button type="submit" className="button-primary" disabled={!canSubmit}
                title={t('发送后将调用外部写作服务并产生写作费用。所选章节带图时，图片会随正文一起发送。')}>{t('发送修改意见')}</button>
            </div>
          </div>
        </fieldset>
      </form>
    </section>
  </div>
}
