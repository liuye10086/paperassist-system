import { useEffect, useRef, useState, type Ref } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { useI18n } from '../../shared/i18n'
import BioUpload from '../bioinformatics/BioUpload'
import BatchUpload from '../files/BatchUpload'
import type { MaterialHistory } from '../files/UploadHistory'
import { parseStatusLabels, type FilePage } from '../files/fileLibraryApi'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import type { AnalysisPick } from './CustomerAnalysisResults'
import { SupplementForm, SupplementRequest, type ClosedSupplement } from './CustomerSupplement'
import { customerBase, type Progress } from './customerWorkspaceApi'
import PaperMaterialEditor from './PaperMaterialEditor'
import SciFileNote from './SciFileNote'
import { paperMaterialKind, paperMaterialsUrl, useMaterialAnalysisPicks, type PaperFile, type PaperMaterialNote, type PaperMaterialsRead, type PaperMaterialTarget } from './paperMaterials'
import ReturnBar from './ReturnBar'
import type { ReturnTarget } from './returnToken'

const uploadKinds = [['documents', '文档与图片'], ['bio', '测序数据与样本表']] as const
const pageSize = 5
const fileNatures: Record<string, string> = {
  docx: 'Word 文档', xlsx: 'Excel 表格', pdf: 'PDF 文档',
  png: '图片', jpg: '图片', jpeg: '图片', tif: '图片', tiff: '图片',
  bio_bundle: '测序数据包', bio_component: '测序文件',
}
// A supplement holds at most 50 files (接口设计第二节 2); newer uploads come first.
const supplementPageSize = 50

/** Supplement mode (`step=upload&mode=supplement`): the analyst asked for more materials. */
export type SupplementMode = {
  /** Set only when the page was reached with a valid return token. */
  returnTarget: ReturnTarget | null
  onReturn: (href: string) => void
  onSubmitted: () => void
  onProgress: () => void
}

type MaterialsProps = {
  projectId: string
  headingRef?: Ref<HTMLHeadingElement>
  registerLeaveGuard: RegisterLeaveGuard
  forWriting?: 'sci' | 'thesis'
  onRequirements?: () => void
  active?: boolean
  supplement?: SupplementMode
  /** Called once a file appears that was not on the first page when it was first read (B03 task 7). */
  onUploaded?: () => void
  /** Analysis results downloaded in this browser tab (B05 task 6): a file with the same name shows where it came from. */
  analysisPicks?: AnalysisPick[]
  onAnalysisResults?: () => void
  analysisResultsRef?: Ref<HTMLButtonElement>
}

type UploadActions = {onContinue: () => void; onUnavailable: () => void}
type MaterialsView = ({kind: 'upload'} & UploadActions) | {kind: 'organizer'; chapterRevision: number}

export function ThesisMaterialOrganizer({projectId, registerLeaveGuard, chapterRevision = 0}: {
  projectId: string; registerLeaveGuard: RegisterLeaveGuard; chapterRevision?: number
}) {
  const [picks] = useMaterialAnalysisPicks(projectId)
  return <MaterialsContent projectId={projectId} forWriting="thesis" registerLeaveGuard={registerLeaveGuard}
    analysisPicks={picks} view={{kind:'organizer', chapterRevision}} />
}

export default function CustomerMaterials({onContinue, onUnavailable, ...props}: MaterialsProps & UploadActions) {
  return <MaterialsContent {...props} view={{kind:'upload', onContinue, onUnavailable}} />
}

