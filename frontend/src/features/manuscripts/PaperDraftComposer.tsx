import {useEffect, useRef, useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError, useI18n} from '../../shared/i18n'
import {parsedMaterialLabel} from '../../shared/parsedMaterialLabel'
import type {SciSettings} from '../customer/sciProjectSettings'
import useResearchDraft from '../research-results/useResearchDraft'
import {TaskRequestError} from '../tasks/taskApi'
import ManuscriptReferencePicker, {type SelectedReference} from './ManuscriptReferencePicker'
import {sourceKey, validInput, type Candidates, type Manuscript, type ManuscriptInput} from './manuscriptTypes'
import {paperDraftMaterials, type MaterialChoices} from './paperDraftMaterials'
import {preparePaperDraft} from './preparePaperDraft'
import {findPaperDraft, isPaperDraftRejected, submitPaperDraft} from './submitPaperDraft'
import {purposeLabels, schoolPurposes, validThesisInput, type SchoolPurpose} from './thesisTypes'
import {frozenWritingEvidence, writableSchoolPurpose} from './writingLiveTypes'
import './paperDraftComposer.css'

type Choices = MaterialChoices & {references: SelectedReference[]}
type Ticket = {key: string; input: ManuscriptInput; references: SelectedReference[]; manuscriptId?: string;
  preparedId?: string; revision?: number; requestId?: string}
type Props = {projectId: string; active: boolean; school: boolean; candidates: Candidates; baseInput: ManuscriptInput;
  current?: Manuscript; sciSettings?: SciSettings | null; planUnavailable: boolean; onPrepared: (root: Manuscript) => void;
  onOpenGenerated: (id: string, revision: number, requestId: string) => void; onFindLiterature?: () => void;
  onOpenSchoolTemplate?: () => void; onOpenRequirements?: () => void; onOpenMaterials?: () => void; onRefresh: () => void}

