import BioInsightsWorkspace from '../bio-insights/BioInsightsWorkspace'
import {isInsightView} from '../bio-insights/state'
import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import BioUpload from '../bioinformatics/BioUpload'
import BioImports from '../bioinformatics/BioImports'
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
import AnalysisGuide from './AnalysisGuide'
import './projectUpload.css'
import './projectAnalysis.css'

type Props = { onRequirements?: () => void; projectId: string; onSaved: () => void; section: ProjectSection; onSectionChange: (section: ProjectSection) => void; active?: boolean
  analysisNavigation?: AnalysisNavigation; onAnalysisNavigate?: (next:AnalysisNavigation)=>void; resourceNavigation?: ResourceNavigation; onResourceNavigate?: (next: ResourceNavigation) => void; registerLeaveGuard?: RegisterLeaveGuard }

function ResourceScope({ projectId, onSaved, section, onSectionChange, active = true, ...navigationProps }: Props) {
  const { t } = useI18n()
  const [unavailable, setUnavailable] = useState(false)
  const denied = useCallback(() => setUnavailable(true), [])
  useEffect(() => onApiSessionChanged(denied), [denied])
  if (unavailable) return <p role="alert" className="error-panel">{t('项目不存在或无权访问。')}</p>
  return <ResourceContent projectId={projectId} onSaved={onSaved} section={section} onSectionChange={onSectionChange} active={active} onUnavailable={denied} {...navigationProps} />
}

