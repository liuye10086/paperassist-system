import { Fragment, useId, useState } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { useI18n } from '../../shared/i18n'
import { taskStatusLabel } from '../../shared/i18n/protocolLabels'
import { readingScopeLabels } from '../manuscripts/ParagraphReferenceExcerpts'
import ManuscriptImage from '../manuscripts/ManuscriptImage'
import type { Snapshot } from '../manuscripts/manuscriptTypes'
import { projectBase, RESEARCH_TIMEOUT_MS, useResearchRead } from '../research-results/api'
import TaskPendingAction from '../tasks/TaskPendingAction'
import { taskErrorMessage } from '../tasks/taskApi'
import { isWorkspace, type TaskStatus, type TaskWorkspace } from '../tasks/taskTypes'
import './sciDraftReader.css'

type Props = { projectId: string; manuscriptId: string; revision: number; requestId: string; thesis?: boolean; onRevise: () => void }
type Citation = {
  number: number; project_reference_id: string; title: string
  excerpts: {id: string; quote: string; reading_scope: keyof typeof readingScopeLabels}[]
}
type Group = Pick<Snapshot['results_groups'][number], 'id' | 'title' | 'tables' | 'figures'>
type Paragraph = { id: string; parts: {text: string; citations: Citation[]}[]; figures?: Group['figures'] }
type Section = { id: string; heading: string; level: number; purpose?: string; output_language?: 'zh-CN' | 'en'
  paragraphs: Paragraph[]; groups: Group[]; keywords?: string[] }
type Draft = {
  title: string; english_title?: string; output_language: 'en' | 'zh-CN'; sections: Section[]; keywords: string[]; acknowledgements: string
  references: {number: number; project_reference_id: string; text: string}[]
}
type Change = {section_id: string; heading: string; before: string[]; after: string[]; paragraph_ids: string[]}
type Detail = { project_id: string; manuscript_id: string; request_id: string; revision: number; status: TaskStatus
  error_code: string | null; draft: Draft | null; previous_request_id: string | null; changes: Change[]; can_revise: boolean }
const inProgress = (item: Detail) => item?.status === 'queued' || item?.status === 'running'

type FigureView = {reader: string; revision: number; english: boolean}

function DraftFigure({figure, reader, revision, english}: FigureView & {figure: Group['figures'][number]}) {
  return <figure className="sci-review-figure">
    <ManuscriptImage url={`${reader}/figures/${figure.number}?revision=${revision}`} title={figure.title} timeoutMs={RESEARCH_TIMEOUT_MS}/>
    <figcaption><strong>{english ? 'Figure' : '图'} {figure.number} {figure.title}</strong>
      <p>{figure.caption}</p>{figure.panels?.map((panel, i) => <p key={i}><b>{panel.label}</b> {panel.description}</p>)}
    </figcaption>
  </figure>
}

