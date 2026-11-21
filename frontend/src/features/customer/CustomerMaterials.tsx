import { useEffect, useRef, useState, type Ref } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { useI18n } from '../../shared/i18n'
import BioUpload from '../bioinformatics/BioUpload'
import BatchUpload from '../files/BatchUpload'
import { parseStatusLabels, type FilePage } from '../files/fileLibraryApi'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import type { AnalysisPick } from './CustomerAnalysisResults'
import { SupplementForm, SupplementRequest, type ClosedSupplement } from './CustomerSupplement'
import { customerBase, type Progress } from './customerWorkspaceApi'
import PaperMaterialEditor from './PaperMaterialEditor'
import { paperMaterialKind, paperMaterialsUrl, type PaperFile, type PaperMaterialNote, type PaperMaterialsRead, type PaperMaterialTarget } from './paperMaterials'
import ReturnBar from './ReturnBar'
import type { ReturnTarget } from './returnToken'

const uploadKinds = [['documents', '文档与图片'], ['bio', '测序数据与样本表']] as const
const pageSize = 5
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

export default function CustomerMaterials({ projectId, headingRef, onContinue, onUnavailable, registerLeaveGuard, forWriting, onRequirements, active = true, supplement, onUploaded, analysisPicks = [] }: {
  projectId: string
  headingRef?: Ref<HTMLHeadingElement>
  onContinue: () => void
  onUnavailable: () => void
  registerLeaveGuard: RegisterLeaveGuard
  forWriting?: 'sci' | 'thesis'
  onRequirements?: () => void
  active?: boolean
  supplement?: SupplementMode
  /** Called once a file appears that was not on the first page when it was first read (B03 task 7). */
  onUploaded?: () => void
  /** Analysis results downloaded in this browser tab (B05 task 6): a file with the same name shows where it came from. */
  analysisPicks?: AnalysisPick[]
}) {
  const { t } = useI18n()
  const [kind, setKind] = useState<'documents' | 'bio'>('documents')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<{ file: PaperFile; note?: PaperMaterialNote; targets: PaperMaterialTarget[]; prefill?: string } | null>(null)
  const filesUrl = projectBase(projectId) + '/files'
  const files = useResearchRead<FilePage>(`${filesUrl}?page=${page}&page_size=${pageSize}`, active)
  const pages = Math.max(1, Math.ceil((files.data?.total ?? 0) / pageSize))
  const eligibleIds = forWriting ? files.data?.items.filter(paperMaterialKind).map(file => file.id) ?? [] : []
  const notes = useResearchRead<PaperMaterialsRead>(paperMaterialsUrl(projectId, eligibleIds), active && eligibleIds.length > 0)
  const noteByFile = new Map(notes.data?.items.map(item => [item.file_id, item]))
  const supplementing = !!supplement && !forWriting
  const [closed, setClosed] = useState<ClosedSupplement | null>(null)
  // Newest files first, independent of the history page the customer is looking at.
  const recent = useResearchRead<FilePage>(`${filesUrl}?page=1&page_size=${supplementPageSize}`, active && supplementing)
  const progress = useResearchRead<Progress>(customerBase(projectId) + '/progress', active && supplementing)
  const supplementVersion = !closed && !progress.error && progress.data?.status === 'needs_materials'
    ? progress.data.requirement_version : null
  const refreshFiles = () => { files.refresh(); if (supplementing) recent.refresh() }
  const uploadProps = { projectId, embedded: true, customerView: true, registerLeaveGuard, onChanged: refreshFiles }
  // Newest files come first, so a new upload shows on page 1. Files already there when the page opened do not count.
  const knownFiles = useRef<Set<string> | null>(null)
  const uploaded = useRef(onUploaded)
  useEffect(() => { uploaded.current = onUploaded })
  useEffect(() => {
    if (page !== 1 || !files.data || files.error) return
    const ids = files.data.items.map(file => file.id)
    if (!knownFiles.current) { knownFiles.current = new Set(ids); return }
    const known = knownFiles.current
    if (!ids.some(id => !known.has(id))) return
    ids.forEach(id => known.add(id))
    uploaded.current?.()
  }, [files.data, files.error, page])

  return <div className="customer-section customer-materials">
    {supplementing && <ReturnBar target={supplement.returnTarget} onReturn={supplement.onReturn}>
      {t('正在为“{place}”补充资料', { place: supplement.returnTarget?.label ?? '' })}
    </ReturnBar>}
    <div className="customer-section-heading">
      {forWriting ? <h2>{t('上传写作资料')}</h2> : <h1 ref={headingRef} tabIndex={-1}>{t(supplementing ? '补交资料' : '上传资料')}</h1>}
      {!supplementing && <button type="button" className="button-primary" onClick={onContinue}>{t(forWriting === 'thesis' ? '下一步 章节与复核' : forWriting ? '下一步 稿件与复核' : '下一步 选择需求')}</button>}
    </div>
    {supplementing && <SupplementRequest progress={progress.data} error={progress.error} closed={closed}
      onRetry={progress.refresh} onProgress={supplement.onProgress} />}
    <div className="customer-materials-body" tabIndex={0} role="region" aria-label={t(supplementing ? '补交资料' : '上传资料')}>
      {editing && onRequirements && <PaperMaterialEditor key={editing.file.id} projectId={projectId}
        original={editing.file} note={editing.note} targets={editing.targets} prefill={editing.prefill} registerLeaveGuard={registerLeaveGuard}
        onBack={() => setEditing(null)} onSaved={notes.refresh} onRequirements={onRequirements} />}
      <div hidden={!!editing}>
      {(!supplementing || supplementVersion != null) && <>
        {!forWriting && <div className="customer-switches" role="group" aria-label={t('资料类型')}>
          {uploadKinds.map(([value, label]) => <button type="button" key={value} aria-pressed={kind === value}
            className="button-quiet" onClick={() => setKind(value)}>{t(label)}</button>)}
        </div>}
        <div hidden={kind !== 'documents'}>
          <BatchUpload {...uploadProps} active={active && !editing && kind === 'documents'} onUnavailable={onUnavailable} writingMaterials={forWriting} />
        </div>
        {!forWriting && <div hidden={kind !== 'bio'}>
          <BioUpload {...uploadProps} active={kind === 'bio'} />
        </div>}
      </>}
      {supplementing && supplementVersion != null && <>
        {recent.error && <p role="alert" className="error-panel">{t(recent.error)}</p>}
        <SupplementForm key={supplementVersion} projectId={projectId} version={supplementVersion} recent={recent.data?.items ?? null}
          onClosed={reason => { setClosed(reason); if (reason.kind === 'revision') progress.refresh() }} onSubmitted={supplement.onSubmitted} />
      </>}
      <div className="customer-section-heading customer-material-history">
        <h3>{t(supplementing ? '项目里已有的文件' : '已上传资料')}</h3>
        <button type="button" className="button-quiet" disabled={files.loading} onClick={refreshFiles}>{t('刷新资料')}</button>
      </div>
      {files.error && <p role="alert" className="error-panel">{t(files.error)}</p>}
      {eligibleIds.length > 0 && notes.error && <p role="alert" className="error-panel">{t(notes.error)}{' '}
        <button type="button" onClick={notes.refresh}>{t('重新读取图表资料')}</button>
      </p>}
      {!files.data && !files.error && <p role="status">{t('正在读取文件列表……')}</p>}
      {files.data && !files.error && (files.data.items.length === 0
        ? <p>{t('此项目还没有文件。')}</p>
        : <ul className="customer-list" aria-label={t('已上传资料')}>
          {files.data.items.map(file => {
            const note = noteByFile.get(file.id)
            const registration = note ? '编辑图表资料' : '填写图表资料'
            const pick = forWriting ? analysisPicks.find(item => item.memberNames.includes(file.filename)) : undefined
            const source = pick ? t('来自 {project} · {delivery}', { project: pick.researchProjectName, delivery: pick.deliveryTitle }) : ''
            return <li key={file.id}>
              <div><strong>{file.filename}</strong><p className="muted">
                {t(file.parse_status === 'stored' ? '已上传' : parseStatusLabels[file.parse_status])}
                {note && <> · {note.target_label && note.target_available ? note.target_label : t('待关联')}</>}
                {source && <> · {source}</>}
              </p></div>
              <div className="sci-inline-controls">
                {onRequirements && forWriting && paperMaterialKind(file) && <button type="button" className="button-quiet" disabled={!notes.data || !!notes.error}
                  aria-label={t(note ? '编辑 {name} 的图表资料' : '填写 {name} 的图表资料', { name: file.filename })}
                  onClick={() => {
                    if (notes.data) setEditing({ file: { id: file.id, filename: file.filename, file_type: file.file_type }, note,
                      targets: notes.data.targets, prefill: source || undefined })
                  }}>{t(registration)}</button>}
                <ProjectDownloadLink href={`${filesUrl}/${encodeURIComponent(file.id)}/download`} filename={file.filename}
                  ariaLabel={t('下载 {name}', { name: file.filename })}>{t('下载原文件')}</ProjectDownloadLink>
              </div>
            </li>
          })}
        </ul>)}
      </div>
    </div>
    {!editing && files.data && (page > 1 || pages > 1) && <nav className="customer-pagination" aria-label={t('文件分页')}>
      <button type="button" onClick={() => setPage(value => value - 1)} disabled={page <= 1 || files.loading}>{t('上一页')}</button>
      <span>{t('第 {page} / {pages} 页 · 共 {count} 个文件', { page, pages, count: files.data.total })}</span>
      <button type="button" onClick={() => setPage(value => value + 1)}
        disabled={page >= pages || files.loading}>{t('下一页')}</button>
    </nav>}
  </div>
}