function ResourceContent({ projectId, onSaved, section, onSectionChange, onUnavailable, active, resourceNavigation, onResourceNavigate, registerLeaveGuard, analysisNavigation, onAnalysisNavigate, onRequirements }: Props & { onUnavailable: () => void }) {
  const { t } = useI18n()
  const [localNavigation, setLocalNavigation] = useState<ResourceNavigation>({ view: 'list', fileId: '' })
  const [uploadKind, setUploadKind] = useState<'documents'|'bio'>('documents')
  const navigation = resourceNavigation ?? localNavigation
  const [uploadVisited, setUploadVisited] = useState(navigation.view === 'upload')
  const [previewVisited, setPreviewVisited] = useState(navigation.view === 'preview')
  if (navigation.view === 'upload' && !uploadVisited) setUploadVisited(true)
  if (navigation.view === 'preview' && !previewVisited) setPreviewVisited(true)
  function navigate(next: ResourceNavigation) { if (onResourceNavigate) onResourceNavigate(next); else setLocalNavigation(next) }
  const [localAnalysis,setLocalAnalysis]=useState<AnalysisNavigation>({view:'overview',fileId:''})
  const analysis=analysisNavigation??localAnalysis
  const [requirementsVisited,setRequirementsVisited]=useState(analysis.view==='research-request')
  if(analysis.view==='research-request'&&!requirementsVisited)setRequirementsVisited(true)
  const navigateAnalysis=onAnalysisNavigate??setLocalAnalysis
  const insightView=isInsightView(analysis.view)
  const bioView=analysis.view.startsWith('bio-')&&!insightView
  const researchView=analysis.view==='research-findings'
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
    const timeout = window.setTimeout(() => controller.abort(), STANDARD_REQUEST_TIMEOUT_MS)
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
  return <>
    <div hidden={section !== 'files'} className="project-files-page">
      <nav className="material-view-actions resource-view-nav" aria-label={t('材料视图')}>
        {['list', 'upload'].includes(navigation.view) ? <>
          <button type="button" aria-current={navigation.view === 'upload' ? 'page' : undefined} onClick={() => navigate({ view: 'upload', fileId: '' })}>{t('上传文件')}</button>
          <button type="button" aria-current={navigation.view === 'list' ? 'page' : undefined} onClick={() => navigate({ view: 'list', fileId: '' })}>{t('已上传文件')}</button>
        </> : <button type="button" onClick={() => navigate({ view: 'list', fileId: '' })}>{t('返回文件列表')}</button>}
        {navigation.view === 'preview' && navigation.fileId && <>
          <button type="button" onClick={() => navigate({ view: 'detail', fileId: navigation.fileId })}>{t('文件详情')}</button>
          <button type="button" disabled={busy} onClick={() => { setPreviewState({ id: navigation.fileId, status: 'loading' }); setOpened({ id: navigation.fileId, request: ++openSequence.current }) }}>{t('重新读取预览')}</button>
        </>}
      </nav>
      <div className="upload-mode-bar" hidden={navigation.view !== 'upload'}>
        <div className="upload-kind-options" role="group" aria-label={t('选择上传材料类型')}>{([['documents','表格、报告与图片'],['bio','组学与生信数据包']] as const).map(([kind,label])=><button type="button" key={kind} aria-pressed={uploadKind===kind} onClick={()=>setUploadKind(kind)}>{t(label)}</button>)}</div>
      </div>
      <div className="resource-upload-panel" hidden={navigation.view !== 'upload' || uploadKind !== 'documents'}>{uploadVisited && <BatchUpload embedded projectId={projectId} active={filesActive && navigation.view === 'upload' && uploadKind==='documents'} onUnavailable={onUnavailable} onChanged={batchChanged} registerLeaveGuard={registerLeaveGuard} />}</div>
      <div className="resource-upload-panel" hidden={!filesActive||navigation.view!=='upload'||uploadKind!=='bio'}><BioUpload embedded active={filesActive&&navigation.view==='upload'&&uploadKind==='bio'} projectId={projectId} onChanged={batchChanged} registerLeaveGuard={registerLeaveGuard}/></div>
      <ProjectFileLibrary projectId={projectId} active={filesActive} uploadVersion={uploadVersion} busy={busy} resourceNavigation={navigation} onResourceNavigate={navigate} registerLeaveGuard={registerLeaveGuard}
        previewState={previewState} onUnavailable={onUnavailable} onPreview={id => {
          setPreviewState({ id, status: 'loading' }); setOpened({ id, request: ++openSequence.current })
          navigate({ view: 'preview', fileId: id })
        }} />
      <div className="resource-upload-panel" hidden={navigation.view !== 'preview'}>
        {previewVisited && <ExcelPreview embedded projectId={projectId} savedFile={opened} uploadVisible={false} onUnavailable={onUnavailable} onBusyChange={setBusy} onSavedPreviewChange={setPreviewState} />}
      </div>
    </div>
    <div hidden={section !== 'analysis'} className="project-analysis-page">
      <nav hidden={analysis.view==='overview'} className="analysis-overview-nav" aria-label={t('分析工作区')}>
        <button type="button" onClick={()=>navigateAnalysis({view:'overview',fileId:analysis.fileId})}>← {t('返回分析入口')}</button>
      </nav>
      <BioInsightsWorkspace projectId={projectId} navigation={analysis} onNavigate={navigateAnalysis} active={Boolean(active)&&section==='analysis'&&insightView} registerLeaveGuard={registerLeaveGuard}/>
      <BioImports projectId={projectId} navigation={analysis} onNavigate={navigateAnalysis} active={Boolean(active)&&section==='analysis'&&bioView} registerLeaveGuard={registerLeaveGuard}/>
      <div hidden={analysis.view!=='overview'}>
        <AnalysisGuide projectId={projectId} active={Boolean(active)&&section==='analysis'&&analysis.view==='overview'} onNavigate={view=>navigateAnalysis({view,fileId:analysis.fileId})} onRequirements={onRequirements}/>
      </div>
      <div hidden={analysis.view!=='research-request'}>{requirementsVisited&&<ProjectRequirements projectId={projectId} files={files.filter((file):file is ProjectFile & {parse_status:'queued'|'parsing'|'parsed'|'failed'}=>file.parse_status!=='stored')} registerLeaveGuard={registerLeaveGuard}/>}</div>
      <div hidden={analysis.view==='overview'||analysis.view==='research-request'||bioView||insightView||researchView}>
      <AnalysisSetup projectId={projectId} files={files.filter((file):file is ProjectFile & {parse_status:'queued'|'parsing'|'parsed'|'failed'}=>file.parse_status!=='stored'&&file.file_type==='xlsx')} filesLoading={loading} filesError={error} onReloadFiles={refresh}
        onOpenFiles={() => onSectionChange('files')} stage={analysis.view==='overview'||analysis.view==='research-request'||analysis.view==='research-findings'||analysis.view.startsWith('bio-')?'setup':analysis.view as import('../analysis/analysisWorkflowContext').AnalysisStage} onStageChange={view=>navigateAnalysis({...analysis,view})} fileId={analysis.fileId} onFileChange={fileId=>navigateAnalysis({...analysis,fileId})} registerLeaveGuard={registerLeaveGuard} />
      </div>
    </div>
  </>
}

export default function ProjectResources(props: Props) { return <ResourceScope key={props.projectId} {...props} /> }