export default function PaperDraftComposer({projectId, active, school, candidates, baseInput, current, sciSettings,
  planUnavailable, onPrepared, onOpenGenerated, onFindLiterature, onOpenSchoolTemplate, onOpenRequirements, onOpenMaterials, onRefresh}: Props) {
  const {t} = useI18n()
  const [choices, setChoices] = useResearchDraft<Choices>(projectId, 'paper-draft-choices', () => ({references: [], omittedFiles: [], chapterPurposes: {}}))
  const [ticket, setTicket] = useResearchDraft<Ticket | null>(projectId, 'paper-draft-submission', () => null)
  const [consent, setConsent] = useState(false), [stage, setStage] = useState(''), [error, setError] = useState('')
  const operation = useRef<AbortController | null>(null)
  useEffect(() => {
    const stop = () => {operation.current?.abort(); operation.current = null; setStage(''); setConsent(false)}
    const unsubscribe = onApiSessionChanged(stop)
    return () => {stop(); unsubscribe()}
  }, [projectId, active])
  function edit(update: Partial<Choices>) {setChoices(old => ({...old, ...update})); setConsent(false); setError('')}
  const plan = candidates.paper_plan, readiness = candidates.thesis
  const last = current?.versions.find(v => v.revision === current.current_revision)
  const review = !school && (plan?.kind ?? sciSettings?.article_type ?? last?.snapshot.article_type) === 'narrative_review'
  const {input, options, resultSources} = paperDraftMaterials(candidates, baseInput, choices, current?.current_revision ?? 0, review)
  const frozenCount = last && last.input.citation_draft?.id === input.citation_draft?.id &&
    last.input.citation_draft?.revision === input.citation_draft?.revision ? frozenWritingEvidence(last.snapshot).length : 0
  const hasResult = !!plan?.materials.some(m => m.result.trim()) || input.results_groups.some(g =>
    g.analysis_run_ids.some(id => input.sources.some(s => s.id === id && s.role === 'computed_results')))
  const needResult = !school && !review && !hasResult
  const pendingUploads = options.filter(s => s.kind === 'original' && /\.(docx|xlsx)$/i.test(s.label) && !choices.omittedFiles.includes(s.file_id))
  const pendingKey = pendingUploads.map(s => s.file_id).join(',')
  const refreshAttempts = useRef({key: '', count: 0})
  useEffect(() => {
    if (!active || !pendingKey || ticket) return
    if (refreshAttempts.current.key !== pendingKey) refreshAttempts.current = {key: pendingKey, count: 0}
    if (refreshAttempts.current.count >= 12) return
    const timer = window.setTimeout(() => {refreshAttempts.current.count++; onRefresh()}, 5000)
    return () => window.clearTimeout(timer)
  }, [pendingKey, active, onRefresh, ticket])
  const invalidChapter = school && (!validThesisInput(input.thesis) || !input.thesis.chapter_mappings.some(m => writableSchoolPurpose(m.purpose)))
  let missing = ''
  if (school && !readiness?.ready) missing = '请先确认学校模板，初稿会按模板里的章节生成。'
  else if (planUnavailable) missing = '请先保存项目的写作要求。'
  else if (invalidChapter) missing = '请核对下方章节用途，至少选择一个需要生成正文的章节。'
  else if (pendingUploads.length) missing = '勾选的 Word 或 Excel 还没有可读版本。可等待解析、查看上传状态，或取消勾选后继续。'
  else if (review && !choices.references.length && !frozenCount) missing = '请从候选文献中勾选至少一段原文，用作综述依据。'
  else if (needResult && !input.reported_result) missing = '请填写主要结果，并选择提供这项结果的文件。'
  else if (input.sources.length > 50) missing = '一次最多使用 50 项补充材料，请取消部分文件。'
  else if (!validInput(input)) missing = '请填写稿件标题，检查分组与冲突资料。'
  const locked = !!ticket || !!stage
  const finished = !!ticket?.requestId && !!ticket.preparedId && !!ticket.revision
  const open = (saved: Ticket) => {
    if (saved.preparedId && saved.revision && saved.requestId) onOpenGenerated(saved.preparedId, saved.revision, saved.requestId)
  }
  async function run(checkOnly = false) {
    if (operation.current || !active || (!checkOnly && (!consent || (!ticket && missing)))) return
    const controller = new AbortController()
    operation.current = controller
    const signal = controller.signal
    let saved: Ticket = ticket ?? {key: crypto.randomUUID(), input, references: choices.references, manuscriptId: current?.id}
    let savingMaterials = false
    setTicket(saved); setError(''); setConsent(false)
    try {
      if (saved.preparedId && saved.revision) {
        setStage('正在读取提交结果……')
        const found = await findPaperDraft({projectId, manuscriptId: saved.preparedId, attemptKey: saved.key, signal})
        signal.throwIfAborted()
        if (found) {saved = {...saved, requestId: found.id}; setTicket(saved); open(saved); return}
        if (checkOnly) {setError('尚未找到这次写作请求，可用原请求继续。'); return}
      }
      setStage('正在保存摘录并整理写作材料……')
      savingMaterials = true
      const prepared = await preparePaperDraft({projectId, manuscriptId: saved.manuscriptId, input: saved.input, references: saved.references, attemptKey: saved.key, signal})
      savingMaterials = false
      signal.throwIfAborted()
      onPrepared(prepared.root)
      saved = {...saved, preparedId: prepared.manuscriptId, revision: prepared.version.revision}
      setTicket(saved); setStage('正在提交正文写作……')
      const written = await submitPaperDraft({projectId, manuscriptId: prepared.manuscriptId, version: prepared.version, attemptKey: saved.key, signal, sciSettings})
      signal.throwIfAborted()
      saved = {...saved, requestId: written.id}; setTicket(saved); open(saved)
    } catch (issue) {
      if (signal.aborted) return
      setError(safeError(issue, '写作请求未确认，请用原请求继续。'))
      if (!checkOnly && (isPaperDraftRejected(issue) || savingMaterials && issue instanceof TaskRequestError && issue.status >= 400 && issue.status < 500 && issue.status !== 408)) {
        setTicket(null); onRefresh()
      }
    } finally {if (operation.current === controller) {operation.current = null; setStage('')}}
  }

  return <section className="paper-draft-composer" aria-label={t('撰写初稿')}>
    <header><h3>{t('撰写初稿')}</h3><p>{input.title}</p></header>
    {finished && ticket ? <div className="paper-draft-submit">
      <p>{t('这次初稿已提交，可查看生成进度和正文。')}</p>
      <button type="button" className="button-primary" onClick={() => open(ticket)}>{t('查看这次初稿')}</button>
      <button type="button" onClick={() => {setTicket(null); setConsent(false); setError('')}}>{t('准备新的初稿')}</button>
    </div> : <>
    <section className="paper-draft-materials">
      <div className="paper-draft-heading"><h4>{t('本次写作材料')}</h4>{onOpenMaterials && <button type="button" className="button-quiet" disabled={locked} onClick={onOpenMaterials}>{t('管理上传材料')}</button>}</div>
      <p>{[t(school ? '毕业论文' : review ? '综述' : '研究型论文'), t(input.output_language === 'en' ? '英文' : '中文'),
        ...(plan?.keywords ?? sciSettings?.keywords ?? [])].join(' · ')}</p>
      {!!plan?.sections.length && <ul className="paper-draft-plan">{plan.sections.map(s => <li key={s.id}><strong>{s.label}</strong>{s.text && <span>{s.text}</span>}</li>)}</ul>}
      {!!plan?.materials.length && <ul>{plan.materials.map((m,i) => <li key={m.section_id + i}>{m.filename} · {m.result || t('已关联章节')}</li>)}</ul>}
      {!!baseInput.sources.length && <p>{t('已沿用上次保存的来源')} · {baseInput.sources.map(s => candidates.items.find(x => sourceKey(x) === sourceKey(s))?.label ?? last?.snapshot.sources.find(x => x.id === s.id)?.label ?? s.id).join('、')}</p>}
      {!!options.length && <div className="paper-draft-files">{options.map(file => <label key={file.file_id}>
        <input type="checkbox" disabled={locked} checked={!choices.omittedFiles.includes(file.file_id)}
          onChange={e => edit({omittedFiles: e.target.checked ? choices.omittedFiles.filter(id => id !== file.file_id) : [...choices.omittedFiles, file.file_id]})}/>
        {parsedMaterialLabel(file) ?? file.label}{file.kind === 'original' && <small>{t(/\.(docx|xlsx)$/i.test(file.label) ? '等待可读版本' : '图片原件')}</small>}</label>)}</div>}
      {pendingUploads.length > 0 && <button type="button" className="button-quiet" disabled={locked} onClick={onRefresh}>{t('刷新文件状态')}</button>}
      {onOpenRequirements && planUnavailable && <button type="button" onClick={onOpenRequirements}>{t('填写写作要求')}</button>}
      {school && !readiness?.ready && onOpenSchoolTemplate && <button type="button" onClick={onOpenSchoolTemplate}>{t('确认学校模板')}</button>}
      {school && readiness?.ready && input.thesis && <div className="paper-draft-chapters"><strong>{t('学校模板章节')}</strong>
        {input.thesis.chapter_mappings.map((m,index) => {const name = readiness.chapters[index].title
          const key = readiness.confirmation_id + '/' + m.chapter_id
          return !m.purpose || choices.chapterPurposes[key] ? <label key={key}>{name}<select value={m.purpose} disabled={locked} onChange={e => edit({chapterPurposes: {...choices.chapterPurposes, [key]: e.target.value as SchoolPurpose}})}>
            <option value="">{t('选择章节用途')}</option>{schoolPurposes.map(p => <option key={p} value={p}>{t(purposeLabels[p])}</option>)}</select></label> : <span key={key}>{name}</span>
        })}</div>}
      {needResult && <div className="paper-draft-result"><label>{t('主要结果')}<textarea rows={2} maxLength={20000} disabled={locked}
        value={choices.resultText ?? baseInput.reported_result?.text ?? ''} onChange={e => edit({resultText: e.target.value})}/></label>
        <label>{t('这项结果来自哪个文件？')}<select disabled={locked} value={choices.resultSource ?? baseInput.reported_result?.source_ids[0] ?? ''}
          onChange={e => edit({resultSource: e.target.value})}><option value="">{t('选择文件')}</option>{resultSources.map(s => <option key={sourceKey(s)} value={s.id}>{parsedMaterialLabel(s) ?? s.label}</option>)}</select></label></div>}
    </section>
    {!!frozenCount && <p>{t(choices.references.length ? '本次使用新勾选的摘录，之前的引用保留在历史稿件中。' : '沿用已有的 {count} 段核对摘录。', {count: frozenCount})}</p>}
    <ManuscriptReferencePicker projectId={projectId} active={active} disabled={locked} onFindLiterature={onFindLiterature} selected={choices.references} onChange={references => edit({references})}/>
    <div className="paper-draft-submit">
      {!ticket && missing && <p>{t(missing)}</p>}
      <p>{t('所选材料和摘录将发送给外部写作服务。生成记录由服务商保存，生成正文会产生写作费用。')}</p>
      <label><input type="checkbox" checked={consent} disabled={!!stage} onChange={e => setConsent(e.target.checked)}/>{t('我确认用以上材料生成正文，接受本次写作费用和外部保存。')}</label>
      {error && <p role="alert" className="error-panel">{t(error)}</p>}
      {stage && <p role="status">{t(stage)}</p>}
      <div className="manuscript-actions"><button type="button" className="button-primary" disabled={!!stage || !consent || (!ticket && !!missing)} onClick={() => void run()}>{t(ticket ? '用原请求继续' : '生成正文初稿')}</button>
        {ticket?.preparedId && <button type="button" disabled={!!stage} onClick={() => void run(true)}>{t('查看提交结果')}</button>}
      </div>
    </div></>}
  </section>
}