function MaterialsContent({ projectId, headingRef, view, registerLeaveGuard, forWriting, onRequirements, active = true, supplement, onUploaded, analysisPicks = [], onAnalysisResults, analysisResultsRef }: MaterialsProps & {view: MaterialsView}) {
  const { t } = useI18n()
  const simpleSci = forWriting === 'sci' && !onRequirements
  const thesis = forWriting === 'thesis'
  const organizing = view.kind === 'organizer'
  const supplementing = !!supplement && !forWriting
  const groupUploads = view.kind === 'upload' && !supplementing
  const groupWritingUploads = groupUploads && !!forWriting
  const inlineNotes = simpleSci || organizing
  const [noteFile, setNoteFile] = useState<string | null>(null)
  const [kind, setKind] = useState<'documents' | 'bio'>('documents')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<{ file: PaperFile; note?: PaperMaterialNote; targets: PaperMaterialTarget[]; prefill?: string } | null>(null)
  const filesUrl = projectBase(projectId) + '/files'
  const historyFilter = kind === 'documents' ? 'outside_document_batches=true' : 'outside_batch_profile=bioinformatics_v1'
  const files = useResearchRead<FilePage>(`${filesUrl}?page=${page}&page_size=${pageSize}${groupUploads ? `&${historyFilter}` : ''}`, active)
  const recentUploads = useResearchRead<FilePage>(`${filesUrl}?page=1&page_size=${pageSize}`, active && groupUploads && !!onUploaded)
  const pages = Math.max(1, Math.ceil((files.data?.total ?? 0) / pageSize))
  const eligibleIds = forWriting ? files.data?.items.filter(file => {
    const material = paperMaterialKind(file)
    return material && (forWriting !== 'sci' || material === 'table')
  }).map(file => file.id) ?? [] : []
  const notes = useResearchRead<PaperMaterialsRead>(paperMaterialsUrl(projectId, groupWritingUploads ? [] : eligibleIds),
    active && (groupWritingUploads || eligibleIds.length > 0), undefined, view.kind === 'organizer' ? view.chapterRevision : 0)
  const noteByFile = new Map(notes.data?.items.map(item => [item.file_id, item]))
  const [closed, setClosed] = useState<ClosedSupplement | null>(null)
  // Newest files first, independent of the history page the customer is looking at.
  const recent = useResearchRead<FilePage>(`${filesUrl}?page=1&page_size=${supplementPageSize}`, active && supplementing)
  const progress = useResearchRead<Progress>(customerBase(projectId) + '/progress', active && supplementing)
  const supplementVersion = !closed && !progress.error && progress.data?.status === 'needs_materials'
    ? progress.data.requirement_version : null
  const refreshFiles = () => {
    files.refresh()
    if (groupUploads && onUploaded) recentUploads.refresh()
    if (supplementing) recent.refresh()
  }
  const uploadProps = { projectId, embedded: true, customerView: true, registerLeaveGuard, onChanged: refreshFiles }
  // Newest files come first, so a new upload shows on page 1. Files already there when the page opened do not count.
  const knownFiles = useRef<Set<string> | null>(null)
  const uploaded = useRef(onUploaded)
  useEffect(() => { uploaded.current = onUploaded })
  const observedUploads = groupUploads ? recentUploads : files
  useEffect(() => {
    if (!onUploaded || (!groupUploads && page !== 1) || !observedUploads.data || observedUploads.error) return
    const ids = observedUploads.data.items.map(file => file.id)
    if (!knownFiles.current) { knownFiles.current = new Set(ids); return }
    const known = knownFiles.current
    if (!ids.some(id => !known.has(id))) return
    ids.forEach(id => known.add(id))
    uploaded.current?.()
  }, [groupUploads, observedUploads.data, observedUploads.error, onUploaded, page])

  function describeFile(id: string | null, filename: string, fileType: string) {
    const template = thesis && id && notes.data?.template_source_file_ids?.includes(id)
    const nature = t(template ? '学校模板' : (fileNatures[fileType] ?? '文件'))
    if (!id) return { nature }

    const file = { id, filename, file_type: fileType }
    const kind = paperMaterialKind(file)
    const allowsNotes = !!kind && (forWriting !== 'sci' || kind === 'table')
    const note = template || !allowsNotes ? undefined : noteByFile.get(id)
    const figure = organizing && kind === 'figure'
    const linkedTable = organizing && kind === 'table' && !!(note?.target_id || note?.worksheet_names?.length)
    const useEditor = linkedTable || !!(onRequirements && forWriting && !thesis && !inlineNotes)
    const chooseWorksheets = organizing && file.file_type === 'xlsx' && !template && !linkedTable && !!notes.data?.targets.length
    const pick = forWriting ? analysisPicks.find(item => item.memberNames.includes(file.filename)) : undefined
    const source = pick ? t('来自 {project} · {delivery}', { project: pick.researchProjectName, delivery: pick.deliveryTitle }) : ''
    const chapter = figure && (note?.target_available && note.target_label
      ? t('配图章节 · {name}', { name: note.target_label })
      : note?.target_id && note.target_label ? t('原章节「{name}」已变更，将自动安排', { name: note.target_label })
        : t('配图章节 · 自动安排'))
    const context = [template && !groupWritingUploads && t('学校模板'), chapter,
      note && useEditor && (note.target_label && note.target_available ? note.target_label : t('待关联')), source]
      .filter(Boolean).join(' · ')
    const description = inlineNotes && noteFile === id
      ? <SciFileNote key={id} projectId={projectId} file={file} note={note} prefill={source}
          figureTargets={figure ? (thesis ? notes.data?.figure_targets ?? [] : notes.data?.targets) : undefined}
          registerLeaveGuard={registerLeaveGuard} onDone={saved => { setNoteFile(null); if (saved) notes.refresh() }} />
      : inlineNotes && note?.result ? <p>{note.result}</p> : null
    const actions = <>
      {inlineNotes && !template && !useEditor && allowsNotes && noteFile !== id &&
        <button type="button" className="button-quiet" disabled={!notes.data || notes.loading || !!notes.error || noteFile !== null}
          onClick={() => setNoteFile(id)}>{t(figure ? '设置配图' : note ? '编辑说明' : '添加说明')}</button>}
      {(useEditor || chooseWorksheets) && allowsNotes && <button type="button" className="button-quiet"
        disabled={!notes.data || !!notes.error || noteFile !== null}
        aria-label={chooseWorksheets ? undefined : t(note ? '编辑 {name} 的图表资料' : '填写 {name} 的图表资料', { name: filename })}
        onClick={() => {
          if (notes.data) setEditing({ file, note, targets: notes.data.targets, prefill: source || undefined })
        }}>{t(chooseWorksheets ? '入稿工作表' : note ? '编辑图表资料' : '填写图表资料')}</button>}
    </>
    return { nature, context, description, actions,
      details: context || description ? <>{context && <p className="muted">{context}</p>}{description}</> : null }
  }

  const filePagination = !editing && files.data && (page > 1 || pages > 1) && <nav className="customer-pagination" aria-label={t('文件分页')}>
    <button type="button" onClick={() => setPage(value => value - 1)} disabled={page <= 1 || files.loading || noteFile !== null}>{t('上一页')}</button>
    <span>{t('第 {page} / {pages} 页 · 共 {count} 个文件', { page, pages, count: files.data.total })}</span>
    <button type="button" onClick={() => setPage(value => value + 1)}
      disabled={page >= pages || files.loading || noteFile !== null}>{t('下一页')}</button>
  </nav>
  const notesError = (groupWritingUploads || eligibleIds.length > 0) && notes.error && <p role="alert" className="error-panel">{t(notes.error)}{' '}
    <button type="button" onClick={notes.refresh}>{t('重新读取图表资料')}</button>
  </p>
  const fileReadStatus = <>
    {files.error && <p role="alert" className="error-panel">{t(files.error)}</p>}
    {notesError}
    {!files.data && !files.error && <p role="status">{t('正在读取文件列表……')}</p>}
  </>
  const materialHistory: MaterialHistory | undefined = groupUploads ? {
    otherFiles: files.error ? [] : files.data?.items ?? [],
    ready: !!files.data && !files.error,
    status: fileReadStatus,
    pagination: filePagination,
    editing: noteFile !== null,
    refresh: () => { refreshFiles(); if (groupWritingUploads) notes.refresh() },
    describe: describeFile,
  } : undefined

  const FileListHeading = organizing ? 'h2' : 'h3'
  return <div className="customer-section customer-materials" hidden={!active}>
    {supplementing && <ReturnBar target={supplement.returnTarget} onReturn={supplement.onReturn}>
      {t('正在为“{place}”补充资料', { place: supplement.returnTarget?.label ?? '' })}
    </ReturnBar>}
    {view.kind === 'upload' && <div className="customer-section-heading">
      {forWriting && !simpleSci && !thesis ? <h2>{t('上传写作资料')}</h2> :
        <h1 ref={headingRef} tabIndex={-1} className={supplementing ? undefined : 'visually-hidden'}>{t(supplementing ? '补交资料' : '上传资料')}</h1>}
    </div>}
    {supplementing && <SupplementRequest progress={progress.data} error={progress.error} closed={closed}
      onRetry={progress.refresh} onProgress={supplement.onProgress} />}
    <div className="customer-materials-body" tabIndex={0} role="region" aria-label={t(organizing ? '已上传资料' : supplementing ? '补交资料' : '上传资料')}>
      {editing && <PaperMaterialEditor key={editing.file.id} projectId={projectId}
        original={editing.file} note={editing.note} targets={notes.data?.targets ?? editing.targets} prefill={editing.prefill} registerLeaveGuard={registerLeaveGuard}
        onBack={() => setEditing(null)} onSaved={notes.refresh} onRequirements={onRequirements} />}
      <div hidden={!!editing}>
      {view.kind === 'upload' && (!supplementing || supplementVersion != null) && <>
        {!forWriting && <div className="customer-switches" role="group" aria-label={t('资料类型')}>
          {uploadKinds.map(([value, label]) => <button type="button" key={value} aria-pressed={kind === value}
            className="button-quiet" onClick={() => {
              setKind(value)
              if (!supplementing && value !== kind) setPage(1)
            }}>{t(label)}</button>)}
        </div>}
        <div hidden={kind !== 'documents'}>
          {onAnalysisResults && <button ref={analysisResultsRef} type="button" className="button-accent" onClick={onAnalysisResults}>{t('从我的分析项目取用成果')}</button>}
          <BatchUpload {...uploadProps} active={active && !editing && kind === 'documents'} onUnavailable={view.onUnavailable}
            writingMaterials={forWriting} materialHistory={kind === 'documents' ? materialHistory : undefined} />
        </div>
        {!forWriting && <div hidden={kind !== 'bio'}>
          <BioUpload {...uploadProps} active={active && !editing && kind === 'bio'} materialHistory={kind === 'bio' ? materialHistory : undefined} />
        </div>}
      </>}
      {supplementing && supplementVersion != null && <>
        {recent.error && <p role="alert" className="error-panel">{t(recent.error)}</p>}
        <SupplementForm key={supplementVersion} projectId={projectId} version={supplementVersion} recent={recent.data?.items ?? null}
          onClosed={reason => { setClosed(reason); if (reason.kind === 'revision') progress.refresh() }} onSubmitted={supplement.onSubmitted} />
      </>}
      {!groupUploads && <>
      <div className="customer-section-heading customer-material-history">
        <FileListHeading>{t(supplementing ? '项目里已有的文件' : '已上传资料')}</FileListHeading>
        {(!organizing || files.error) && <button type="button" className="button-quiet" disabled={files.loading} onClick={() => {
          refreshFiles()
          if ((inlineNotes || thesis) && eligibleIds.length > 0) notes.refresh()
        }}>{t('刷新资料')}</button>}
      </div>
      {fileReadStatus}
      {files.data && !files.error && (files.data.items.length === 0
        ? <p>{t('此项目还没有文件。')}</p>
        : <ul className={organizing ? 'customer-list customer-card-list' : 'customer-list'} aria-label={t('已上传资料')}>
          {files.data.items.map(file => {
            const material = describeFile(file.id, file.filename, file.file_type)
            return <li key={file.id}>
              <div><strong>{file.filename}</strong><p className="muted">
                {t(file.parse_status === 'stored' ? '已上传' : parseStatusLabels[file.parse_status])}
                {material.context && <> · {material.context}</>}
              </p>{material.description}
              </div>
              <div className="sci-inline-controls">
                {material.actions}
                <ProjectDownloadLink href={`${filesUrl}/${encodeURIComponent(file.id)}/download`} filename={file.filename}
                  ariaLabel={t('下载 {name}', { name: file.filename })}>{t('下载原文件')}</ProjectDownloadLink>
              </div>
            </li>
          })}
        </ul>)}
      </>}
      </div>
    </div>
    {!groupUploads && filePagination}
    {view.kind === 'upload' && !supplementing && <footer className="customer-step-actions">
      <button type="button" className="button-primary" disabled={noteFile !== null} onClick={view.onContinue}>
        {t(thesis || simpleSci ? '下一步 图件拼版' : forWriting ? '下一步 稿件与复核' : '下一步 选择需求')}
      </button>
    </footer>}
  </div>
}
