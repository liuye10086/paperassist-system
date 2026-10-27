import type { AnalysisNavigation } from './analysisViews'
import { useCallback, useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { useI18n } from '../../shared/i18n'
import BatchUpload from '../files/BatchUpload'
import ExcelPreview from '../files/ExcelPreview'
import type { SavedPreviewState } from '../files/ExcelPreview'
import ProjectFileLibrary from '../files/ProjectFileLibrary'
import { fileRequest } from '../files/fileLibraryApi'
import type { ProjectFile } from '../files/fileLibraryApi'
import AnalysisSetup from '../analysis/AnalysisSetup'
import ProjectRequirements from '../analysisPlan/ProjectRequirements'
import type { ProjectSection } from './WorkspaceShell'
import type { ResourceNavigation } from './resourceViews'
import type { RegisterLeaveGuard } from './useDraftLeaveGuard'

type Props = { projectId: string; onSaved: () => void; section: ProjectSection; onSectionChange: (section: ProjectSection) => void; active?: boolean
  analysisNavigation?: AnalysisNavigation; onAnalysisNavigate?: (next:AnalysisNavigation)=>void; resourceNavigation?: ResourceNavigation; onResourceNavigate?: (next: ResourceNavigation) => void; registerLeaveGuard?: RegisterLeaveGuard }

function ResourceScope({ projectId, onSaved, section, onSectionChange, active = true, ...navigationProps }: Props) {
  const { t } = useI18n()
  const [unavailable, setUnavailable] = useState(false)
  const denied = useCallback(() => setUnavailable(true), [])
  useEffect(() => onApiSessionChanged(denied), [denied])
  if (unavailable) return <p role="alert" className="error-panel">{t('项目不存在或无权访问。')}</p>
  return <ResourceContent projectId={projectId} onSaved={onSaved} section={section} onSectionChange={onSectionChange} active={active} onUnavailable={denied} {...navigationProps} />
}

function ResourceContent({ projectId, onSaved, section, onSectionChange, onUnavailable, active, resourceNavigation, onResourceNavigate, registerLeaveGuard, analysisNavigation, onAnalysisNavigate }: Props & { onUnavailable: () => void }) {
  const { t } = useI18n()
  const [localNavigation, setLocalNavigation] = useState<ResourceNavigation>({ view: 'list', fileId: '' })
  const navigation = resourceNavigation ?? localNavigation
  const [uploadVisited, setUploadVisited] = useState(navigation.view === 'upload')
  const [previewVisited, setPreviewVisited] = useState(navigation.view === 'upload' || navigation.view === 'preview')
  if (navigation.view === 'upload' && !uploadVisited) setUploadVisited(true)
  if ((navigation.view === 'upload' || navigation.view === 'preview') && !previewVisited) setPreviewVisited(true)
  function navigate(next: ResourceNavigation) { if (onResourceNavigate) onResourceNavigate(next); else setLocalNavigation(next) }
  const [localAnalysis,setLocalAnalysis]=useState<AnalysisNavigation>({view:'overview',fileId:''})
  const analysis=analysisNavigation??localAnalysis
  const navigateAnalysis=onAnalysisNavigate??setLocalAnalysis
  const filesActive = Boolean(active) && section === 'files'
  const [files, setFiles] = useState<ProjectFile[]>([])
  const [attempt, setAttempt] = useState(0)
  const [uploadVersion, setUploadVersion] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [opened, setOpened] = useState<{ id: string; request: number } | null>(null)
  const [previewState, setPreviewState] = useState<SavedPreviewState | null>(null)
  const openSequence = useRef(0)
  if (navigation.view === 'preview' && navigation.fileId && opened?.id !== navigation.fileId) {
    setPreviewState({ id: navigation.fileId, status: 'loading' })
    setOpened({ id: navigation.fileId, request: 0 })
  }

  function refresh() { setLoading(true); setError(''); setAttempt(value => value + 1) }
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    void fileRequest<ProjectFile[]>(`/api/v1/projects/${projectId}/files`, controller.signal, onUnavailable)
      .then(result => {
        if (!Array.isArray(result)) throw new Error('format')
        if (active && !controller.signal.aborted) setFiles(result)
      })
      .catch(() => { if (active) setError('文件列表读取失败，请确认后端服务正常后重试。') })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false) })
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [projectId, attempt, onUnavailable])

  function batchChanged() { setUploadVersion(value => value + 1); refresh(); onSaved() }
  function uploaded() {
    setOpened(null); setPreviewState(null); setUploadVersion(value => value + 1)
    refresh(); onSaved()
  }
  return <>
    <div hidden={section !== 'files'} className="project-files-page">
      <nav className="material-view-actions" aria-label={t('材料视图')}>
        {navigation.view !== 'list' && <button type="button" onClick={() => navigate({ view: 'list', fileId: '' })}>{t('返回文件列表')}</button>}
        {navigation.view === 'list' && <button type="button" className="button-primary" onClick={() => navigate({ view: 'upload', fileId: '' })}>{t('上传文件')}</button>}
        {navigation.view === 'preview' && navigation.fileId && <>
          <button type="button" onClick={() => navigate({ view: 'detail', fileId: navigation.fileId })}>{t('文件详情')}</button>
          <button type="button" disabled={busy} onClick={() => { setPreviewState({ id: navigation.fileId, status: 'loading' }); setOpened({ id: navigation.fileId, request: ++openSequence.current }) }}>{t('重新读取预览')}</button>
        </>}
      </nav>
      <div hidden={navigation.view !== 'upload'}>
        {uploadVisited && <BatchUpload projectId={projectId} active={filesActive && navigation.view === 'upload'} onUnavailable={onUnavailable} onChanged={batchChanged} registerLeaveGuard={registerLeaveGuard} />}
      </div>
      <ProjectFileLibrary projectId={projectId} active={filesActive} uploadVersion={uploadVersion} busy={busy} resourceNavigation={navigation} onResourceNavigate={navigate} registerLeaveGuard={registerLeaveGuard}
        previewState={previewState} onUnavailable={onUnavailable} onPreview={id => {
          setPreviewState({ id, status: 'loading' }); setOpened({ id, request: ++openSequence.current })
          navigate({ view: 'preview', fileId: id })
        }} />
      <div hidden={navigation.view !== 'upload' && navigation.view !== 'preview'}>
        {previewVisited && <ExcelPreview projectId={projectId} savedFile={opened} uploadVisible={navigation.view === 'upload'} onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} onSaved={uploaded} onBusyChange={setBusy} onSavedPreviewChange={setPreviewState} />}
      </div>
    </div>
    <div hidden={section !== 'analysis'} className="project-analysis-page">
      <nav className="analysis-overview-nav" aria-label={t('分析工作区')}>
        <button type="button" aria-current={analysis.view==='overview'?'page':undefined} onClick={()=>navigateAnalysis({...analysis,view:'overview'})}>{t('分析概览')}</button>
        {analysis.view==='overview'&&<button type="button" className="button-primary" onClick={()=>navigateAnalysis({...analysis,view:'setup'})}>{t('进入分析工作台')}</button>}
      </nav>
      <div hidden={analysis.view!=='overview'}>
        <section className="analysis-overview-heading"><span className="workspace-eyebrow">{t('数据分析')}</span><h2>{t('从研究问题到分析成果')}</h2><p>{t('按任务进入独立视图，继续当前文件的配置与分析。')}</p></section>
        <div className="analysis-entry-grid">{([
          ['setup','数据与字段','选择原始数据或整理版本，检查分析字段。'],
          ['profile','数据概况','查看质量概况与字段分布。'],
          ['plan','分析方案','核对研究问题、方法与已确认方案。'],
          ['statistics','统计结果','执行统计并查看固定来源的结果。'],
          ['figure','图表工作台','调整图表配置，查看已生成版本。'],
          ['report','报告与集合','组织固定结果，预览并导出报告。'],
        ] as const).map(([target,title,description],index)=><button type="button" key={target} onClick={()=>navigateAnalysis({...analysis,view:target})}><span className="analysis-entry-number">{String(index+1).padStart(2,'0')}</span><strong>{t(title)}</strong><span>{t(description)}</span></button>)}</div>
        <ProjectRequirements projectId={projectId} files={files} registerLeaveGuard={registerLeaveGuard}/>
      </div>
      <div hidden={analysis.view==='overview'}>
      <AnalysisSetup projectId={projectId} files={files} filesLoading={loading} filesError={error} onReloadFiles={refresh}
        onOpenFiles={() => onSectionChange('files')} stage={analysis.view==='overview'?'setup':analysis.view} onStageChange={view=>navigateAnalysis({...analysis,view})} fileId={analysis.fileId} onFileChange={fileId=>navigateAnalysis({...analysis,fileId})} registerLeaveGuard={registerLeaveGuard} />
      </div>
    </div>
  </>
}

export default function ProjectResources(props: Props) { return <ResourceScope key={props.projectId} {...props} /> }