function Illustrations({group, section, reader, revision, english}: FigureView & {group: Group; section: Section}) {
  return <section className="sci-draft-illustrations">
    {section.heading !== group.title && <h4>{group.title}</h4>}
    {group.tables.map(table => <div key={table.id} className="field-table-scroll"><table className="field-table">
      <caption>{table.title}</caption>
      <thead><tr>{table.columns.map((column, i) => <th key={i} scope="col">{column}</th>)}</tr></thead>
      <tbody>{table.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody>
    </table></div>)}
    {group.figures.map(figure => <DraftFigure key={figure.id} figure={figure} reader={reader} revision={revision} english={english}/>)}
  </section>
}

function DraftParagraph({paragraph, title, changed}: {paragraph: Paragraph; title: boolean; changed: boolean}) {
  const { t } = useI18n()
  const [selected, setSelected] = useState<{part: number; citation: Citation} | null>(null)
  const excerptId = useId()
  const Body = title ? 'h2' : 'p'
  return <div className={changed ? 'sci-draft-paragraph sci-draft-modified' : 'sci-draft-paragraph'}>
    <Body>{paragraph.parts.map((part, index) => <Fragment key={index}>{part.text}{part.citations.map(citation => {
      const open = selected?.part === index && selected.citation.number === citation.number
      return <button key={citation.number} type="button" className="sci-draft-citation"
        aria-expanded={open} aria-controls={open ? excerptId : undefined}
        onClick={() => setSelected(open ? null : {part: index, citation})}>[{citation.number}]</button>
    })}</Fragment>)}</Body>
    {selected && <aside id={excerptId} className="sci-draft-excerpt">
      <strong>[{selected.citation.number}] <span>{selected.citation.title}</span></strong>
      {selected.citation.excerpts.map(e => <blockquote key={e.id}>
        <small>{t('初稿关联的原文摘录')} · {t(readingScopeLabels[e.reading_scope])}</small><p>{e.quote}</p>
      </blockquote>)}
    </aside>}
  </div>
}

function DraftKeywords({section, draft, thesis}: {section: Section; draft: Draft; thesis: boolean}) {
  if ((section.purpose ?? section.id) !== 'abstract') return null
  const language = section.output_language ?? draft.output_language
  const keywords = section.keywords ?? (!thesis || language === draft.output_language ? draft.keywords : [])
  return keywords.length > 0
    ? <p><strong>{language === 'en' ? 'Keywords: ' : '关键词：'}</strong>{keywords.join(language === 'en' ? ', ' : '、')}</p>
    : null
}

function Recovery({projectId, requestId, refresh}: {projectId: string; requestId: string; refresh: () => void}) {
  const { t } = useI18n()
  const recovery = useResearchRead<TaskWorkspace>(`/api/v1/tasks/${encodeURIComponent(requestId)}/workspace`, true)
  if (recovery.error) return <p role="alert">{t(recovery.error)} <button onClick={recovery.refresh}>{t('重试')}</button></p>
  const workspace = recovery.data
  if (!isWorkspace(workspace, projectId, requestId) || workspace.task.task_type !== 'manuscript_writing') return null
  return <TaskPendingAction workspace={workspace} blocked={recovery.loading} customerView
    onChanged={() => { recovery.refresh(); refresh() }}/>
}

function Reader({ projectId, manuscriptId, revision, requestId, thesis, onRevise }: Props) {
  const { t } = useI18n()
  const [downloaded, setDownloaded] = useState(false)
  const base = `${projectBase(projectId)}/manuscripts/${encodeURIComponent(manuscriptId)}/writing-requests/${encodeURIComponent(requestId)}/draft-reader`
  const result = useResearchRead<Detail>(`${base}?revision=${revision}`, true, inProgress)
  const detail = result.data
  const wrongRequest = detail && (detail.request_id !== requestId || detail.revision !== revision ||
    detail.project_id !== projectId || detail.manuscript_id !== manuscriptId)
  if (result.error || wrongRequest || (detail?.status === 'succeeded' && !detail.draft)) return <p role="alert" className="error-panel">
    {t(result.error || '指定初稿暂时无法读取。')} <button onClick={result.refresh}>{t('重试')}</button>
  </p>
  if (!detail) return <p role="status">{t('正在读取初稿……')}</p>
  if (!detail.draft || detail.status !== 'succeeded') return <section className="manuscript-panel">
    {inProgress(detail) ? <p role="status">{t(detail.status === 'queued' ? '初稿已排队，完成后将自动显示。' : '正在生成正文，完成后将自动显示。')}</p>
      : <><p role="status">{t('写作任务')} · {taskStatusLabel(detail.status)}</p>
        {detail.error_code && <p role="alert">{t(taskErrorMessage(detail.error_code, '任务暂未完成，请查看处理说明。', true))}</p>}
        {['failed', 'waiting_confirmation', 'waiting_input'].includes(detail.status) &&
          <Recovery projectId={projectId} requestId={requestId} refresh={result.refresh}/>}</>}
    <button type="button" className="button-quiet" onClick={result.refresh}>{t('重新读取')}</button>
  </section>
  const draft = detail.draft
  const en = draft.output_language === 'en'
  const changedIds = new Set(detail.changes.flatMap(change => change.paragraph_ids))
  const bibliography = draft.references.length > 0 && <ol className="sci-draft-references">{draft.references.map(ref =>
    <li key={ref.project_reference_id} value={ref.number}>[{ref.number}] {ref.text}</li>)}</ol>
  return <section className="sci-draft-reader">
    <div className="sci-draft-actions">
      <ProjectDownloadLink href={`${base}/word?revision=${revision}`} filename={draft.title.slice(0, 80).replace(/[\\/]/g, '-') + '.docx'}
        timeoutMs={RESEARCH_TIMEOUT_MS} onDownloaded={() => setDownloaded(true)}>{t(thesis ? '按学校模板下载 Word' : '下载 Word')}</ProjectDownloadLink>
      {detail.can_revise && <button type="button" onClick={onRevise}>{t(thesis ? '按导师意见修改' : '修改初稿')}</button>}
    </div>
    {downloaded && <p role="status">{t('Word 已交给浏览器下载。')}</p>}
    {detail.previous_request_id && <details className="sci-draft-changes">
      <summary>{t('查看修改处')}</summary>
      <a href={'#' + new URLSearchParams({'customer-project': projectId, step:'manuscripts', view:'writing',
        manuscript: manuscriptId, revision: String(revision), writingRequest: detail.previous_request_id})}>{t('阅读修改前的全文')}</a>
      {detail.changes.map((change, index) => <section key={index}>
        <h3>{change.heading}</h3>
        {change.before.length > 0 && <><strong>{t('修改前')}</strong>{change.before.map((text, i) => <p key={i}>{text}</p>)}</>}
        {change.after.length > 0 && <><strong>{t('修改后')}</strong>{change.after.map((text, i) => <p key={i}>{text}</p>)}</>}
      </section>)}
    </details>}
    <article lang={draft.output_language} className="sci-draft-body">
      {thesis && <h2>{draft.title}</h2>}
      {draft.sections.map(section => <section key={section.id} lang={section.output_language}>
        {(thesis || section.id !== 'title') && (section.level === 1 ? <h3>{section.heading}</h3>
          : <h4 aria-level={section.level + 2}>{section.heading}</h4>)}
        {thesis && section.purpose === 'abstract' && section.output_language === 'en' && draft.english_title &&
          <p className="sci-draft-english-title"><strong>{draft.english_title}</strong></p>}
        {section.paragraphs.map(p => <Fragment key={p.id}>
          <DraftParagraph paragraph={p} title={!thesis && section.id === 'title'} changed={changedIds.has(p.id)}/>
          {p.figures?.map(figure => <DraftFigure key={figure.id} figure={figure} reader={base} revision={revision} english={(section.output_language ?? draft.output_language) === 'en'}/>)}
        </Fragment>)}
        <DraftKeywords section={section} draft={draft} thesis={!!thesis}/>
        {section.purpose === 'references' && bibliography}
        {section.groups.map(group => <Illustrations key={group.id} group={group} section={section} reader={base} revision={revision} english={(section.output_language ?? draft.output_language) === 'en'}/>)}
      </section>)}
      {draft.acknowledgements && <section><h3>{en ? 'Acknowledgements' : '致谢'}</h3><p>{draft.acknowledgements}</p></section>}
      {!draft.sections.some(s => s.purpose === 'references') && bibliography && <section><h3>{en ? 'References' : '参考文献'}</h3>
        {bibliography}
      </section>}
    </article>
  </section>
}

export function SciDraftReader(props: Props) {
  return <Reader key={JSON.stringify([props.projectId, props.manuscriptId, props.revision, props.requestId])} {...props}/>
}
