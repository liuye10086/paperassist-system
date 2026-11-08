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
import AnalysisEntryContext from './AnalysisEntryContext'
import {analysisScopes,filePreparation} from './analysisEntryState'
import type {Intake,Version} from '../research-intake/contracts'
import {projectBase,useResearchRead} from '../research-results/api'
import useResearchDraft from '../research-results/useResearchDraft'
import useEntryImports from './useEntryImports'
import './projectUpload.css'
import './projectAnalysis.css'
import UploadQuality from './UploadQuality'

type Props = { allowNewAnalysis?:boolean; savedRequirement?:Version|null; onRequirements?: (panel?:'materials') => void; projectId: string; onSaved: () => void; section: ProjectSection; onSectionChange: (section: ProjectSection) => void; active?: boolean
  analysisNavigation?: AnalysisNavigation; onAnalysisNavigate?: (next:AnalysisNavigation)=>void; resourceNavigation?: ResourceNavigation; onResourceNavigate?: (next: ResourceNavigation) => void; registerLeaveGuard?: RegisterLeaveGuard }

function ResourceScope({ projectId, onSaved, section, onSectionChange, active = true, ...navigationProps }: Props) {
  const { t } = useI18n()
  const [unavailable, setUnavailable] = useState(false)
  const denied = useCallback(() => setUnavailable(true), [])
  useEffect(() => onApiSessionChanged(denied), [denied])
  if (unavailable) return <p role="alert" className="error-panel">{t('项目不存在或无权访问。')}</p>
  return <ResourceContent projectId={projectId} onSaved={onSaved} section={section} onSectionChange={onSectionChange} active={active} onUnavailable={denied} {...navigationProps} />
}

