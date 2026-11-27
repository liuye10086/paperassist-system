import { Fragment, useId, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import { taskStatusLabel } from '../../shared/i18n/protocolLabels'
import { readingScopeLabels } from '../manuscripts/ParagraphReferenceExcerpts'
import ManuscriptImage from '../manuscripts/ManuscriptImage'
import { RESEARCH_TIMEOUT_MS, useResearchRead } from '../research-results/api'
import TaskPendingAction from '../tasks/TaskPendingAction'
import { taskErrorMessage } from '../tasks/taskApi'
import { isWorkspace, type TaskWorkspace } from '../tasks/taskTypes'
import CustomerDownloadLink from './CustomerDownloadLink'
import SciDraftReplyStream from './SciDraftReplyStream'
import { inProgress, useSciDraftRead, type Citation, type Draft, type DraftChange, type DraftRead, type DraftRequest, type Group, type Paragraph, type Section } from './useSciDraftRead'
import './sciDraftReader.css'

type Props = DraftRequest & { thesis?: boolean; onRevise?: () => void }
type RevisionScope = {
  editable: ReadonlySet<string>; selected: ReadonlySet<string>; choosing: boolean; toggle: (sectionId: string) => void
  focus?: (sectionId: string) => void
}

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

function DraftParagraph({paragraph, titleLevel, changed}: {paragraph: Paragraph; titleLevel?: number; changed: boolean}) {
  const { t } = useI18n()
  const [selected, setSelected] = useState<{part: number; citation: Citation} | null>(null)
  const excerptId = useId()
  const Body = titleLevel !== undefined ? 'h2' : 'p'
  return <div className={changed ? 'sci-draft-paragraph sci-draft-modified' : 'sci-draft-paragraph'}>
    <Body aria-level={titleLevel === undefined ? undefined : titleLevel + 2}>{paragraph.parts.map((part, index) => <Fragment key={index}>{part.text}{part.citations.map(citation => {
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

function DraftHeading({heading, level}: {heading: string; level: number}) {
  return level === 1 ? <h3>{heading}</h3> : <h4 aria-level={level + 2}>{heading}</h4>
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

export function SciDraftProgress({projectId, requestId, read, reply = false, sections = [], onReveal}: Pick<DraftRequest,'projectId' | 'requestId'> & {
  read: DraftRead; reply?: boolean; sections?: Pick<Section, 'id' | 'heading'>[]; onReveal?: () => void
}) {
  const { t } = useI18n()
  const { data: detail, error, refresh } = read
  if (error) return <p role="alert" className={reply ? 'sci-revision-reply' : 'error-panel'}>
    {t(error)} {!reply && <button onClick={refresh}>{t('重试')}</button>}
  </p>
  if (!detail) return <p role="status" className={reply ? 'sci-revision-reply' : undefined}>
    {t(reply ? '正在读取修改进度……' : '正在读取初稿……')}
  </p>
  const status = detail.draft_advice
    ? detail.status === 'queued' ? '建议请求已排队。' : '正在整理修改建议……'
    : detail.previous_request_id
      ? detail.status === 'queued' ? '修改稿已排队。' : '正在按意见修改初稿……'
      : detail.status === 'queued' ? '初稿已排队，完成后将自动显示。' : '正在生成正文，完成后将自动显示。'
  const partials = reply ? detail.partial_reply ?? [] : []
  return <section className={reply ? 'sci-revision-reply sci-revision-progress' : 'manuscript-panel'}>
    {inProgress(detail) ? <>
      <p role="status">{t(status)}</p>
      {partials.length > 0 && <SciDraftReplyStream key={requestId} parts={partials} sections={sections} onReveal={onReveal}/>}
    </>
      : <><p role="status">{t('写作任务')} · {taskStatusLabel(detail.status)}</p>
        {detail.error_code && <p role="alert">{t(taskErrorMessage(detail.error_code, '任务暂未完成，请查看处理说明。', true))}</p>}
        {['failed', 'waiting_confirmation', 'waiting_input'].includes(detail.status) &&
          <Recovery projectId={projectId} requestId={requestId} refresh={refresh}/>}</>}
    {!reply && <button type="button" className="button-quiet" onClick={refresh}>{t('重新读取')}</button>}
  </section>
}

export function SciDraftWordDownload({read, thesis}: {read: DraftRead; thesis?: boolean}) {
  const { t } = useI18n()
  const detail = read.data
  if (detail?.status !== 'succeeded' || !detail.draft) return null
  return <CustomerDownloadLink href={`${read.base}/word?revision=${detail.revision}`}
    filename={detail.draft.title.slice(0, 80).replace(/[\\/]/g, '-') + '.docx'} timeoutMs={RESEARCH_TIMEOUT_MS}>
    {t(thesis ? '按学校模板下载 Word' : '下载 Word')}
  </CustomerDownloadLink>
}

export function SciDraftChanges({changes}: {changes: DraftChange[]}) {
  const { t } = useI18n()
  return <>
    {changes.map((change, index) => <section key={index}>
      <h3>{change.heading}</h3>
      {change.before.length > 0 && <><strong>{t('修改前')}</strong>{change.before.map((text, i) => <p key={i}>{text}</p>)}</>}
      {change.after.length > 0 && <><strong>{t('修改后')}</strong>{change.after.map((text, i) => <p key={i}>{text}</p>)}</>}
    </section>)}
  </>
}

export function SciDraftView({ projectId, manuscriptId, revision, requestId, thesis, onRevise, read, bodyOnly, revisionScope }: Props & {
  read: DraftRead; bodyOnly?: boolean; revisionScope?: RevisionScope
}) {
  const { t } = useI18n()
  const { base, data: detail } = read
  if (detail?.status !== 'succeeded' || !detail.draft) return <SciDraftProgress projectId={projectId} requestId={requestId} read={read}/>
  const draft = detail.draft
  const en = draft.output_language === 'en'
  const changedIds = new Set(detail.changes.flatMap(change => change.paragraph_ids))
  const bibliography = draft.references.length > 0 && <ol className="sci-draft-references">{draft.references.map(ref =>
    <li key={ref.project_reference_id} value={ref.number}>[{ref.number}] {ref.text}</li>)}</ol>
  return <section className="sci-draft-reader">
    {!bodyOnly && <div className="sci-draft-actions">
      <SciDraftWordDownload read={read} thesis={thesis}/>
      {detail.can_revise && onRevise && <button type="button" onClick={onRevise}>{t('修改初稿')}</button>}
    </div>}
    {thesis && !bodyOnly && detail.previous_request_id && <details className="sci-draft-changes">
      <summary>{t('查看修改处')}</summary>
      <SciDraftChanges changes={detail.changes}/>
      <a href={'#' + new URLSearchParams({'customer-project': projectId, step:'manuscripts', view:'writing',
        manuscript: manuscriptId, revision: String(revision), writingRequest: detail.previous_request_id})}>{t('阅读修改前的全文')}</a>
    </details>}
    <article lang={draft.output_language} className="sci-draft-body">
      {thesis && <h2>{draft.title}</h2>}
      {draft.sections.map(section => <Fragment key={section.id}>
        <section lang={section.output_language}
          data-sci-revision-section={revisionScope?.editable.has(section.id) ? section.id : undefined}
          data-sci-revision-selected={revisionScope?.selected.has(section.id) ? '' : undefined}
          onClick={revisionScope?.focus && revisionScope.editable.has(section.id) ? event => {
            if (event.target instanceof Element && !event.target.closest('a, button, input') && window.getSelection()?.isCollapsed !== false) {
              revisionScope.focus?.(section.id)
            }
          } : undefined}>
          {revisionScope?.choosing && revisionScope.editable.has(section.id) &&
            <input type="checkbox" className="sci-revision-section-checkbox"
              aria-label={t('选择 {section}', {section:section.heading})} checked={revisionScope.selected.has(section.id)}
              onChange={() => revisionScope.toggle(section.id)}/>}
          {(thesis || section.id !== 'title') && <DraftHeading heading={section.heading} level={section.level}/>}
          {thesis && section.purpose === 'abstract' && section.output_language === 'en' && draft.english_title &&
            <p className="sci-draft-english-title"><strong>{draft.english_title}</strong></p>}
          {section.paragraphs.map(p => <Fragment key={p.id}>
            <DraftParagraph paragraph={p} titleLevel={!thesis && section.id === 'title' ? section.level : undefined} changed={changedIds.has(p.id)}/>
            {p.figures?.map(figure => <DraftFigure key={figure.id} figure={figure} reader={base} revision={revision} english={(section.output_language ?? draft.output_language) === 'en'}/>)}
          </Fragment>)}
          <DraftKeywords section={section} draft={draft} thesis={!!thesis}/>
          {section.purpose === 'references' && bibliography}
          {section.groups.map(group => <Illustrations key={group.id} group={group} section={section} reader={base} revision={revision} english={(section.output_language ?? draft.output_language) === 'en'}/>)}
        </section>
        {!thesis && section.id === 'title' && !!draft.title_fields?.length && <dl className="sci-draft-title-fields">
          {draft.title_fields.map(label => <div key={label}><dt>{label}</dt><dd>{t('在 Word 填写')}</dd></div>)}
        </dl>}
      </Fragment>)}
      {draft.acknowledgements && <section><h3>{en ? 'Acknowledgements' : '致谢'}</h3><p>{draft.acknowledgements}</p></section>}
      {!draft.sections.some(s => s.purpose === 'references') && bibliography && <section>
        <DraftHeading heading={draft.reference_heading?.heading ?? (en ? 'References' : '参考文献')} level={draft.reference_heading?.level ?? 1}/>
        {bibliography}
      </section>}
    </article>
  </section>
}

function Reader(props: Props) {
  const read = useSciDraftRead(props)
  return <SciDraftView {...props} read={read}/>
}

export function SciDraftReader(props: Props) {
  return <Reader key={JSON.stringify([props.projectId, props.manuscriptId, props.revision, props.requestId])} {...props}/>
}
