import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import ResearchWorkspace from '../research-results/ResearchWorkspace'
import ResearchIntake from '../research-intake/ResearchIntake'
import type { DeliveryKind } from '../research-intake/contracts'
import {deliveryLabels} from '../research-intake/contracts'
import ReviewsWorkspace from '../reviews/ReviewsWorkspace'
import JournalWorkspace from '../journals/JournalWorkspace'
import SchoolTemplates from '../school-templates/SchoolTemplates'
import ProjectManuscripts from '../manuscripts/ProjectManuscripts'
import {AnalysisWritingProvider} from '../manuscripts/AnalysisWritingContext'
import ProjectLiterature from '../literature/ProjectLiterature'
import { apiFetch } from '../../shared/api/client'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import ProjectDetails from './ProjectDetails'
import ProjectInfoActions from './ProjectInfoActions'
import ProjectResources from './ProjectResources'
import './projectContent.css'
import ProjectSummary from './ProjectSummary'
import ProjectTasks from '../tasks/ProjectTasks'
import ProjectList, { type ProjectListQuery } from './ProjectList'
import WorkspaceShell, { WorkspaceIcon, type WorkspaceView, type ProjectSection } from './WorkspaceShell'
import ProjectCreateDialog from './ProjectCreateDialog'
import ProjectJourney, { ProjectResultActions } from './ProjectJourney'
import ProjectResultNavigation from './ProjectResultNavigation'
import useProjectSelection from './useProjectSelection'
import useProjectFlow, { isAnalysisResultView } from './useProjectFlow'
import {isFixedWritingNavigation, type NavigationRoute} from './projectNavigation'
import {supportsResultOrigin,type AnalysisNavigation} from './analysisViews'
import {bulkRoute} from '../bio-insights/bulkWorkflow'
import { PROJECT_PAGE_SIZE, isProject, isProjectPage, typeNames, type Project } from './projectTypes'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import AssignedProjectList from '../analyst/AssignedProjectList'
import AnalystProgress from '../analyst/AnalystProgress'
import AnalystDelivery from '../analyst/AnalystDelivery'
import SubmittedRequirement from '../analyst/SubmittedRequirement'
import useAnalystWorkspace from '../analyst/useAnalystWorkspace'
import BioAnalysisRuns from '../bioinformatics/BioAnalysisRuns'
async function responseData(response: Response, fallback: string) {
  const data = await response.json().catch(() => null)
  if (!response.ok) throw Object.assign(new Error(apiError(data, fallback)),{status:response.status})
  return data
}
function isFixedAnalysisRead(analysis:AnalysisNavigation) {
  return analysis.view==='bulk-workflow'
    || analysis.view==='bio-analysis'&&!!analysis.runId
    || analysis.view==='bio-result'&&!!analysis.processedId
    || analysis.view==='bio-insight-plan'&&!!analysis.runId
    || analysis.view==='bio-insight-runs'
    || analysis.view==='bio-insight-result'&&!!analysis.resultVersionId
    || analysis.view==='research-findings'&&!!analysis.findingSetId&&!!analysis.findingVersionId
}