function ResourceContent({ projectId, onSaved, section, onSectionChange, onUnavailable, active, resourceNavigation, onResourceNavigate, registerLeaveGuard, analysisNavigation, onAnalysisNavigate, onRequirements, savedRequirement, allowNewAnalysis=true }: Props & { onUnavailable: () => void }) {
  const { t } = useI18n()
  const [localNavigation, setLocalNavigation] = useState<ResourceNavigation>({ view: 'list', fileId: '' })
  const [uploadKind, setUploadKind] = useResearchDraft<'documents'|'bio'>(projectId,'resource-upload-kind',()=> 'documents')
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
  const analysisActive=!!active&&section==='analysis'
  const intake=useResearchRead<Intake>(`${projectBase(projectId)}/research-intake`,Boolean(active)&&(section==='analysis'||section==='files'))
  const fixed=useResearchRead<Version>(analysis.entry?`${projectBase(projectId)}/requirements/${encodeURIComponent(analysis.entry.requirementVersionId)}`:'',analysisActive&&!!analysis.entry)
  const current=savedRequirement&&savedRequirement.version>=(intake.data?.current_requirement?.version??0)?savedRequirement:intake.data?.current_requirement??null
  const requirement=analysis.entry?fixed.data:current
  const entryAvailable=!analysis.entry||!!fixed.data&&!fixed.error&&analysisScopes(fixed.data).some(s=>s.id===analysis.entry?.scopeItemId)
  function openFile(id:string){if(onResourceNavigate)onResourceNavigate({view:'detail',fileId:id});else{onSectionChange('files');navigate({view:'detail',fileId:id})}}
  const insightView=isInsightView(analysis.view)
  const bioView=analysis.view.startsWith('bio-')&&!insightView
  const researchView=analysis.view==='research-findings'
  const filesActive = Boolean(active) && section === 'files'
  const qualityBioActive = filesActive && navigation.view === 'quality' && !!navigation.bio
  const sharedBioActive = qualityBioActive || analysisActive && bioView && entryAvailable
  const desiredBio = qualityBioActive ? navigation.bio! : analysis
  const [retainedBio, setRetainedBio] = useState<AnalysisNavigation>(desiredBio)
  if (sharedBioActive && retainedBio !== desiredBio) setRetainedBio(desiredBio)
  function navigateBio(next: AnalysisNavigation) {
    if (section === 'files') navigate({view:'quality',fileId:'',bio:next})
    else navigateAnalysis(next)
  }
  const [files, setFiles] = useState<ProjectFile[]>([])
  const imports=useEntryImports(projectId,Boolean(active)&&(section==='files'||section==='analysis')&&files.some(file=>file.parse_status==='stored'),section==='analysis'?analysis.view:navigation.view)
  const initialFileIds=analysis.entry&&analysis.intent==='bio'&&entryAvailable&&fixed.data?.material_refs?.some(ref=>ref.file_id===analysis.fileId&&ref.availability==='provided')&&files.some(file=>file.id===analysis.fileId&&file.parse_status==='stored')?[analysis.fileId]:undefined
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
  }, [projectId, attempt, onUnavailable, section])

  function batchChanged() { setUploadVersion(value => value + 1); refresh(); onSaved() }
  function refreshMaterials(){refresh();imports.refresh()}
  function openUpload(){if(onResourceNavigate)onResourceNavigate({view:'upload',fileId:''});else{onSectionChange('files');navigate({view:'upload',fileId:''})}}
  const canContinueMaterials=!loading&&!error&&files.some(file=>file.parse_status==='stored'||file.parse_status==='parsed')
  return <div className={section === 'files' ? 'project-files-page' : 'project-analysis-page analysis-workspace'} hidden={!active || !['files','analysis'].includes(section)}>
    <div hidden={section !== 'files'}>
      <nav className="material-view-actions resource-view-nav" aria-label={t('材料视图')}>
          <button type="button" aria-current={navigation.view === 'upload' ? 'page' : undefined} onClick={() => navigate({ view: 'upload', fileId: '' })}>{t('上传文件')}</button>
          <button type="button" aria-current={['list','detail','preview'].includes(navigation.view) ? 'page' : undefined} onClick={() => navigate({ view: 'list', fileId: '' })}>{t('已上传文件')}</button>
          <button type="button" aria-current={navigation.view === 'quality' ? 'page' : undefined} onClick={() => navigate({view:'quality',fileId:''})}>{t('质量控制')}</button>
      </nav>
      <div className="resource-module-body" hidden={qualityBioActive}>
      {navigation.view === 'preview' && navigation.fileId && <div className="resource-subview-actions">
          <button type="button" onClick={() => navigate({ view: 'detail', fileId: navigation.fileId })}>{t('文件详情')}</button>
          <button type="button" disabled={busy} onClick={() => { setPreviewState({ id: navigation.fileId, status: 'loading' }); setOpened({ id: navigation.fileId, request: ++openSequence.current }) }}>{t('重新读取预览')}</button>
      </div>}
      {navigation.view==='quality' && !navigation.fileId && !navigation.bio && <UploadQuality files={files} loading={loading} error={error} onReload={refreshMaterials} onNavigate={navigate}/>}
      {navigation.view==='list'&&<section className="upload-preparation-summary" aria-label={t('材料准备状态')}>{imports.error&&<p role="alert">{t(imports.error)}</p>}{loading?<p role="status">{t('正在核对材料状态……')}</p>:error?<p role="alert">{t(error)} <button type="button" onClick={refreshMaterials}>{t('重新读取材料')}</button></p>:<ul>{Object.entries(files.reduce<Record<string,number>>((counts,file)=>{const label=file.parse_status==='stored'&&imports.unknown?'材料状态尚未核实':filePreparation(file,imports.data??[]).label;counts[label]=(counts[label]??0)+1;return counts},{})).map(([label,count])=><li key={label}>{t(label)} · {count}</li>)}</ul>}</section>}
      <div className="upload-mode-bar" hidden={navigation.view !== 'upload'}>
        <div className="upload-kind-options" role="group" aria-label={t('选择上传材料类型')}>{([['documents','表格、报告与图片'],['bio','组学与生信数据包']] as const).map(([kind,label])=><button type="button" key={kind} aria-pressed={uploadKind===kind} onClick={()=>setUploadKind(kind)}>{t(label)}</button>)}</div>
      </div>
      <div className="resource-upload-panel" hidden={navigation.view !== 'upload' || uploadKind !== 'documents'}>{uploadVisited && <BatchUpload embedded projectId={projectId} active={filesActive && navigation.view === 'upload' && uploadKind==='documents'} onUnavailable={onUnavailable} onChanged={batchChanged} registerLeaveGuard={registerLeaveGuard} />}</div>
      <div className="resource-upload-panel" hidden={!filesActive||navigation.view!=='upload'||uploadKind!=='bio'}><BioUpload embedded active={filesActive&&navigation.view==='upload'&&uploadKind==='bio'} projectId={projectId} onChanged={batchChanged} registerLeaveGuard={registerLeaveGuard}/></div>
      <ProjectFileLibrary projectId={projectId} active={filesActive} uploadVersion={uploadVersion} busy={busy} resourceNavigation={navigation} onResourceNavigate={navigate} registerLeaveGuard={registerLeaveGuard} onReloadMaterials={refreshMaterials}
        previewState={previewState} onUnavailable={onUnavailable} onPreview={id => {
          setPreviewState({ id, status: 'loading' }); setOpened({ id, request: ++openSequence.current })
          navigate({ view: 'preview', fileId: id })
        }} />
      <div className="resource-upload-panel" hidden={navigation.view !== 'preview'}>
        {previewVisited && <ExcelPreview embedded projectId={projectId} savedFile={opened} uploadVisible={false} onUnavailable={onUnavailable} onBusyChange={setBusy} onSavedPreviewChange={setPreviewState} />}
      </div>
      {['upload','list','detail','preview'].includes(navigation.view)&&<footer className="upload-preparation-summary" aria-label={t('上传后的下一步')}>
        {loading?<p>{t('正在核对材料状态……')}</p>:error?<p>{t('材料状态尚未核实，请重新读取材料后继续。')}</p>:canContinueMaterials?<>
          <p>{t(files.some(file=>file.parse_status==='stored')?'原件已保存，待导入核对；先选择分析，再继续核对材料与参数。':'材料已保存，可以选择本次分析并核对参数。')}</p>
          <div className="intake-actions">{current&&analysisScopes(current).length>0
            ? <button type="button" className="button-primary" onClick={()=>{navigateAnalysis(analysis);onSectionChange('analysis')}}>{t('继续本次分析')}</button>
            : onRequirements&&<button type="button" className="button-primary" onClick={()=>onRequirements?.()}>{t('下一步：选择分析')}</button>}</div>
        </>:<p>{t(files.length?'材料仍在解析或解析失败，请先查看材料状态。':'请先上传本次分析所需材料。')}</p>}
      </footer>}
      </div>
    </div>
    <div className={bioView?'analysis-content analysis-bio-header':'analysis-content'} hidden={section !== 'analysis'}>
      <nav hidden={analysis.view==='overview'||!!analysis.entry} className="analysis-overview-nav" aria-label={t('分析工作区')}>
        <button type="button" onClick={()=>navigateAnalysis({view:'overview',fileId:analysis.fileId,entry:analysis.entry,intent:analysis.intent})}>← {t('返回分析入口')}</button>
      </nav>
      <AnalysisEntryContext navigation={analysis} version={fixed.data} current={current} loading={fixed.loading} error={fixed.error} files={files} filesUnknown={loading||!!error||imports.unknown} imports={imports.data??[]} onReload={fixed.refresh} onNavigate={navigateAnalysis} onFile={openFile}/>
      <div className="analysis-module-body" hidden={bioView}>
      <BioInsightsWorkspace allowNewAnalysis={allowNewAnalysis} projectId={projectId} navigation={analysis} onNavigate={navigateAnalysis} active={analysisActive&&insightView&&entryAvailable} registerLeaveGuard={registerLeaveGuard}/>
      <div className="analysis-overview-body" hidden={analysis.view!=='overview'}>
        <AnalysisGuide projectId={projectId} onUpload={openUpload} version={requirement} scopeId={analysis.entry?.scopeItemId} loading={analysis.entry?fixed.loading:intake.loading&&!current} error={analysis.entry?fixed.error:intake.error} onRefresh={analysis.entry?fixed.refresh:intake.refresh} files={files} filesLoading={loading} filesError={error} onReloadFiles={refreshMaterials} imports={imports.data??[]} importsUnknown={imports.unknown} importsError={imports.error} onFile={openFile} onNavigate={navigateAnalysis} onRequirements={onRequirements}/>
      </div>
      <div hidden={analysis.view!=='research-request'}>{requirementsVisited&&<ProjectRequirements projectId={projectId} files={files.filter((file):file is ProjectFile & {parse_status:'queued'|'parsing'|'parsed'|'failed'}=>file.parse_status!=='stored')} registerLeaveGuard={registerLeaveGuard}/>}</div>
      <div hidden={!entryAvailable||analysis.view==='overview'||analysis.view==='research-request'||bioView||insightView||researchView}>
      <AnalysisSetup projectId={projectId} files={files.filter((file):file is ProjectFile & {parse_status:'queued'|'parsing'|'parsed'|'failed'}=>file.parse_status!=='stored'&&file.file_type==='xlsx')} filesLoading={loading} filesError={error} onReloadFiles={refresh}
        onOpenFiles={() => onSectionChange('files')} stage={analysis.view==='overview'||analysis.view==='research-request'||analysis.view==='research-findings'||analysis.view.startsWith('bio-')?'setup':analysis.view as import('../analysis/analysisWorkflowContext').AnalysisStage} onStageChange={view=>navigateAnalysis({...analysis,view})} fileId={analysis.fileId} onFileChange={fileId=>navigateAnalysis({...analysis,fileId})} registerLeaveGuard={registerLeaveGuard} />
      </div>
    </div>
    </div>
    <div className={section==='files'?'resource-bio-body':'analysis-bio-body'} hidden={!sharedBioActive}>
      {qualityBioActive && navigation.bio?.view!=='bio-datasets' && <div className="resource-subview-actions"><button type="button" onClick={()=>navigateBio({view:'bio-datasets',fileId:''})}>{t('返回数据集与记录')}</button></div>}
      <BioImports allowNewAnalysis={allowNewAnalysis} projectId={projectId} navigation={sharedBioActive?desiredBio:retainedBio} onNavigate={navigateBio} active={sharedBioActive} sectioned qualityMode={section==='files'} initialFileIds={qualityBioActive?undefined:initialFileIds} entryKey={qualityBioActive?undefined:analysis.entry?`${analysis.entry.requirementVersionId}:${analysis.entry.scopeItemId}`:undefined} registerLeaveGuard={registerLeaveGuard}/>
    </div>
  </div>
}

export default function ProjectResources(props: Props) { return <ResourceScope key={props.projectId} {...props} /> }
