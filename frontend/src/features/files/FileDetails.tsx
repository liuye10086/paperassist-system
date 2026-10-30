import DocumentVersions from '../documents/DocumentVersions'
import StructureVersions from '../datasets/StructureVersions'
import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { fileRequest, mergeFileMetadata, parseStatusLabels, purposeLabels, referenceLabels } from './fileLibraryApi'
import type { FileDetail, FilePurpose, LibraryFile } from './fileLibraryApi'
import FileLifecyclePanel from './FileLifecyclePanel'
import {onApiSessionChanged} from '../../shared/api/client'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'

type DetailTask = 'info' | 'lifecycle' | 'structure' | 'document'

function FileDetailsContent({ projectId, fileId, active, onUnavailable, onUpdated, initialTask = 'info', registerLeaveGuard }: {
  projectId: string; fileId: string; active: boolean; onUnavailable: () => void; onUpdated: (file: LibraryFile) => void
  initialTask?: DetailTask; registerLeaveGuard?: RegisterLeaveGuard
}) {
  const { t, locale } = useI18n()
  const [detail, setDetail] = useState<FileDetail | null>(null)
  const [draft, setDraft] = useState<FilePurpose[]>([])
  const draftInitialized = useRef(false)
  const confirmedMetadata = useRef<LibraryFile | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [task, setTask] = useState<DetailTask>(initialTask)
  const [visitedTasks, setVisitedTasks] = useState<DetailTask[]>([initialTask])
  function showTask(next: DetailTask) { setTask(next); setVisitedTasks(current => current.includes(next) ? current : [...current, next]) }
  const [previousInitialTask, setPreviousInitialTask] = useState(initialTask)
  if (previousInitialTask !== initialTask) {
    setPreviousInitialTask(initialTask)
    if (initialTask === 'document') { setTask('document'); setVisitedTasks(current => current.includes('document') ? current : [...current, 'document']) }
  }
  const mounted = useRef(true)
  const saveController = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const [scopeValid,setScopeValid] = useState(true)
  useDraftLeaveGuard(registerLeaveGuard, detail !== null && JSON.stringify([...draft].sort()) !== JSON.stringify([...detail.purposes].sort()), busy)
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`
  const requestKey = `${base}:${active}:${attempt}`
  const [previousRequest, setPreviousRequest] = useState(requestKey)
  if (previousRequest !== requestKey) {
    setPreviousRequest(requestKey)
    if (active) { setLoading(true); setError(''); setNotice('') }
  }

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; saveController.current?.abort() }
  }, [])
  useEffect(()=>onApiSessionChanged(()=>{generation.current++;saveController.current?.abort();setScopeValid(false);setDetail(null);setDraft([]);confirmedMetadata.current=null;draftInitialized.current=false;setError('');setNotice('');setLoading(false);setBusy(false)}),[])
  useEffect(() => {
    if (!active || !scopeValid) return
    const controller = new AbortController()
    const captured = generation.current
    let current = true
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    void fileRequest<FileDetail>(`${base}/details`, controller.signal, onUnavailable)
      .then(result => {
        if (!current || controller.signal.aborted || captured!==generation.current) return
        const merged = mergeFileMetadata(result, confirmedMetadata.current)
        confirmedMetadata.current = merged
        setDetail(merged)
        onUpdated(merged)
        // Re-reading confirms the latest revision, without discarding unsaved choices.
        if (!draftInitialized.current) { setDraft(merged.purposes); draftInitialized.current = true }
        else setNotice('已重新读取文件详情，草稿已保留，请核对后保存。')
      })
      .catch(cause => {
        if (current && captured===generation.current) setError(controller.signal.aborted ? '读取文件详情超时，请重试。'
          : safeError(cause, '读取文件详情失败，请重试。'))
      })
      .finally(() => { window.clearTimeout(timeout); if (current && captured===generation.current) setLoading(false) })
    return () => { current = false; controller.abort(); window.clearTimeout(timeout) }
  }, [base, active, attempt, onUnavailable, onUpdated, scopeValid])

  async function save() {
    if (!detail || loading || saveController.current) return
    const controller = new AbortController()
    saveController.current = controller
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 15_000)
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await fileRequest<LibraryFile>(`${base}/purposes`, controller.signal, onUnavailable, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision: detail.metadata_revision, purposes: draft }),
      })
      if (mounted.current && !controller.signal.aborted) {
        const merged = mergeFileMetadata(result, confirmedMetadata.current)
        confirmedMetadata.current = merged
        setDetail(current => current && ({ ...current, ...merged })); setDraft(merged.purposes)
        onUpdated(merged); setNotice('文件用途已保存。')
      }
    } catch (cause) {
      if (mounted.current && (!controller.signal.aborted || timedOut)) setError(timedOut
        ? '保存用途超时，草稿已保留，请重新读取以确认结果。'
        : safeError(cause, '保存用途失败，草稿已保留，请重试或重新读取。'))
    } finally {
      window.clearTimeout(timeout)
      if (saveController.current === controller) saveController.current = null
      if (mounted.current) setBusy(false)
    }
  }

  return <section className="file-details" aria-label={t('文件详情')} aria-busy={loading || busy}>
    <div className="preview-heading"><h3>{t('文件详情')}{detail && ` · ${detail.filename}`}</h3>
      <button type="button" disabled={loading || busy} onClick={() => setAttempt(value => value + 1)}>{t('重新读取文件详情')}</button></div>
    {loading && <p role="status">{t('正在读取文件详情……')}</p>}
    {error && <p className="error-panel" role="alert">{t(error)}</p>}
    {detail && <>
      {['bio_bundle','bio_component'].includes(detail.file_type)&&<p>{t('已保存，待生信导入')} · <a href={`#project=${encodeURIComponent(projectId)}&section=analysis&view=bio-datasets`}>{t('生信数据集')}</a></p>}
      <nav className="material-task-nav" aria-label={t('文件任务')}>
        <button type="button" aria-pressed={task === 'info'} onClick={() => showTask('info')}>{t('文件信息与用途')}</button>
        <button type="button" aria-pressed={task === 'lifecycle'} onClick={() => showTask('lifecycle')}>{t('生命周期')}</button>
        {detail.file_type === 'xlsx' && detail.parse_status === 'parsed' && <button type="button" aria-pressed={task === 'structure'} onClick={() => showTask('structure')}>{t('结构与数据整理')}</button>}
        {['docx','pdf','png','jpeg'].includes(detail.file_type) && <button type="button" aria-pressed={task === 'document'} onClick={() => showTask('document')}>{t('解析与文字核对')}</button>}
      </nav>
      {task !== 'info' && <button type="button" className="material-back" onClick={() => showTask('info')}>{t('返回文件信息')}</button>}
      <div hidden={task !== 'info'}>
      <dl className="file-metadata">
        <div><dt>{t('文件大小')}</dt><dd>{t('{count} 字节', { count: detail.size_bytes.toLocaleString(locale) })}</dd></div>
        <div><dt>{t('文件类型')}</dt><dd>{detail.file_type === 'xlsx' ? 'Excel (.xlsx)' : detail.file_type === 'docx' ? 'Word (.docx)' : detail.file_type === 'pdf' ? 'PDF (.pdf)' : detail.file_type === 'png' ? 'PNG (.png)' : detail.file_type === 'jpeg' ? 'JPEG (.jpg / .jpeg)' : t('未知类型')}</dd></div>
        <div><dt>{t('解析状态')}</dt><dd>{t(parseStatusLabels[detail.parse_status])}</dd></div>
        <div><dt>{t('上传者记录')}</dt><dd>{t(detail.uploader_recorded ? '已记录上传者' : '未记录上传者')}</dd></div>
      </dl>
      {detail.file_type === 'xlsx' && <><p className="muted">{t(detail.source.preview_available ? '既有预览：前 {count} 行' : '此文件没有可用的既有预览。', { count: detail.source.preview_row_limit ?? 20 })}</p>
      <p className="muted">{detail.source.kind === 'excel_parse' ? t('解析器版本：{version}。预览不代表完整数据。', { version: detail.source.parser_version ?? '' }) : t('历史 Excel 读取链未记录精确解析版本。预览不代表完整数据。')}</p></>}
      <p className="muted">{t('已保存用途：{purposes}', { purposes: detail.purposes.length
        ? detail.purposes.map(purpose => t(purposeLabels[purpose])).join(' · ') : t('未指定用途') })}</p>
      <form onSubmit={event => { event.preventDefault(); void save() }}>
        <fieldset disabled={loading || busy}><legend>{t('文件用途')}</legend>
          <div className="file-purpose-options">{(Object.keys(purposeLabels) as FilePurpose[]).map(purpose =>
            <label key={purpose}><input type="checkbox" checked={draft.includes(purpose)} onChange={event => {
              setDraft(current => event.target.checked ? [...current, purpose] : current.filter(value => value !== purpose))
              setNotice('')
            }} />{t(purposeLabels[purpose])}</label>)}</div>
        </fieldset>
        {!draft.length && <p className="muted">{t('未指定用途')}</p>}
        <p className="muted">{t('用途用于整理资料，不会更改分析配置或已有成果。')}</p>
        <button type="submit" className="button-primary" disabled={loading || busy}>{t(busy ? '正在保存用途……' : '保存用途')}</button>
      </form>
      <details className="file-reference-summary"><summary>{t('文件引用汇总')}</summary><dl className="file-reference-counts">
        {(Object.keys(referenceLabels) as (keyof typeof referenceLabels)[]).map(key =>
          <div key={key}><dt>{t(referenceLabels[key])}</dt><dd>{(detail.references[key] ?? 0).toLocaleString(locale)}</dd></div>)}
      </dl>
      <p className="muted">{t('引用数量描述当前依赖，不代表可以删除文件。')}</p></details>
      </div>
      {visitedTasks.includes('lifecycle') && <div hidden={task !== 'lifecycle'}><FileLifecyclePanel projectId={projectId} fileId={fileId} active={active && task === 'lifecycle'} observedVersion={detail.parse_revision} registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable}/></div>}
    </>}
    {visitedTasks.includes('structure') && detail?.file_type === 'xlsx' && detail.parse_status === 'parsed' && <div hidden={task !== 'structure'}><StructureVersions projectId={projectId} fileId={fileId} filename={detail.filename} active={active && task === 'structure'} registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable} /></div>}
    {visitedTasks.includes('document') && detail && ['docx','pdf','png','jpeg'].includes(detail.file_type) && <div hidden={task !== 'document'}><DocumentVersions fileType={detail.file_type as 'docx' | 'pdf' | 'png' | 'jpeg'} projectId={projectId} fileId={fileId} filename={detail.filename} active={active && task === 'document'} registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable} /></div>}
    {notice && <p className="saved-notice" role="status">{t(notice)}</p>}
  </section>
}
export default function FileDetails(props:Parameters<typeof FileDetailsContent>[0]){return <FileDetailsContent key={JSON.stringify([props.projectId,props.fileId])} {...props}/>}