export default function ProjectWorkspace({ analysisOnly = false }: { analysisOnly?: boolean }) {
  const { t, locale } = useI18n()
  const [schoolRevision,setSchoolRevision]=useState(0)
  const [bulkOverviewRevision,setBulkOverviewRevision]=useState(0)
  const [navigationSequence, setNavigationSequence] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [writingChoice, setWritingChoice] = useState<{projectId:string;kind:'sci_draft'|'thesis_draft';awaitingServices?:boolean} | null>(null)
  const [requirementPanelRequest,setRequirementPanelRequest]=useState<{projectId:string;instanceKey:number;panel:'edit'|'materials';sequence:number}|null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState<ProjectListQuery>({ page: 1, q: '', type: '' })
  const [searchDraft, setSearchDraft] = useState('')
  const [assignedQuery, setAssignedQuery] = useState<ProjectListQuery>({ page: 1, q: '', type: '' })
  const [assignedSearchDraft, setAssignedSearchDraft] = useState('')
  const [tableResult, setTableResult] = useState<{ instanceKey: number; taskId: string } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [createError, setCreateError] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [topic, setTopic] = useState('')
  const [projectType, setProjectType] = useState<'' | 'sci' | 'thesis' | 'research'>('research')
  const [deliveryKinds,setDeliveryKinds]=useState<DeliveryKind[]>(['analysis'])
  const createIdentity=useRef<{key:string;body:string}|null>(null)
  const [createUnknown,setCreateUnknown]=useState(false)
  const createController = useRef<AbortController | null>(null)
  const listRequest = useRef<{ controller: AbortController; timeout: number } | null>(null)
  const listSequence = useRef(0)
  const unavailableIds = useRef(new Set<string>())
  const selectedRegion = useRef<HTMLElement | null>(null)
  const analystStepRegion = useRef<HTMLDivElement | null>(null)
  const listRegion = useRef<HTMLElement | null>(null)
  const workspaceRegion = useRef<HTMLDivElement | null>(null)
  const flowGate = useRef<(next: NavigationRoute) => boolean>(() => true)
  const [flowNotice, setFlowNotice] = useState('')
  const selection = useProjectSelection(id => {
    unavailableIds.current.add(id)
    setProjects(previous => previous.filter(item => item.id !== id))
    refresh()
  }, id => {
    if (unavailableIds.current.delete(id)) refresh()
  }, () => { setNavigationSequence(value => value + 1); setFlowNotice('') }, next => flowGate.current(next), analysisOnly)
  const project = selection.project
  const section = selection.section
  const resultRoute=`${project?.id}:${section}:${JSON.stringify(selection.artifactNavigation)}`
  const [resultPanel,setResultPanel]=useState({route:resultRoute,next:false})
  const resultNext=resultPanel.route===resultRoute&&resultPanel.next
  const view = selection.workspaceView
  const assigned = analysisOnly && project?.assignment_revision !== undefined
  const assignedResultsActive = assigned && view === 'project' && section === 'artifacts' && selection.artifactNavigation.view === 'list'
  const fromTableResults = assigned && tableResult?.instanceKey === selection.instance?.key
    && tableResult?.taskId === selection.taskId
  const showingTaskResult = fromTableResults || Boolean(selection.taskId && selection.taskDetailView === 'result')
  const analysisFromResults = analysisOnly && selection.analysisNavigation.fromResults
  const showingResult = section === 'artifacts'
    || section === 'analysis' && (analysisFromResults || isAnalysisResultView(selection.analysisNavigation.view))
    || section === 'tasks' && showingTaskResult
  const analyst = useAnalystWorkspace(view === 'project' && assigned ? project!.id : '', project?.assignment_revision)
  const overviewView = selection.overviewView === 'tasks' ? 'settings' : selection.overviewView
  const showingProjectInfo = view === 'project' && section === 'overview' && ['settings', 'activity', 'usage'].includes(overviewView)
  const analystInfoHeader = analysisOnly && !!project && showingProjectInfo
  const showingSubmittedRequirement = assigned && section === 'overview' && overviewView === 'requirements'
  const showingAnalystExecution = analysisOnly && !!project && (section === 'files' || section === 'analysis' && !showingResult)
  const showingAnalystResults = analysisOnly && !!project && showingResult
  const showingAnalystDelivery = analysisOnly && !!project && section === 'overview' && overviewView === 'deliveries'
  const analystStepTitle = showingAnalystResults ? '查看结果' : showingAnalystExecution ? '执行分析' : showingAnalystDelivery ? '分析交付' : undefined
  const bulkDesign = section==='analysis'&&selection.analysisNavigation.view==='bulk-workflow'&&selection.analysisNavigation.bulkView==='design'
  const flow = useProjectFlow(view !== 'project' && assigned ? null : project, section, overviewView, assigned)
  const sectionReason: typeof flow.reason = (target, overview) => {
    if (analysisOnly && (target === 'overview' || target === 'analysis')) return ''
    return flow.reason(target, overview)
  }
  flowGate.current = next => {
    const fixedAnalysisRead=next.section==='analysis'&&isFixedAnalysisRead(next.analysisNavigation)
    const reason = isFixedWritingNavigation(next) || fixedAnalysisRead ? '' : sectionReason(next.section, next.overviewView)
    if (reason) setFlowNotice(reason)
    return !reason
  }

  const selectedKey = selection.instance?.key
  useLayoutEffect(() => {
    // In-place module navigation keeps focus on its selected tab.
    const infoTabs = document.activeElement?.closest('.project-info-tabs')
    if (view === 'project' && section === 'overview' && ['settings','activity','usage'].includes(overviewView)
      && infoTabs && selectedRegion.current?.contains(infoTabs)) {
      infoTabs.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus({ preventScroll: true })
      return
    }
    const target = view === 'project' ? selectedRegion.current : listRegion.current
    target?.focus({ preventScroll: true })
    if (analystStepRegion.current) analystStepRegion.current.scrollTop = 0
    if (window.scrollY > 0) window.scrollTo({ top: 0, behavior: 'instant' })
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const animation = workspaceRegion.current?.animate?.([
      { opacity: 0.45, transform: 'translateY(6px)' },
      { opacity: 1, transform: 'translateY(0)' },
    ], { duration: 180, easing: 'cubic-bezier(.2,.7,.2,1)' })
    return () => animation?.cancel()
  }, [selectedKey, view, section, overviewView, navigationSequence])

  function navigate(next: WorkspaceView) {
    selection.navigateWorkspace(next)
  }

  function openProject(id: string) {
    selection.open(id)
  }

  function changeSection(next: ProjectSection) {
    if (next === 'tasks' && assigned && showingTaskResult) openTask('')
    else if (analysisOnly && next === 'analysis') openAnalysis()
    else selection.changeSection(next)
  }

  function closeProject() {
    selection.returnToList()
  }

  function openAnalysis() {
    const current = selection.analysisNavigation
    selection.selectAnalysis(analysisOnly && (current.fromResults || isAnalysisResultView(current.view)) ? { view: 'overview', fileId: '' } : current)
  }

  function openResultTask(taskId: string) {
    if (!selection.instance) return
    setTableResult({ instanceKey: selection.instance.key, taskId })
    selection.selectTask(taskId, 'result')
  }

  function openTask(taskId: string) {
    setTableResult(null)
    selection.selectTask(taskId)
  }

  function openResults() {
    selection.selectArtifact({ view: 'list', artifactId: '', kind: '', page: 1 })
  }

  function openAnalysisResult(next: AnalysisNavigation) {
    selection.selectAnalysis(supportsResultOrigin(next.view) ? { ...next, fromResults: true } : next)
  }

  function invalidateList() {
    listSequence.current++
    if (listRequest.current) {
      listRequest.current.controller.abort()
      window.clearTimeout(listRequest.current.timeout)
      listRequest.current = null
    }
  }

  function refresh() {
    if (analysisOnly) return
    invalidateList()
    setLoading(true)
    setLoadError('')
    setAttempt(value => value + 1)
  }

  function changeQuery(next: ProjectListQuery) {
    invalidateList()
    setLoading(true)
    setLoadError('')
    setQuery(next)
  }

  useEffect(() => {
    if (analysisOnly) return
    const controller = new AbortController()
    let active = true
    const sequence = ++listSequence.current
    const timeout = window.setTimeout(() => {
      if (!active || sequence !== listSequence.current) return
      controller.abort()
      listSequence.current++
      setLoadError('项目列表读取超时，请稍后重试。')
      setLoading(false)
    }, STANDARD_REQUEST_TIMEOUT_MS)
    listRequest.current = { controller, timeout }
    async function load() {
      try {
        const parameters = new URLSearchParams({ page: String(query.page), page_size: String(PROJECT_PAGE_SIZE) })
        if (query.q) parameters.set('q', query.q)
        if (query.type) parameters.set('type', query.type)
        const response = await apiFetch(`/api/v1/projects?${parameters}`, { signal: controller.signal })
        const result = await responseData(response, '项目列表读取失败。')
        if (!active || sequence !== listSequence.current || controller.signal.aborted) return
        if (!isProjectPage(result, query.page)) {
          throw new Error('项目列表格式不正确。')
        }
        const data = result
        const lastPage = Math.max(1, Math.ceil(data.total / PROJECT_PAGE_SIZE))
        if (query.page > lastPage) {
          changeQuery({ ...query, page: lastPage })
          return
        }
        setProjects(data.items.filter(item => !unavailableIds.current.has(item.id)))
        setTotal(data.total)
      } catch {
        if (active && sequence === listSequence.current) setLoadError('项目列表读取失败，请确认后端服务正常后重试。')
      } finally {
        window.clearTimeout(timeout)
        if (active && sequence === listSequence.current) setLoading(false)
      }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [query, attempt, analysisOnly])

  function updated(result: Project) {
    selection.update(result)
    setProjects(previous => previous.map(item => item.id === result.id ? result : item)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
    refresh()
  }

  useEffect(() => () => createController.current?.abort(), [])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (createController.current) return
    if (!name.trim() || !topic.trim()) { setCreateError('请填写项目名称和研究主题。'); return }
    if (projectType==='research'&&!deliveryKinds.length){setCreateError('请至少选择一种服务。');return}
    if (!projectType) { setCreateError('请选择项目类型。'); return }
    const controller = new AbortController()
    createController.current = controller
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, STANDARD_REQUEST_TIMEOUT_MS)
    setCreating(true)
    setCreateError('')
    try {
      const body=JSON.stringify({ name: name.trim(), research_topic: topic.trim(), project_type: projectType,...(projectType==='research'?{delivery_kinds:deliveryKinds}:{}) })
      if(projectType==='research')createIdentity.current??={key:crypto.randomUUID(),body}
      let recovered:Project|null=null
      if(createUnknown&&createIdentity.current){const read=await apiFetch(`/api/v1/project-create-requests/${encodeURIComponent(createIdentity.current.key)}`,{signal:controller.signal});if(read.ok)recovered=await read.json();else if(read.status!==404)throw new Error('创建结果尚未核实，请稍后重试。')}
      const response = recovered?new Response(JSON.stringify(recovered),{status:200}):await apiFetch('/api/v1/projects', { method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json',...(createIdentity.current&&projectType==='research'?{'Idempotency-Key':createIdentity.current.key}:{}) },
        body: projectType==='research'?createIdentity.current!.body:body,
      })
      const created: Project = await responseData(response, '创建项目失败，请检查输入后重试。')
      if (!controller.signal.aborted) {
        if (!isProject(created)) throw new Error('项目响应格式不正确，请刷新项目列表。')
        setProjects([created])
        selection.open(created.id, created, true)
        setSearchDraft('')
        changeQuery({ ...query, page: 1, q: '', type: '' })
        setName('')
        setTopic('')
        setProjectType('research');setDeliveryKinds(['analysis']);createIdentity.current=null;setCreateUnknown(false)
        setShowCreate(false)
      }
    } catch (cause) {
      const definitive=cause&&typeof cause==='object'&&'status' in cause&&typeof cause.status==='number'&&cause.status>=400&&cause.status<500
      if(projectType==='research'&&!definitive){setCreateUnknown(true)}else if(!createUnknown)createIdentity.current=null
      if (timedOut) setCreateError('创建请求超时，请先刷新项目列表确认是否已创建。')
      else if (!controller.signal.aborted) setCreateError(cause instanceof TypeError ? '无法连接后端，请稍后重试。'
        : safeError(cause, '创建项目失败。'))
    } finally {
      window.clearTimeout(timeout)
      createController.current = null
      if (!controller.signal.aborted || timedOut) setCreating(false)
    }
  }

  const recentProject = view === 'home' && !query.q && !query.type && query.page === 1 && !loadError ? projects[0] : undefined
  const returnToListButton = <button type="button" className="project-back button-quiet" aria-label={t('返回项目列表')} onClick={closeProject}>← {t('返回项目列表')}</button>
  const projectContentClass = [
    section === 'artifacts' && 'project-results-page',
    analystStepTitle && 'project-details-card analyst-project-details',
    showingAnalystExecution && 'analyst-execution-card',
    showingAnalystResults && 'analyst-results-card',
    showingAnalystDelivery && 'analyst-delivery-card',
  ].filter(Boolean).join(' ')
  function openRequirements(panel?:'materials') {
    if(!project||!selection.instance)return
    setRequirementPanelRequest(previous=>({projectId:project.id,instanceKey:selection.instance!.key,panel:panel??'edit',sequence:(previous?.sequence??0)+1}))
    selection.changeOverviewView('requirements')
  }
  function continueWriting(kind:'sci_draft'|'thesis_draft') {
    if (!project) return
    setWritingChoice({projectId:project.id,kind})
    if (project.project_type === 'research') selection.startWritingSelection()
    else selection.selectManuscriptView('materials')
  }

  return <WorkspaceShell view={view} analysisOnly={analysisOnly} onNavigate={navigate} onCreate={() => setShowCreate(true)} projectName={analysisOnly && view !== 'project' ? undefined : project?.name} projectType={project?.project_type}
    section={section} overviewView={overviewView} onOverviewChange={selection.changeOverviewView} sectionBlocked={sectionReason} hasAnalysis={flow.hasAnalysis}
    showingResult={showingResult} onSectionChange={changeSection} onCurrentProject={() => navigate('project')}>
    <div ref={workspaceRegion} className="project-workspace">
    <section ref={listRegion} tabIndex={-1} hidden={view === 'project'} aria-labelledby="projects-title"
      className={view === 'assigned' ? 'project-list-panel' : undefined}>
    <div className="workspace-page-heading project-list-title"><h1 id="projects-title">{t(analysisOnly ? '分配给我的项目' : view === 'home' ? '工作台' : '我的项目')}</h1></div>
    {recentProject && <section className="continue-research" aria-label={t('最近更新的研究')}>
      <div className="continue-research-icon" aria-hidden="true"><WorkspaceIcon name="file" /></div>
      <div className="continue-research-copy"><span className="workspace-eyebrow">{t('最近更新的研究')}</span><h2>{recentProject.name}</h2>
        <p>{recentProject.research_topic}</p><span className="muted">{t('最近更新 {date}', { date: new Date(recentProject.updated_at).toLocaleDateString(locale) })}</span></div>
      <button type="button" onClick={() => openProject(recentProject.id)}>{t('继续研究')}<WorkspaceIcon name="arrow" /></button>
    </section>}
    {analysisOnly ? view === 'assigned' && <AssignedProjectList query={assignedQuery} searchDraft={assignedSearchDraft}
      onQueryChange={setAssignedQuery} onSearchDraftChange={setAssignedSearchDraft} onOpen={openProject}/> : <ProjectList items={projects} total={total} query={query} searchDraft={searchDraft} loading={loading} error={loadError}
      onSearchDraftChange={setSearchDraft} onQueryChange={changeQuery} onOpen={openProject} onRetry={refresh}
      presentation={view === 'home' ? 'cards' : 'table'} />}
    </section>
    {!analysisOnly && showCreate && <ProjectCreateDialog busy={creating} onClose={() => setShowCreate(false)}>
    <form className="project-form" onSubmit={create} aria-busy={creating}>
      <div className="project-fields">
        <label>{t("项目名称")}<input placeholder={t('例如：药物干预后的表达变化研究')} value={name} onChange={event => setName(event.target.value)} required maxLength={120} disabled={creating||createUnknown} /></label>
        <label>{t("项目类型")}<select value={projectType} onChange={event => setProjectType(event.target.value as '' | 'sci' | 'thesis' | 'research')} required disabled={creating||createUnknown}>
          <option value="research">{t('研究项目')}</option><option value="">{t("请选择项目类型")}</option><option value="sci">{t("SCI 科研论文")}</option><option value="thesis">{t("毕业论文")}</option>
        </select></label>
      </div>
      {projectType==='research'&&<fieldset className="create-service-options" disabled={creating||createUnknown}><legend>{t('所需服务')}</legend>{(Object.keys(deliveryLabels) as DeliveryKind[]).map(kind=><label key={kind}><input type="checkbox" checked={deliveryKinds.includes(kind)} onChange={e=>setDeliveryKinds(e.target.checked?[...deliveryKinds,kind]:deliveryKinds.filter(k=>k!==kind))}/>{t(deliveryLabels[kind])}</label>)}<p>{t('可以多选，也可以先做分析，之后再添加论文写作。')}</p></fieldset>}
      <label>{t("研究主题")}<textarea placeholder={t('用一句话描述你想研究什么，或比较哪些差异。')} value={topic} onChange={event => setTopic(event.target.value)} required maxLength={500} rows={3} disabled={creating||createUnknown} /></label>

      {createError && <p className="error-panel" role="alert">{t(createError)}</p>}
      <div className="project-form-actions"><button type="submit" className="button-primary" disabled={creating}>{creating ? t("正在创建……") : t(createUnknown?'核对创建结果':'创建项目')}</button>
        <button type="button" disabled={creating} onClick={() => setShowCreate(false)}>{t('取消创建')}</button></div>
    </form>
    </ProjectCreateDialog>}

    {selection.unavailableId && <div className="error-panel" role="alert">{t("项目不存在或无权访问。")}{' '}
      <button type="button" className="project-back button-quiet" aria-label={t('返回项目列表')} onClick={closeProject}>← {t("返回项目列表")}</button>{' '}
      <button type="button" onClick={() => openProject(selection.unavailableId)}>{t("重试打开项目")}</button>
    </div>}
    {selection.instance && <section ref={selectedRegion} hidden={view !== 'project'} tabIndex={-1} className="selected-project" aria-label={t("当前项目工作区")}>
      {!analystInfoHeader && !showingSubmittedRequirement && !analystStepTitle && (analysisOnly || !['files','analysis','artifacts','tasks'].includes(section) && !(section === 'overview' && ['requirements','design','settings','activity','usage'].includes(overviewView))) && returnToListButton}
      {selection.loading && <p role="status">{t("正在读取项目详情……")}</p>}
      {selection.error && <div className="error-panel" role="alert">{t(selection.error)}{' '}
        <button type="button" onClick={selection.refresh}>{t("重试项目详情")}</button>
      </div>}
      {project && (!assigned || view === 'project') && <ProjectWritingScope key={`${selection.instance.key}:${project.assignment_revision ?? ''}`} analysisOnly={analysisOnly} project={project} onOpenWriting={()=>selection.selectManuscriptView('materials')}>
        <div className={projectContentClass || undefined} ref={analystStepTitle ? analystStepRegion : undefined}
          role={analystStepTitle ? 'region' : undefined} aria-label={analystStepTitle ? t(analystStepTitle) : undefined}
          tabIndex={analystStepTitle ? 0 : undefined}>
        <ProjectJourney analysisOnly={analysisOnly} analysisView={selection.analysisNavigation.view} analysisFromResults={analysisFromResults} showingTaskResult={showingTaskResult}
          workflowState={flow.workflowState ?? undefined} blocked={(target,overview)=>target==='analysis'&&isFixedAnalysisRead(selection.analysisNavigation)?'':sectionReason(target,overview)}
          hasAnalysis={flow.hasAnalysis} onWriting={()=>selection.selectManuscriptView(project.project_type==='research'?'research-selection':'materials')}
          active={view === 'project'} project={project} section={section} overviewView={overviewView}
          onOverview={next=>next==='requirements'?openRequirements():selection.changeOverviewView(next)}
          onUpload={()=>selection.selectResource({view:'upload',fileId:''})} onAnalysis={openAnalysis} onResults={openResults}/>
        {showingAnalystResults && section !== 'analysis' && <header className="analyst-project-details-heading">
          <h1>{t('查看结果')}</h1>
          {returnToListButton}
        </header>}
        {section === 'artifacts' && <ProjectResultNavigation analysisOnly={analysisOnly} navigation={selection.artifactNavigation} nextActive={resultNext} onNext={()=>analysisOnly ? selection.changeOverviewView('deliveries') : setResultPanel({route:resultRoute,next:true})} onNavigate={next=>{setResultPanel({route:resultRoute,next:false});selection.selectArtifact(next)}}/> }
        {flowNotice&&<p role="status" className="warning-panel">{t(flowNotice)}</p>}
        <div hidden={section !== 'overview'}>
          <ProjectInfoActions key={project.id} project={project} view={overviewView} onViewChange={selection.changeOverviewView} analysisOnly={analysisOnly}
            active={showingProjectInfo} headerAction={analystInfoHeader ? returnToListButton : undefined}
            error={flow.error} onOpenJournals={()=>changeSection('journals')} onOpenManuscripts={()=>changeSection('manuscripts')}>
            {assigned ? <>
              <dl className="analyst-project-info">
                <div><dt>{t('研究主题')}</dt><dd>{project.research_topic}</dd></div>
                <div><dt>{t('项目类型')}</dt><dd>{t(typeNames[project.project_type])}</dd></div>
                <div><dt>{t('文件数')}</dt><dd>{project.file_count}</dd></div>
              </dl>
              {showingProjectInfo && overviewView === 'settings' && <AnalystProgress projectId={project.id} workspace={analyst}/>}
            </> : <ProjectDetails project={project} onUpdated={updated} showHeading={false} registerLeaveGuard={selection.registerLeaveGuard}
              renderHeader={analysisOnly ? undefined : language => <header className="project-info-header">
                <div className="project-info-heading-row"><div className="project-info-label"><WorkspaceIcon name="folder"/><h2>{t('项目资料')}</h2></div>{language}</div>
              </header>}/>}
          </ProjectInfoActions>
          {showingSubmittedRequirement && <SubmittedRequirement projectId={project.id} workspace={analyst}
            onDesign={()=>selection.changeOverviewView('design')} headerAction={returnToListButton}/>}
          {!analysisOnly&&overviewView==='deliveries'&&<button type="button" onClick={openResults}>{t('返回成果列表')}</button>}
        </div>
        <div className="result-summary-host" hidden={section !== 'artifacts'||resultNext||selection.artifactNavigation.view.startsWith('research-')}>
          {assigned ? <>
              <BioAnalysisRuns projectId={project.id} active={assignedResultsActive} resultsOnly title="生信分析结果与 Word"
                onNavigate={openAnalysisResult} headerAction={assignedResultsActive && <button type="button" className="button-quiet"
                  onClick={() => selection.selectAnalysis({ view: 'bio-insight-runs', fileId: '' })}>{t('查看洞察分析结果')}</button>}/>
              <ProjectTasks projectId={project.id} active={assignedResultsActive} resultsOnly selectedTaskId="" onSelectTask={openResultTask}/>
            </>
            : <ProjectSummary onAnalysisNavigate={selection.selectAnalysis} showArtifactNavigation={false} artifactNavigation={selection.artifactNavigation} onArtifactNavigate={selection.selectArtifact} key={`${project.id}:${schoolRevision}`} projectId={project.id} projectType={project.project_type} view={section === 'artifacts' ? 'artifacts' : 'overview'}
              active={view === 'project' && section === 'artifacts'&&!resultNext&&!selection.artifactNavigation.view.startsWith('research-')} onOpenJournals={analysisOnly?undefined:()=>changeSection('journals')} onOpenManuscripts={analysisOnly?undefined:()=>changeSection('manuscripts')} />}
        </div>
        {!analysisOnly && <>
          {project.project_type === 'thesis' && <SchoolTemplates navigation={selection.schoolTemplateNavigation} onNavigate={selection.selectSchoolTemplate} registerLeaveGuard={selection.registerLeaveGuard} projectId={project.id} onChanged={()=>setSchoolRevision(value=>value+1)} active={view === 'project' && section === 'school-templates'} />}
          {project.project_type==='research'&&['reviews','journals'].includes(section)&&<section className="warning-panel"><h2>{t('已登记，当前流程未开放')}</h2><p>{t('研究项目的期刊和独立意见修改入口仍未开放，请使用已发布稿件的受控写作流程。')}</p><button type="button" onClick={()=>selection.changeOverviewView('deliveries')}>{t('交付登记')}</button></section>}
          {project.project_type!=='research'&&<ReviewsWorkspace view={selection.reviewView} selectedItemId={selection.reviewItemId} onViewChange={selection.selectReviewView} onSelectItem={selection.selectReviewItem} onSelectRun={selection.selectReviewRun} onSelectDocument={selection.selectReviewDocument} registerLeaveGuard={selection.registerLeaveGuard} projectId={project.id} projectType={project.project_type} active={view==='project'&&section==='reviews'} roundId={selection.reviewLink.round} initialManuscript={selection.reviewLink.manuscript} initialRevision={selection.reviewLink.revision} initialRun={selection.reviewLink.run} initialDocument={selection.reviewLink.document} onSelectRound={selection.selectRound} onOpenTask={selection.selectTask}/>}
          {project.project_type!=='research'&&<ProjectManuscripts view={selection.manuscriptView} onViewChange={selection.selectManuscriptView} onSelectVersion={selection.selectManuscriptVersion} registerLeaveGuard={selection.registerLeaveGuard} initialManuscript={selection.manuscriptLink.id} initialRevision={selection.manuscriptLink.revision} projectType={project.project_type} projectId={project.id} researchTopic={project.research_topic} outputLanguage={project.default_output_language??'zh-CN'} active={view==='project'&&section==='manuscripts'} onOpenTask={selection.selectTask} onOpenLiterature={()=>selection.selectLiterature('')}/>}
          {project.project_type === 'sci' && <JournalWorkspace view={selection.journalView} onViewChange={selection.selectJournalView} initialAdaptation={selection.adaptationId} onSelectAdaptation={selection.selectJournalAdaptation} registerLeaveGuard={selection.registerLeaveGuard} projectId={project.id} active={view==='project'&&section==='journals'} onOpenTask={selection.selectTask}/>}
          <ProjectLiterature projectId={project.id} researchTopic={project.research_topic} outputLanguage={project.default_output_language??'zh-CN'} active={view==='project'&&section==='literature'} initialSearchId={selection.literatureSearchId} onSearchChange={selection.selectLiterature} onOpenTask={selection.selectTask} literatureNavigation={selection.literatureNavigation} onLiteratureNavigate={selection.selectLiteratureView} registerLeaveGuard={selection.registerLeaveGuard}/>
        </>}
        <ProjectTasks assigned={assigned} detailView={selection.taskDetailView} onDetailViewChange={selection.selectTaskDetailView} registerLeaveGuard={selection.registerLeaveGuard} onOpenJournals={analysisOnly?undefined:()=>changeSection('journals')} onOpenManuscripts={analysisOnly?undefined:()=>changeSection('manuscripts')} onOpenFiles={() => changeSection('files')} projectId={project.id} active={view === 'project' && section === 'tasks'}
          selectedTaskId={selection.taskId} onSelectTask={openTask} onBackToResults={assigned && showingTaskResult ? openResults : undefined}
          onOpenLiterature={analysisOnly?undefined:selection.selectLiterature} />
        <ProjectResources analysisOnly={analysisOnly} assigned={assigned} assignmentRevision={assigned ? project.assignment_revision : undefined}
          analystWorkspace={assigned ? analyst : undefined} headerAction={showingAnalystExecution || showingAnalystResults && section === 'analysis' ? returnToListButton : undefined}
          onBackToResults={showingAnalystResults && section === 'analysis' ? openResults : undefined}
          onDeliveries={() => selection.changeOverviewView('deliveries')} allowNewAnalysis={flow.reason('analysis')===''}
          savedRequirement={flow.savedRequirement} onRequirements={openRequirements} analysisNavigation={selection.analysisNavigation}
          onAnalysisNavigate={showingAnalystResults ? openAnalysisResult : selection.selectAnalysis} projectId={project.id} active={view === 'project'} section={section} onSectionChange={changeSection}
          onSaved={() => { refresh(); flow.refresh(); selection.refresh() }} resourceNavigation={selection.resourceNavigation}
          onResourceNavigate={selection.selectResource} registerLeaveGuard={selection.registerLeaveGuard}
          outputLanguage={project.default_output_language} bulkOverviewRevision={bulkOverviewRevision} />
        <ResearchWorkspace analysisOnly={analysisOnly} writingSource={selection.writingSource} writingDeliveryId={selection.writingDeliveryId} onWritingSource={source=>{setWritingChoice(null);selection.selectWritingSource(source)}} onWritingDelivery={id=>{setWritingChoice(null);selection.selectWritingDelivery(id)}} onReturnSource={()=>{const source=selection.writingSource;if(!source)return;if(source.kind==='research_finding_version'&&source.setId)selection.selectAnalysis({view:'research-findings',fileId:'',findingSetId:source.setId,findingVersionId:source.id});else if(source.kind!=='research_finding_version')selection.selectArtifact({view:source.kind==='research_figure_version'?'research-figures':'research-reports',artifactId:source.id,kind:'',page:1})}} onOpenTask={selection.selectTask} sectionBlocked={sectionReason} preferredDeliveryKind={writingChoice?.projectId===project.id?writingChoice.kind:undefined} onManageServices={()=>{setWritingChoice(previous=>previous?.projectId===project.id?{...previous,awaitingServices:true}:previous);openRequirements()}} projectId={project.id} projectType={project.project_type} active={view==='project'&&(section!=='artifacts'||!resultNext)} section={section} analysis={selection.analysisNavigation} artifact={selection.artifactNavigation} manuscriptView={selection.manuscriptView} candidateId={selection.researchCandidateId} manuscriptId={selection.manuscriptLink.id} revision={selection.manuscriptLink.revision} onAnalysis={selection.selectAnalysis} onArtifact={selection.selectArtifact} onManuscriptView={selection.selectManuscriptView} onCandidate={selection.selectResearchCandidate} onPublished={(id,revision,view)=>selection.selectManuscriptVersion(id,revision,view??'body')} registerLeaveGuard={selection.registerLeaveGuard} schoolNavigation={selection.schoolTemplateNavigation} onSchoolNavigate={selection.selectSchoolTemplate}/>
        {section==='overview'&&['requirements','design'].includes(overviewView)&&selection.analysisNavigation.bulkView&&
          <button type="button" onClick={()=>selection.selectAnalysis(bulkRoute('design'))}>{t('返回 Bulk RNA-seq 工作流')}</button>}
        {analysisOnly && <AnalystDelivery projectId={project.id} active={view==='project'&&showingAnalystDelivery}
          deliveryId={selection.deliveryId} snapshotId={selection.deliverySnapshotId} onSelect={selection.selectDelivery}
          registerLeaveGuard={selection.registerLeaveGuard} workspace={assigned?analyst:undefined}
          onBackToResults={openResults} headerAction={returnToListButton}/>}
        {(!assigned || bulkDesign || overviewView==='design') && <ResearchIntake analysisOnly={analysisOnly} designOnly={assigned} onDesignSaved={bulkDesign?()=>setBulkOverviewRevision(value=>value+1):undefined} panelRequest={!bulkDesign&&requirementPanelRequest?.projectId===project.id&&requirementPanelRequest.instanceKey===selection.instance!.key?requirementPanelRequest:undefined} onViewChange={selection.changeOverviewView} onRequirementSaved={flow.acceptServices} continueLabel={writingChoice?.projectId===project.id&&writingChoice.awaitingServices?'保存需求并继续':undefined} onContinue={(services,version)=>{flow.acceptServices(services,version);if(writingChoice?.projectId===project.id&&writingChoice.awaitingServices&&services.includes(writingChoice.kind)){continueWriting(writingChoice.kind)}else if(services.includes('analysis')){setWritingChoice(null);selection.selectAnalysis(selection.analysisNavigation.bulkView?bulkRoute('data'):{view:'overview',fileId:selection.analysisNavigation.fileId})}else if(!analysisOnly){continueWriting(services.includes('sci_draft')?'sci_draft':'thesis_draft')}}} deliveryId={selection.deliveryId} snapshotId={selection.deliverySnapshotId} onDeliverySelect={selection.selectDelivery} projectId={project.id} view={section==='analysis'&&selection.analysisNavigation.bulkView?'design':analysisOnly&&overviewView==='deliveries'?'requirements':overviewView} active={view==='project'&&(bulkDesign||section==='overview'&&['requirements','design',...analysisOnly?[]:['deliveries']].includes(overviewView))} registerLeaveGuard={selection.registerLeaveGuard}/>}
        {!analysisOnly && section === 'artifacts' && <div className="result-next-panel" hidden={!resultNext}><ProjectResultActions projectType={project.project_type} onWriting={continueWriting} onExit={closeProject} onExistingManuscripts={()=>selection.selectManuscriptView('list')} onDeliveries={()=>selection.changeOverviewView('deliveries')}/></div>}
      </div></ProjectWritingScope>}
    </section>}
  </div>
  </WorkspaceShell>
}

function ProjectWritingScope({project,onOpenWriting,children,analysisOnly}:{project:Project;onOpenWriting:()=>void;children:ReactNode;analysisOnly:boolean}){return analysisOnly||project.project_type==='research'?children:<AnalysisWritingProvider projectId={project.id} projectType={project.project_type} onOpenWriting={onOpenWriting}>{children}</AnalysisWritingProvider>}
