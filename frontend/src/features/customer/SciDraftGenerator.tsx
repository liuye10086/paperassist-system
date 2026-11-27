import {useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {apiError, safeError, useI18n} from '../../shared/i18n'
import {useEvidenceResource} from '../literature/evidenceHooks'
import {EvidencePagination} from '../literature/LiteratureMaterials'
import {basePath, literatureRequest, validPage, validReference, validSearch, type Page, type Reference, type Search} from '../literature/literatureApi'
import {suggestManualPubMedQuery, suggestPubMedQuery} from '../literature/pubmedKeywords'
import {articleHeading} from '../manuscripts/articleStructure'
import {useAnalysisWritingTransfer} from '../manuscripts/analysisWritingTransfer'
import {emptyInput, manuscriptBase, validCandidates, validManuscript, type Candidates, type Manuscript, type ManuscriptInput} from '../manuscripts/manuscriptTypes'
import {defaultPaperFiles, preparePaperDraft, type DraftReference} from '../manuscripts/preparePaperDraft'
import {findPaperDraft, isPaperDraftRejected, submitPaperDraft, type DraftSkillsReview} from '../manuscripts/submitPaperDraft'
import CustomerWritingConfirm from '../manuscripts/CustomerWritingConfirm'
import {validThesisInput, type SchoolPurpose} from '../manuscripts/thesisTypes'
import {canonicalJson, frozenWritingEvidence, writableSchoolPurpose} from '../manuscripts/writingLiveTypes'
import type {Project} from '../projects/projectTypes'
import {jsonRequest} from '../research-intake/api'
import {useResearchRead} from '../research-results/api'
import useResearchDraft from '../research-results/useResearchDraft'
import {TaskRequestError} from '../tasks/taskApi'
import {isTask, type TaskView} from '../tasks/taskTypes'
import type {SciSettings} from './sciProjectSettings'
import type {ThesisRequirements} from './thesisProjectRequirements'
import ThesisDraftMaterials from './ThesisDraftMaterials'
import {thesisDraftMaterials} from './thesisGenerationInput'
import './sciDraftGenerator.css'

type SharedProps = {project: Project; initialSearchId?:string; onOpenProject?: () => void; onOpenOrganizer?: () => void; onOpenMaterials?: () => void; onSubmitted: (manuscriptId: string, revision: number, requestId: string) => void}
type Props = SharedProps & {settings:SciSettings | null; onOpenResources?: () => void}
type ThesisProps = SharedProps & {requirements:ThesisRequirements | null}
type Ticket = {key: string; input: ManuscriptInput; references: DraftReference[]; manuscriptId?: string; preparedId?: string; revision?: number; needsSkillsConfirmation?: true}
const maxPapers = 20
const maxSciFigures = 20
const ignoreDenied = () => undefined
const pending = (status: string) => status === 'queued' || status === 'running'

function draftMaterials(project: Project, candidates: Candidates, current?: Manuscript) {
  const plan = candidates.paper_plan
  const input = emptyInput(plan?.title || project.name, project.default_output_language ?? 'zh-CN')
  input.expected_revision = current?.current_revision ?? 0
  if (plan) input.paper_plan_token = plan.token
  const linked = new Set(plan?.materials.map(material => material.selection.file_id))
  // Earlier projects may have a result already attributed to one of their uploaded files.
  const previous = current?.versions.find(version => version.revision === current.current_revision)?.input
  const configuredFigures = new Set(plan?.sci_figures?.map(figure => figure.figure_id))
  const useFormalFigures = plan?.sci_figures !== undefined || plan?.sci_figures_need_configuration === true
  const previousImageRoles = new Map(previous?.sources.filter(source => source.kind === 'original' &&
    (source.role === 'methods' || source.role === 'user_results')).map(source => [source.id, source.role]))
  const files = defaultPaperFiles(candidates.items.filter(file => !useFormalFigures || file.kind !== 'original' ||
    !file.allowed_roles.includes('image_observation') || !configuredFigures.has(file.id) && previousImageRoles.has(file.id)), linked)
  input.sources = files.map(file => {
    const previousRole = useFormalFigures && file.kind === 'original' && file.allowed_roles.includes('image_observation')
      ? previousImageRoles.get(file.id) : undefined
    const role = previousRole && file.allowed_roles.includes(previousRole) ? previousRole
      : !useFormalFigures && plan?.kind === 'research' && file.kind === 'original' && file.allowed_roles.includes('image_observation')
        ? 'image_observation' : file.allowed_roles.includes('methods') ? 'methods' : file.allowed_roles[0]
    return {id:file.id, kind:file.kind, file_id:file.file_id, role}
  })
  if (previous?.reported_result && plan?.kind === 'research') {
    const sourceIds = previous.reported_result.source_ids.map(id => {
      const original = previous.sources.find(source => source.id === id && source.role === 'user_results')
      return files.find(file => file.file_id === original?.file_id && file.allowed_roles.includes('user_results'))?.id
    })
    if (sourceIds.length && sourceIds.every((id): id is string => !!id)) {
      input.reported_result = {text: previous.reported_result.text, source_ids: sourceIds}
      input.sources = input.sources.map(source => sourceIds.includes(source.id) ? {...source, role:'user_results'} : source)
    }
  }
  const hasResult = !!input.reported_result || !!plan?.sections.some(section => section.text.trim()) ||
    !!plan?.materials.some(material => material.result.trim())
  const parsing = files.filter(file => file.kind === 'original' && /\.(docx|xlsx)$/i.test(file.label))
  return {input, hasResult, parsing}
}

function referenceCitation(reference: Reference) {
  return [reference.record.journal, reference.record.year, `PMID ${reference.pmid}`].filter(Boolean).join(' · ')
}

function ReferenceDetails({reference, onClose}: {reference: Reference; onClose: () => void}) {
  const {t} = useI18n()
  const titleId = useId()
  const dialog = useRef<HTMLDialogElement>(null)
  useLayoutEffect(() => {
    const element = dialog.current
    if (!element) return
    if (!element.open) {
      if (typeof element.showModal === 'function') element.showModal()
      else element.setAttribute('open', '')
    }
    return () => { if (element.open && typeof element.close === 'function') element.close() }
  }, [])

  const {record} = reference
  const abstract = record.abstract.filter(part => part.text.trim())
  return <dialog ref={dialog} className="sci-reference-dialog" aria-labelledby={titleId}
    onCancel={event => {event.preventDefault(); onClose()}}>
    <header>
      <h2 id={titleId}>{record.title || t('题名未提供')}</h2>
      <button type="button" className="button-accent" onClick={onClose}>{t('关闭详情')}</button>
    </header>
    <div className="sci-reference-dialog-body">
      {record.authors.length > 0 && <p>{record.authors.join(', ')}</p>}
      <p className="muted">{referenceCitation(reference)}</p>
      <h3>{t('原文摘要')}</h3>
      {abstract.length ? abstract.map((part, index) => <p key={index} className="sci-reference-abstract-part">
        {part.label && <strong>{part.label} · </strong>}{part.text}</p>) : <p>{t('摘要未返回')}</p>}
      <a href={`https://pubmed.ncbi.nlm.nih.gov/${reference.pmid}/`} target="_blank" rel="noopener noreferrer">{t('PubMed 原始条目')}</a>
    </div>
  </dialog>
}

function Generator({project, settings, requirements, initialSearchId, onSubmitted, onOpenProject, onOpenOrganizer, onOpenResources, onOpenMaterials}: Props & {requirements?:ThesisRequirements | null}) {
  const {t} = useI18n()
  const id = project.id, lit = basePath(id), base = manuscriptBase(id)
  const school = project.project_type === 'thesis'
  const scope = school ? 'thesis-simple-' : 'sci-simple-'
  const keywords = requirements?.keywords ?? settings?.keywords ?? []
  const [query, setQuery] = useResearchDraft(id, scope + 'query', () => suggestPubMedQuery(keywords).query || (school ? keywords.join(' ') : ''))
  const [searchId, setSearchId] = useResearchDraft(id, scope + 'search' + (initialSearchId ? ':' + initialSearchId : ''), () => initialSearchId ?? '')
  const [ticket, setTicket] = useResearchDraft<Ticket | null>(id, scope + 'submit', () => null)
  const [purposes, setPurposes] = useResearchDraft<Record<string,SchoolPurpose>>(id, 'thesis-chapter-purposes', () => ({}))
  const [resultTargets, setResultTargets] = useResearchDraft<Record<string,string>>(id, 'thesis-result-chapter', () => ({}))
  const [omittedCitation, setOmittedCitation] = useResearchDraft(id, 'thesis-omitted-citation', () => '')
  const transfer = useAnalysisWritingTransfer()
  const [page, setPage] = useState(1), [selectedOnly, setSelectedOnly] = useState(false)
  const [readingReference, setReadingReference] = useState<Reference | null>(null)
  const [refresh, setRefresh] = useState(0), [projectRefresh, setProjectRefresh] = useState(0)
  const [busy, setBusy] = useState(''), [error, setError] = useState('')
  const [skillsReview, setSkillsReview] = useState<(DraftSkillsReview & {accept: () => void; cancel: () => void}) | null>(null)
  const [failedRecovery, setFailedRecovery] = useState('')
  const operation = useRef<AbortController | null>(null)
  const searchKey = useRef({signature:'', key:''})
  useEffect(() => {
    const stop = () => {operation.current?.abort(); operation.current = null}
    const unsubscribe = onApiSessionChanged(stop)
    return () => {stop(); unsubscribe()}
  }, [])
  const search = useResearchRead<Search>(searchId ? lit + '/searches/' + encodeURIComponent(searchId) : '', !!searchId,
    value => validSearch(value, id) && pending(value.task.status))
  const savedSearch = validSearch(search.data, id) && search.data.id === searchId ? search.data : null
  const loadingSearch = !!searchId && (search.loading || !!savedSearch && pending(savedSearch.task.status))
  const stoppedSearch = savedSearch && !pending(savedSearch.task.status) && savedSearch.task.status !== 'succeeded'
  const searchProblem = stoppedSearch && savedSearch.task.error_code === 'storage_accounting_unknown'
    ? '保存检索结果时中断了。点「重新检索」可继续原任务，已选文献仍然保留。'
    : stoppedSearch ? apiError({code:savedSearch.task.error_code},
    apiError({code:savedSearch.task.reason_code}, '检索未完成，请核对条件后重试。')) : ''
  const params = new URLSearchParams({page: String(page)})
  if (selectedOnly) params.set('selection', 'shortlisted')
  else if (searchId) params.set('search_id', searchId)
  const readPage = (value: unknown, number: number): value is Page<Reference> =>
    validPage(value, id, number, row => validReference(row, id))
  const records = useEvidenceResource<Page<Reference>>(loadingSearch && !selectedOnly ? null : lit + '/references?' + params,
    (v): v is Page<Reference> => readPage(v, page), refresh + (savedSearch?.retrieved_count ?? 0), ignoreDenied, {keepDataOnRefresh: true})
  const shortlist = useEvidenceResource<Page<Reference>>(lit + '/references?page=1&selection=shortlisted',
    (v): v is Page<Reference> => readPage(v, 1), refresh, ignoreDenied, {keepDataOnRefresh: true})
  useEffect(() => {
    if (!selectedOnly || records.loading || !records.data) return
    const lastPage = Math.max(1, Math.ceil(records.data.total / records.data.page_size))
    if (page > lastPage) setPage(lastPage)
  }, [selectedOnly, records.loading, records.data, page])
  const candidates = useEvidenceResource<Candidates>(base + '/candidates',
    (v): v is Candidates => validCandidates(v, id) && (v.project_type === 'thesis') === school, projectRefresh, ignoreDenied)
  const history = useEvidenceResource<{items: Manuscript[]}>(base,
    (v): v is {items: Manuscript[]} => !!v && typeof v === 'object' && 'items' in v &&
      Array.isArray(v.items) && v.items.every(root => validManuscript(root, id)), projectRefresh, ignoreDenied)
  const current = history.data?.items[0]
  const last = current?.versions.find(version => version.revision === current.current_revision)
  const resultTargetKey = (last?.id ?? '') + '/' + (candidates.data?.thesis?.confirmation_id ?? '')
  const resultChapter = resultTargets[resultTargetKey] ?? ''
  const thesisMaterial = school && candidates.data
    ? thesisDraftMaterials(project, requirements ?? null, candidates.data, current, purposes, resultChapter, transfer?.pending) : null
  const citation = thesisMaterial?.input.citation_draft
  const citationKey = citation ? citation.id + '/' + citation.revision : ''
  const count = shortlist.data?.total
  const carryCitation = !!citation && !count && omittedCitation !== citationKey
  if (thesisMaterial && !carryCitation) thesisMaterial.input.citation_draft = null
  const materials = thesisMaterial ? {...thesisMaterial, hasResult:false} :
    candidates.data ? draftMaterials(project, candidates.data, current) : null
  const kind = candidates.data?.paper_plan?.kind ?? settings?.article_type
  const plan = candidates.data?.paper_plan
  const needsSciTemplate = !school && !!onOpenOrganizer && !plan?.sci_template
  const needsSciResources = !school && plan?.sci_figures_need_configuration === true
  const needsThesisResources = school && plan?.thesis_figures_need_configuration === true
  const formalFigures = school ? plan?.thesis_figures : plan?.sci_figures
  const tooManySciFigures = !school && (formalFigures?.length ?? 0) > maxSciFigures
  const reviewFigures = !formalFigures && !needsSciResources && plan?.kind === 'narrative_review' ? plan.materials.filter(material => material.kind === 'figure') : []
  const sourceCount = new Set([...(materials?.input.sources.map(source => source.id) ?? []),
    ...(formalFigures?.map(figure => figure.figure_id) ?? []),
    ...(plan?.kind !== 'research' ? plan?.materials.map(material => material.selection.id) ?? [] : [])]).size
  const readiness = candidates.data?.thesis
  const missingDirectory = school && candidates.data && (!readiness?.ready || !readiness.confirmation_id ||
    requirements?.template && requirements.template.confirmation_id !== readiness.confirmation_id)
  const chapterInput = thesisMaterial?.input.thesis
  const missing = school && !requirements || !school && !settings ? '请先保存项目信息。'
    : needsSciResources ? '请先在资源配置中核对并保存图件。'
    : tooManySciFigures ? '一版初稿最多使用 20 张图，请在资源配置中调整。'
    : !candidates.data || !history.data || count === undefined ? ''
    : missingDirectory ? '请先确认学校模板，初稿会按模板里的章节生成。'
    : needsThesisResources ? '请先在资源配置中核对并保存图件。'
    : school && plan?.kind !== 'thesis' ? '请先保存项目的写作要求。'
    : school && (!validThesisInput(chapterInput) || !chapterInput.chapter_mappings.some(ch => writableSchoolPurpose(ch.purpose)))
      ? '请核对下方章节用途，至少选择一个需要生成正文的章节。'
    : thesisMaterial?.unassignedResult ? thesisMaterial.resultChoices ? '请选择已有结果所属的章节。' : '请将用户提供的结果分配给一个结果章节。'
    : kind === 'research' && !materials?.hasResult ? '请在项目信息中补充主要结果。'
    : kind === 'narrative_review' && !count ? '请至少勾选一篇有摘要的文献。'
    : count > maxPapers ? '一次最多使用 20 篇文献，请减少勾选数量。'
    : sourceCount > 50 ? '本项目超过单次写作可使用的 50 项资料。' : ''
  const ready = !!materials && !!history.data && !shortlist.loading && count !== undefined && !missing
  const failed = current?.versions.find(version => version.revision === current.current_revision && version.status === 'failed')
  const savedPapers = new Set(failed?.snapshot.references.map(ref => ref.project_reference_id))
  const samePapers = carryCitation && canonicalJson(citation) === canonicalJson(failed?.input.citation_draft) ||
    count === savedPapers.size && shortlist.data?.items.every(item => savedPapers.has(item.id))
  const sameFiles = failed && materials && failed.input.sources.length === materials.input.sources.length &&
    failed.input.sources.every(old => materials.input.sources.some(item => item.id === old.id && item.kind === old.kind && item.role === old.role))
  const recoverable = failed && !failed.current_changes.length && samePapers && sameFiles &&
    failed.input.paper_plan_token === materials?.input.paper_plan_token && (!school ||
      canonicalJson({...failed.input,expected_revision:0,citation_draft:null}) === canonicalJson({...materials?.input,expected_revision:0,citation_draft:null}))
  const refreshPage = () => setRefresh(revision => revision + 1)
  const issue = error || records.error || shortlist.error || candidates.error || history.error || search.error
  const emptyMessage = selectedOnly ? '此项目暂无已入选的文献。'
    : !searchId ? '此项目还没有保存的候选文献。'
    : savedSearch?.task.status === 'succeeded' ? '本次检索没有返回候选文献。请调整检索词后重试。' : ''

  async function perform(label: string, action: (controller: AbortController) => Promise<void>) {
    if (operation.current) return
    const controller = new AbortController()
    operation.current = controller
    setBusy(label); setError('')
    try {await action(controller)}
    catch (cause) {if (operation.current === controller && !controller.signal.aborted) setError(safeError(cause, '本次操作未确认，请重试。'))}
    finally {if (operation.current === controller) {operation.current = null; setBusy('')}}
  }
  function startSearch(event: FormEvent) {
    event.preventDefault()
    const raw = query.trim()
    if (!raw || ticket) return
    const suggestion = suggestManualPubMedQuery(raw)
    const topic = project.research_topic || project.name
    const body = {research_topic:topic, source_context:{kind:'project_topic',label:'',text:topic},
      query:suggestion && !suggestion.omitted.length && suggestion.query || raw, year_from:null, year_to:null,
      publication_types:[], sort:'relevance', limit:20, output_language:project.default_output_language ?? 'zh-CN'}
    const prior = savedSearch?.input
    const retry = savedSearch?.task.status === 'failed' && savedSearch.task.revision &&
      ['ncbi_unavailable', 'storage_accounting_unknown', 'storage_quota_exceeded', 'storage_disk_insufficient'].includes(savedSearch.task.error_code ?? '') &&
      prior?.query === body.query && prior.research_topic === topic && prior.source_context.kind === 'project_topic' &&
      prior.source_context.text === topic && prior.source_context.label === '' && prior.output_language === body.output_language &&
      prior.limit === body.limit && prior.sort === body.sort && prior.year_from === null && prior.year_to === null &&
      prior.publication_types.length === 0 ? savedSearch.task : null
    const payload = retry ? {operation:'retry', wait_id:null, expected_task_revision:retry.revision, input_version:retry.input_version} : body
    const path = retry ? '/api/v1/tasks/' + encodeURIComponent(retry.id) + '/resume' : lit + '/searches'
    const signature = JSON.stringify([path, payload])
    if (searchKey.current.signature !== signature) searchKey.current = {signature, key:crypto.randomUUID()}
    void perform('正在检索文献……', async controller => {
      const task = await literatureRequest(path, controller,
        (v): v is TaskView => isTask(v, id, retry?.id) && v.task_type === 'literature_search', jsonRequest(payload, searchKey.current.key))
      controller.signal.throwIfAborted()
      searchKey.current = {signature:'',key:''}
      setSearchId(task.id); setPage(1); setSelectedOnly(false)
      if (retry) search.refresh()
    })
  }
  function toggle(reference: Reference) {
    void perform('正在保存文献选择……', async controller => {
      const status = reference.selection.status === 'shortlisted' ? 'candidate' : 'shortlisted'
      try {
        await literatureRequest(lit + '/references/' + encodeURIComponent(reference.id), controller,
          (v): v is Reference => validReference(v, id) && v.id === reference.id && v.selection.status === status, {
            method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
              expected_revision:reference.selection.revision, note:reference.selection.note, status,
            }),
          })
        if (citationKey) setOmittedCitation(citationKey)
      } finally {if (!controller.signal.aborted) refreshPage()}
    })
  }
  async function generate(controller: AbortController, recover = false) {
    const signal = controller.signal
    let saved = ticket
    if (!saved) {
      if (!ready || !materials) return
      const first = await literatureRequest(lit + '/references?page=1&selection=shortlisted', controller,
        (v): v is Page<Reference> => readPage(v, 1))
      const selected = [...first.items]
      if (first.total !== count) {refreshPage(); throw new Error('已选文献发生变化，请重新生成。')}
      for (let number = 2; number <= Math.ceil(first.total / first.page_size); number++) {
        const next = await literatureRequest(lit + '/references?page=' + number + '&selection=shortlisted', controller,
          (v): v is Page<Reference> => readPage(v, number))
        selected.push(...next.items)
      }
      signal.throwIfAborted()
      if (selected.length !== count || new Set(selected.map(item => item.id)).size !== count) {
        refreshPage(); throw new Error('已选文献发生变化，请重新生成。')
      }
      if (recover && (!recoverable || !current || selected.some(item => !savedPapers.has(item.id)))) {
        if (failed) setFailedRecovery(failed.id)
        throw new Error('当前资料已变更，请使用当前资料生成。')
      }
      saved = recover && failed && current
        ? {key:(school ? 'thesis-resume-' : 'sci-resume-') + failed.id, manuscriptId:current.id, preparedId:current.id, revision:failed.revision,
          input:failed.input, references:[]}
        : {key:crypto.randomUUID(), manuscriptId:current?.id, input:materials.input,
          references:selected.map(item => ({project_reference_id:item.id, search_id:item.source.search_id}))}
      setTicket(saved)
    }
    let preparing = false
    try {
      if (saved.preparedId && saved.revision) {
        const previous = await findPaperDraft({projectId:id, manuscriptId:saved.preparedId, attemptKey:saved.key, signal})
        signal.throwIfAborted()
        if (previous) {setTicket(null); onSubmitted(saved.preparedId, saved.revision, previous.id); return}
      }
      preparing = true
      const result = await preparePaperDraft({projectId:id, manuscriptId:saved.preparedId ?? saved.manuscriptId, input:saved.input,
        references:saved.references, attemptKey:saved.key, signal,
        ...(saved.preparedId && saved.revision ? {existingRevision:saved.revision} : {})})
      preparing = false
      signal.throwIfAborted()
      const prepared = {...saved, preparedId:result.manuscriptId, revision:result.version.revision}
      setTicket(prepared)
      const receipt = await submitPaperDraft({projectId:id, manuscriptId:result.manuscriptId, version:result.version,
        attemptKey:saved.key, sciSettings:settings, documentKind:school ? 'thesis' : 'sci', signal,
        confirmSkills: review => new Promise<void>((resolve, reject) => {
          signal.throwIfAborted()
          setTicket({...prepared,needsSkillsConfirmation:true})
          const abort = () => {setSkillsReview(null); reject(signal.reason)}
          signal.addEventListener('abort', abort, {once:true})
          setSkillsReview({...review, accept: () => {
            signal.removeEventListener('abort', abort)
            setSkillsReview(null)
            resolve()
          }, cancel: () => controller.abort()})
        })})
      signal.throwIfAborted()
      setTicket(null); onSubmitted(result.manuscriptId, result.version.revision, receipt.id)
    } catch (cause) {
      if (saved.preparedId && preparing && cause instanceof TaskRequestError && cause.status >= 400 &&
        cause.status < 500 && cause.status !== 408 && failed) setFailedRecovery(failed.id)
      if (!signal.aborted && (isPaperDraftRejected(cause) || preparing && cause instanceof TaskRequestError &&
        cause.status >= 400 && cause.status < 500 && cause.status !== 408)) {setTicket(null); refreshPage(); setProjectRefresh(v => v + 1)}
      throw cause
    }
  }
  const literatureResults = <>
    <div className="literature-actions">
      <button type="button" className="button-accent" aria-pressed={!selectedOnly}
        onClick={() => {setSelectedOnly(false); setPage(1)}}>{t('检索结果')}</button>
      <button type="button" className="button-accent" aria-pressed={selectedOnly}
        onClick={() => {setSelectedOnly(true); setPage(1)}}>{t('已选文献')} {count ?? ''}</button>
      {searchId && <button type="button" className="button-accent"
        onClick={() => {setSearchId(''); setSelectedOnly(false); setPage(1)}}>{t('查看已有候选')}</button>}
    </div>
    {loadingSearch && <p role="status">{t('正在检索文献……')}</p>}
    {!selectedOnly && searchProblem && busy !== '正在检索文献……' && <p role="alert">{t(searchProblem)}</p>}
    {records.data && (records.data.items.length ? <ul className="sci-reference-list" role="list" aria-label={t(selectedOnly ? '已选文献' : '检索结果')}>
      {records.data.items.map(item => {
        const title = item.record.title || t('题名未提供')
        const selected = item.selection.status === 'shortlisted'
        const abstract = item.record.abstract.find(part => part.text.trim())?.text.trim() ?? ''
        const excerpt = abstract.length > 220 ? `${abstract.slice(0, 220).trimEnd()}…` : abstract
        return <li key={item.id}>
          <div className="sci-reference-text">
            <h3><button type="button" className="button-quiet sci-reference-title" aria-haspopup="dialog"
              onClick={() => setReadingReference(item)}>{title}</button></h3>
            <p className="muted sci-reference-citation">{referenceCitation(item)}</p>
            <p className="sci-reference-excerpt">{excerpt || t('摘要未返回')}</p>
          </div>
          <input type="checkbox" aria-label={title} checked={selected}
            disabled={!!busy || !!ticket || records.loading || shortlist.loading || count === undefined ||
              !selected && (count >= maxPapers || !abstract)}
            onChange={() => toggle(item)} />
        </li>
      })}
    </ul> : emptyMessage && <p>{t(emptyMessage)}</p>)}
    {records.data && records.data.total > records.data.page_size && <EvidencePagination page={page} total={records.data.total}
      onPage={setPage} label="候选文献分页" buttonClassName="button-accent"/>}
  </>

  if (needsSciTemplate && !ticket) {
    if (candidates.error) return <p role="alert" className="error-panel">{t(candidates.error)}{' '}
      <button type="button" className="button-accent" onClick={() => setProjectRefresh(value => value + 1)}>{t('重试')}</button></p>
    if (!candidates.data) return <p role="status">{t('正在读取稿件资料……')}</p>
    return <div>
      <p>{t('请先核对并使用 SCI 模板。')}</p>
      <button type="button" className="button-accent" onClick={onOpenOrganizer}>{t('前往模板设定和资源配置')}</button>
    </div>
  }

  return <section className="sci-draft-generator" data-project-type={project.project_type}>
    {readingReference && <ReferenceDetails reference={readingReference} onClose={() => setReadingReference(null)} />}
    <form onSubmit={startSearch} className="literature-actions">
      <label>{t('检索词')}<input value={query} maxLength={4000} onChange={e => setQuery(e.target.value)}/></label>
      <button type="submit" className="button-accent" disabled={!query.trim() || !!busy || !!ticket || loadingSearch}>
        {t(stoppedSearch ? '重新检索' : '搜索文献')}</button>
    </form>
    {thesisMaterial && candidates.data && <ThesisDraftMaterials candidates={candidates.data} material={thesisMaterial}
      requirements={requirements ?? null} locked={!!ticket || !!busy} resultChapter={resultChapter}
      onResultChapter={chapter => setResultTargets(old => ({...old,[resultTargetKey]:chapter}))}
      onChange={(key,purpose) => setPurposes(previous => ({...previous,[key]:purpose}))}/>}
    {citation && last && count === 0 && <div>
      <label><input type="checkbox" checked={carryCitation} disabled={!!busy || !!ticket}
        onChange={event => setOmittedCitation(event.target.checked ? '' : citationKey)}/>{t('沿用上次稿件的引用')}</label>
      <details><summary>{t('查看原文摘录')}</summary>
        {last.snapshot.references.map(ref => <p key={ref.project_reference_id}>{ref.text}</p>)}
        {frozenWritingEvidence(last.snapshot).map(evidence => <blockquote key={evidence.id}>{evidence.quote}</blockquote>)}
      </details>
    </div>}
    {!school && literatureResults}
    <div className="sci-generate-panel">
      {issue && <p role="alert">{t(issue)} <button type="button" className="button-accent"
        onClick={() => {setError(''); refreshPage(); setProjectRefresh(v => v + 1); search.refresh()}}>{t('刷新')}</button></p>}
      {busy && <p role="status">{t(busy)}</p>}
      {!ticket && missing && <div><p>{t(missing)}</p>{school && requirements && onOpenOrganizer && (missingDirectory || needsThesisResources ||
        thesisMaterial?.unassignedResult && !thesisMaterial.resultChoices ||
        validThesisInput(chapterInput) && !chapterInput.chapter_mappings.some(c => writableSchoolPurpose(c.purpose))) &&
        <button type="button" className="button-accent" onClick={onOpenOrganizer}>{t('前往模板与资料整理')}</button>}
        {school && onOpenProject && (!requirements || !missingDirectory && !plan) &&
          <button type="button" className="button-accent" onClick={onOpenProject}>{t('填写毕业论文需求')}</button>}
        {school && onOpenMaterials && sourceCount > 50 && <button type="button" className="button-accent" onClick={onOpenMaterials}>{t('管理上传材料')}</button>}
        {(needsSciResources || tooManySciFigures) && onOpenResources && <button type="button" className="button-accent" onClick={onOpenResources}>{t('前往资源配置')}</button>}
        {onOpenProject && kind === 'research' && !materials?.hasResult &&
        <button type="button" className="button-accent" onClick={onOpenProject}>{t('补充主要结果')}</button>}</div>}
      {!ticket && !missing && !!materials?.parsing.length && <div><p>{t('以下文件尚无可读正文。本次仅使用已保存的文件说明。')}</p>
        <ul>{materials.parsing.map(file => <li key={file.file_id}>{file.label}</li>)}</ul>
        <button type="button" className="button-accent" onClick={() => setProjectRefresh(v => v + 1)}>{t('刷新文件状态')}</button></div>}
      {!ticket && reviewFigures.length > 0 && <details className="sci-planned-figures">
        <summary>{t('本次配图（{count} 张）', {count:reviewFigures.length})}</summary>
        <ul>{reviewFigures.map(figure => <li key={figure.selection.id}>{figure.filename} · {plan?.sections.find(section =>
          section.id === figure.section_id)?.label ?? articleHeading('narrative_review', figure.section_id, project.default_output_language ?? 'zh-CN')}</li>)}</ul>
      </details>}
      {!ticket && !!formalFigures?.length && <section className="sci-planned-figures" aria-label={t('本次配图（{count} 张）', {count:formalFigures.length})}>
        <h3>{t('本次配图（{count} 张）', {count:formalFigures.length})}</h3>
        <ul>{formalFigures.map(figure => <li key={figure.figure_id}>
          <strong>{figure.title}</strong> · <span>{figure.chapter_label}</span>
          {!!figure.caption && <p>{figure.caption}</p>}
        </li>)}</ul>
      </section>}
      {skillsReview ? <>
        <CustomerWritingConfirm bundle={skillsReview.bundle} version={skillsReview.version} capabilities={skillsReview.capabilities}
          customerThesis={school} generated={false} edited={false} unknown={false} previewUnknown={false} busy={false}
          onSubmit={async () => skillsReview.accept()}/>
        <button type="button" className="button-accent" onClick={skillsReview.cancel}>{t('取消')}</button>
      </> : <>
      <p className="muted">{t(!school && formalFigures?.length
        ? '点击生成即同意将入稿图件、写作资料和所选摘要发送至外部写作服务。服务商将保存生成记录，本次写作会产生费用。'
        : '点击生成即同意将本项目的写作资料和所选摘要发送至外部写作服务。服务商将保存生成记录，本次写作会产生费用。')}</p>
      {!ticket && failed && !recoverable && ready && <p>{t('当前资料已变更，请使用当前资料生成。')}</p>}
      <button type="button" className="button-accent sci-generate-action" disabled={!!busy || !ticket && !ready}
        onClick={() => void perform('正在提交初稿……', controller => generate(controller, !!recoverable && !(school && failedRecovery === failed?.id)))}>
        {t(ticket && (!school || ticket.needsSkillsConfirmation) ? '继续本次生成' : school ? '生成毕业论文初稿' : recoverable ? '恢复原整理任务并生成初稿' : failed ? '使用当前资料生成' : !missing && materials?.parsing.length ? '使用现有资料继续生成' : '生成初稿')}</button>
      {ticket?.needsSkillsConfirmation&&<button type="button" className="button-accent" disabled={!!busy} onClick={() => {
        setTicket(null)
        setProjectRefresh(value => value + 1)
      }}>{t('返回修改')}</button>}
      {!school && !ticket && recoverable && failedRecovery === failed?.id && <button type="button" className="button-accent" disabled={!!busy || !ready}
        onClick={() => void perform('正在提交初稿……', controller => generate(controller))}>{t('使用当前资料生成')}</button>}
      </>}
    </div>
    {school && literatureResults}
  </section>
}

export function SciDraftGenerator(props: Props) {
  return <Generator key={props.project.id + (props.initialSearchId ?? '')} {...props}/>
}

export function ThesisDraftGenerator(props: ThesisProps) {
  return <Generator key={props.project.id + (props.initialSearchId ?? '')} {...props} settings={null}/>
}
