import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { watchProjectAccess } from '../../shared/api/projectAccess'
import ModuleViews, { ModuleView } from '../../shared/components/ModuleViews'
import { useI18n } from '../../shared/i18n'
import ProjectDetails from '../projects/ProjectDetails'
import ProjectList, { type ProjectListQuery } from '../projects/ProjectList'
import { customerProjectTypeNames, type Project, type ProjectPage } from '../projects/projectTypes'
import type { LeaveGuard, RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { WorkspaceFrame, WorkspaceIcon } from '../projects/WorkspaceShell'
import WorkspaceSteps from '../projects/WorkspaceSteps'
import { taskDetailViews } from '../projects/reviewViews'
import { isTaskId } from '../tasks/taskTypes'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import CustomerDeliveries from './CustomerDeliveries'
import CustomerLegacyTask from './CustomerLegacyTask'
import CustomerMaterials, { ThesisMaterialOrganizer } from './CustomerMaterials'
import CustomerProgress from './CustomerProgress'
import CustomerProjectCreate from './CustomerProjectCreate'
import CustomerRequirements from './CustomerRequirements'
import CustomerSciFigures from './CustomerSciFigures'
import CustomerSciResources from './CustomerSciResources'
import CustomerSciSettings from './CustomerSciSettings'
import CustomerSciTemplate from './CustomerSciTemplate'
import CustomerSciWorkflow from './CustomerSciWorkflow'
import CustomerThesisRequirements, { ThesisTemplateOrganizer } from './CustomerThesisRequirements'
import CustomerWritingMaterials from './CustomerWritingMaterials'
import { schoolTemplateViews } from '../projects/manuscriptViews'
import SchoolTemplates from '../school-templates/SchoolTemplates'
import { readLegacyCustomerRoute } from './customerLegacyNavigation'
import { readCustomerReviewNavigation, validCustomerRouteId } from './customerReviewNavigation'
import { readSummary, summaryRoute } from './customerWorkspaceApi'
import { buildReturn, readReturn } from './returnToken'
import './customerWorkspace.css'

const analysisSteps = [
  ['details', '项目资料'],
  ['upload', '上传资料'],
  ['requirements', '选择需求'],
  ['progress', '任务进度'],
  ['deliveries', '查看交付'],
] as const
const paperSteps = [
  ['details', '项目资料'],
  ['materials', '上传资料'],
  ['manuscripts', '文献与初稿'],
] as const
const thesisSteps = [paperSteps[0], paperSteps[1], ['thesis-figures', '图件拼版'], ['school', '模板与资料整理'], paperSteps[2]] as const
const sciSteps = [paperSteps[0], paperSteps[1], ['sci-figures', '图件拼版'], ['sci-template', '模板设定和资源配置'], paperSteps[2]] as const
type Step = typeof analysisSteps[number][0] | typeof sciSteps[number][0] | typeof thesisSteps[number][0] | 'word' | 'reviews' | 'citations' | 'tasks' | 'journals'
type Route = { projectId: string; step: Step; params?: URLSearchParams } | null
type RouteOptions = { confirmed?: boolean; replace?: boolean }
const allowedSteps = new Set<string>([...analysisSteps, ...sciSteps, ...thesisSteps].map(([key]) => key))
for (const key of ['word', 'reviews', 'citations', 'tasks', 'journals']) allowedSteps.add(key)
const navigationIndexKey = 'paperassistCustomerNavigationIndex'
// Customers see about one screen of project cards per page (user decision 2026-11-20); analysts keep five.
const customerPageSize = 12

function readRoute(): Route {
  return routeFromHash(window.location.hash)
}

function routeFromHash(hash: string): Route {
  const params = new URLSearchParams(hash.slice(1))
  if (!params.has('customer-project')) return readLegacyCustomerRoute(hash)
  const projectId = params.get('customer-project')
  if (!validCustomerRouteId(projectId) || new Set(params.keys()).size !== [...params.keys()].length) return null
  const requested = params.get('step')
  const step = requested && allowedSteps.has(requested) ? requested as Step : 'details'
  params.delete('customer-project')
  params.delete('step')
  if (step === 'reviews' && !readCustomerReviewNavigation(params)) return null
  if (step === 'tasks' && !isTaskId(params.get('task'))) return null
  return { projectId, step, params }
}

function address(route: Route) {
  if (!route) return ''
  const params = new URLSearchParams({ 'customer-project': route.projectId, step: route.step })
  route.params?.forEach((value, key) => params.append(key, value))
  return '#' + params.toString()
}

export default function CustomerWorkspace() {
  const { t } = useI18n()
  const [route, setRoute] = useState(readRoute)
  const currentRoute = useRef(route)
  const navigationIndex = useRef(0)
  const restoringEntry = useRef(false)
  const [unavailable, setUnavailable] = useState('')
  const [creating, setCreating] = useState(false)
  const [query, setQuery] = useState<ProjectListQuery>({ page: 1, q: '', type: '' })
  const [search, setSearch] = useState('')
  const [chapterRevision, setChapterRevision] = useState(0)
  const [figureConfigRevision, setFigureConfigRevision] = useState(0)
  // Summary landing for “打开项目” only (接口设计第一节 2); `failed` keeps the retry on project details.
  const [landing, setLanding] = useState<{ projectId: string; attempt: number; failed: boolean } | null>(null)
  const projectListHeading = useRef<HTMLHeadingElement | null>(null)
  const heading = useRef<HTMLHeadingElement | null>(null)
  const guards = useRef(new Map<LeaveGuard, () => boolean>())
  const registerLeaveGuard = useCallback<RegisterLeaveGuard>((guard, isDirty = () => true) => {
    guards.current.set(guard, isDirty)
    return () => { guards.current.delete(guard) }
  }, [])
  // Form drafts are restored on re-entry. Browser File handles are local to the upload step.
  const canLeave = useCallback((next?: Route) => {
    const current = currentRoute.current
    const samePage = current && next && current.projectId === next.projectId && current.step === next.step
    const editingTemplate = current?.step === 'school' || current?.step === 'sci-template' || current?.params?.has('schoolView')
    const preserveDraft = !editingTemplate && (!!samePage ||
      !['upload', 'school', 'materials', 'sci-figures', 'thesis-figures', 'citations', 'manuscripts', 'journals', 'word', 'reviews', 'tasks'].includes(current?.step ?? ''))
    return [...guards.current.keys()].every(guard => guard(preserveDraft))
  }, [])

  const projectId = route?.projectId ?? ''
  const projectUnavailable = !!projectId && unavailable === projectId
  const onUnavailable = useCallback(() => setUnavailable(projectId), [projectId])
  useLayoutEffect(() => projectId ? watchProjectAccess(projectId, onUnavailable) : undefined, [projectId, onUnavailable])

  const params = new URLSearchParams({ page: String(query.page), page_size: String(customerPageSize) })
  if (query.q) params.set('q', query.q)
  if (query.type) params.set('type', query.type)
  const list = useResearchRead<ProjectPage>(`/api/v1/projects?${params}`, !route)
  const details = useResearchRead<Project>(projectId ? projectBase(projectId) : '', !!projectId && !projectUnavailable)
  const project = !details.error && !projectUnavailable && details.data?.id === projectId ? details.data : null
  const isAnalysis = project?.project_type === 'research'
  const isSci = project?.project_type === 'sci'
  const isThesis = project?.project_type === 'thesis'
  const writingSteps = isThesis ? thesisSteps : sciSteps
  const projectSteps = isAnalysis ? analysisSteps : writingSteps
  const hasAnalysisHistory = project?.has_analysis_history === true
  const allowedStep = (step: Step) => step === 'details' || step === 'tasks' || step === 'deliveries' && hasAnalysisHistory ||
    (isAnalysis && analysisSteps.some(([key]) => key === step)) ||
    ((isSci || isThesis) && writingSteps.some(([key]) => key === step))
  const requestedStep = route?.step === 'upload' && (isSci || isThesis) ? 'materials' : route?.step
  const routeParams = route?.params ?? new URLSearchParams()
  const oldLiterature = requestedStep === 'materials' &&
    ['search', 'list', 'detail', 'history', 'evidence', 'citations'].includes(routeParams.get('view') ?? '')
  const oldPaperPage = (isSci || isThesis) && (oldLiterature || ['citations', 'reviews', 'word'].includes(requestedStep ?? '') ||
    isSci && (requestedStep === 'journals' || requestedStep === 'tasks'))
  const legacySchool = isThesis && requestedStep === 'details' && routeParams.has('schoolView')
  const activeStep = legacySchool ? 'school' : oldPaperPage ? 'manuscripts' : requestedStep && allowedStep(requestedStep) ? requestedStep : 'details'
  const templateId = routeParams.get('template')
  const templateView = schoolTemplateViews.find(view => view === (routeParams.get('schoolView') ?? routeParams.get('view')))
  const schoolPanel = activeStep === 'school' && (!!templateView || !!templateId)
  const sciResources = activeStep === 'sci-template' && routeParams.get('view') === 'resources'
  const manuscriptParams = new URLSearchParams(routeParams)
  if (isThesis && requestedStep === 'word' && routeParams.has('manuscript') && !routeParams.has('writingRequest')) manuscriptParams.set('view', 'saved')
  if (isThesis && requestedStep === 'reviews') {
    const oldReview = readCustomerReviewNavigation(routeParams)
    if (oldReview?.roundId) manuscriptParams.set('view', 'past-opinions')
    else if (oldReview?.manuscriptId && oldReview.revision) {
      manuscriptParams.set('manuscript', oldReview.manuscriptId)
      manuscriptParams.set('revision', String(oldReview.revision))
      manuscriptParams.set('view', 'feedback')
    }
  }
  // Wireframe 02: the supplement page is reached from progress with a token back to it, or directly from the summary.
  const supplementing = isAnalysis && activeStep === 'upload' && routeParams.get('mode') === 'supplement'

  const navigate = useCallback((next: Route, { confirmed = false, replace = false }: RouteOptions = {}) => {
    // Any navigation by the customer supersedes a summary landing that has not arrived yet.
    setLanding(null)
    if (address(next) === address(currentRoute.current) || (!confirmed && !canLeave(next))) return
    currentRoute.current = next
    const url = window.location.pathname + window.location.search + address(next)
    if (replace) {
      window.history.replaceState({ ...window.history.state, [navigationIndexKey]: navigationIndex.current }, '', url)
    } else {
      navigationIndex.current += 1
      window.history.pushState({ ...window.history.state, [navigationIndexKey]: navigationIndex.current }, '', url)
    }
    setRoute(next)
  }, [canLeave])

  useEffect(() => {
    const savedIndex = window.history.state?.[navigationIndexKey]
    navigationIndex.current = Number.isInteger(savedIndex) ? savedIndex : 0
    window.history.replaceState({ ...window.history.state, [navigationIndexKey]: navigationIndex.current }, '')
    const restore = () => {
      let nextIndex = window.history.state?.[navigationIndexKey]
      if (restoringEntry.current) {
        if (nextIndex === navigationIndex.current) restoringEntry.current = false
        return
      }
      const next = readRoute()
      if (address(next) === address(currentRoute.current)) {
        if (Number.isInteger(nextIndex)) navigationIndex.current = nextIndex
        return
      }
      if (!Number.isInteger(nextIndex) || nextIndex === navigationIndex.current) {
        nextIndex = navigationIndex.current + 1
        window.history.replaceState({ ...window.history.state, [navigationIndexKey]: nextIndex }, '')
      }
      if (!canLeave(next)) {
        restoringEntry.current = true
        window.history.go(navigationIndex.current - nextIndex)
        return
      }
      navigationIndex.current = nextIndex
      currentRoute.current = next
      setLanding(null)
      setRoute(next)
    }
    const warn = (event: BeforeUnloadEvent) => {
      if ([...guards.current.values()].some(isDirty => isDirty())) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('popstate', restore)
    window.addEventListener('hashchange', restore)
    window.addEventListener('beforeunload', warn)
    return () => {
      window.removeEventListener('popstate', restore)
      window.removeEventListener('hashchange', restore)
      window.removeEventListener('beforeunload', warn)
    }
  }, [canLeave])

  useLayoutEffect(() => {
    const target = projectId ? heading.current : projectListHeading.current
    target?.focus({ preventScroll: true })
    if (window.scrollY > 0) window.scrollTo({ top: 0, behavior: 'instant' })
  }, [projectId, activeStep, project?.id, schoolPanel, sciResources, supplementing])

  // Read only here: refresh, Back/Forward and deep links restore from the address instead.
  const pendingLanding = landing && !landing.failed ? landing : null
  useEffect(() => {
    if (!pendingLanding) return
    const { projectId: id } = pendingLanding
    const opened = address({ projectId: id, step: 'details' })
    const controller = new AbortController()
    readSummary(id, controller.signal).then(value => {
      if (controller.signal.aborted || address(currentRoute.current) !== opened) return
      setLanding(null)
      const next = summaryRoute(value, id)
      if (next && allowedSteps.has(next.step)) navigate({ projectId: id, step: next.step as Step, params: next.params }, { replace: true })
    }, () => {
      if (controller.signal.aborted || address(currentRoute.current) !== opened) return
      setLanding(current => current === pendingLanding ? { ...current, failed: true } : current)
    })
    return () => controller.abort()
  }, [pendingLanding, navigate])

  function openProject(id: string) {
    if (unavailable === id) setUnavailable('')
    navigate({ projectId: id, step: 'details' })
    if (address(currentRoute.current) === address({ projectId: id, step: 'details' })) {
      setLanding(current => ({ projectId: id, attempt: (current?.attempt ?? 0) + 1, failed: false }))
    }
  }

  function retryLanding() {
    if (landing?.failed && landing.projectId === projectId) setLanding({ ...landing, attempt: landing.attempt + 1, failed: false })
  }

  const returnTarget = project ? readReturn(routeParams, project.id) : null
  function openSupplement() {
    const current = currentRoute.current
    if (!project || !current) return
    navigate({ projectId: project.id, step: 'upload', params: new URLSearchParams({
      mode: 'supplement', ...buildReturn(new URLSearchParams(address(current).slice(1)), 'progress'),
    }) })
  }
  function followReturn(href: string, confirmed = false, fallback: Step = 'progress') {
    const next = routeFromHash(href)
    if (next && project && next.projectId === project.id) navigate(next, { confirmed })
    else chooseStep(fallback, confirmed)
  }

  // Writing materials take a published analysis result (B05 task 6, wireframe 18). The files view is written into the
  // current address first, so the token and Back both lead to it; the step and project stay the same.
  function openMaterialsAnalysisResults() {
    const current = currentRoute.current
    if (!project || !current || current.projectId !== project.id || (current.step !== 'materials' && current.step !== 'citations')) return
    const origin = new URLSearchParams(current.params)
    for (const key of ['view', 'analysisProject', 'analysisSnapshot']) origin.delete(key)
    origin.set('view', 'files')
    const here = { ...current, params: origin }
    navigate(here, { confirmed: true, replace: true })
    navigate({ projectId: project.id, step: current.step, params: new URLSearchParams({
      view: 'analysis-results', ...buildReturn(new URLSearchParams(address(here).slice(1)), 'materials'),
    }) })
  }
  function finishSupplement() {
    if (returnTarget) followReturn(returnTarget.href, true)
    else chooseStep('progress', true)
  }

  // Choosing a step leaves the target page, so it deliberately drops any return token.
  function chooseStep(step: Step, confirmed = false, view?: string) {
    if (project && allowedStep(step)) {
      navigate({ projectId: project.id, step, params: view ? new URLSearchParams({ view }) : undefined }, { confirmed })
    }
  }

  // Copies the current parameters, so `return` and its location parameters stay in place.
  function updatePaperRoute(patch: Record<string, string | number | undefined>, confirmed = false, replace = false) {
    const current = currentRoute.current
    if (!current || current.projectId !== projectId) return
    const next = new URLSearchParams(current.params)
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, String(value))
      else next.delete(key)
    }
    navigate({ ...current, step: activeStep, params: next }, { confirmed, replace })
  }

  return <WorkspaceFrame className="customer-workbench" homeLabel="返回我的项目" onHome={() => navigate(null)}
    location={route ? undefined : '我的项目'}
    sidebarAction={closeMenu => <button type="button" className="sidebar-create"
      aria-label={t('新建项目')} title={t('新建项目')} onClick={() => { if (canLeave()) setCreating(true); closeMenu() }}>
      <WorkspaceIcon name="plus" /><span className="sidebar-text">{t('新建项目')}</span>
    </button>}
    navigation={closeMenu => <nav aria-label={t('主要导航')}>
      <button type="button" className="workspace-nav-item" aria-current={!route ? 'page' : undefined}
        aria-label={t('我的项目')} title={t('我的项目')} onClick={() => { navigate(null); closeMenu() }}>
        <WorkspaceIcon name="folder" /><span className="sidebar-text">{t('我的项目')}</span>
      </button>
      {project && <div className="sidebar-current">
        <p className="sidebar-label">{t('当前项目')}</p>
        <button type="button" className="workspace-nav-item current-project-name" aria-current="page"
          title={project.name} aria-label={t('当前项目 {name}', { name: project.name })}
          onClick={() => { chooseStep('details'); closeMenu() }}>
          <WorkspaceIcon name="file" /><span className="sidebar-text">{project.name}</span>
        </button>
      </div>}
    </nav>}>
    <div className={route ? 'customer-workspace' : 'customer-workspace project-list-panel'}>
      {!route && <>
        <div className="customer-section-heading">
          <h1 ref={projectListHeading} tabIndex={-1}>{t('我的项目')}</h1>
        </div>
        <ProjectList items={list.error ? [] : list.data?.items ?? []} total={list.data?.total ?? 0} pageSize={customerPageSize}
          query={query} searchDraft={search} loading={list.loading || (!list.data && !list.error)} error={list.error}
          onSearchDraftChange={setSearch} onQueryChange={setQuery} onOpen={openProject} onRetry={list.refresh}
          presentation="cards" typeLabels={customerProjectTypeNames}
          emptyMessage="还没有项目。新建一个项目，开始数据分析或论文写作。" onCreate={() => { if (canLeave()) setCreating(true) }} />
      </>}
      {route && projectUnavailable && <div className="customer-section">
        <p role="alert">{t('项目不存在或无权访问。')}</p>
        <button type="button" onClick={() => navigate(null)}>{t('返回我的项目')}</button>
      </div>}
      {route && !projectUnavailable && details.error && <div className="customer-section">
        <p role="alert">{t(details.error)}</p>
        <button type="button" onClick={details.refresh}>{t('重新读取项目')}</button>
      </div>}
      {route && !projectUnavailable && !details.error && !project && <div className="customer-section">
        <p role="status">{t('正在读取项目……')}</p>
      </div>}
      {route && project && <>
        <WorkspaceSteps current={projectSteps.findIndex(([key]) => key === activeStep)} steps={projectSteps.map(([key, title]) => ({
          title, action: () => chooseStep(key),
        }))} />
        <div key={project.id} className="customer-step-content">
          {activeStep === 'details' && <div className="customer-section customer-project-details project-details-card">
            <h1 ref={heading} tabIndex={-1} className="visually-hidden">{t('项目资料')}</h1>
            <div className="customer-project-details-fields">
              {landing?.failed && landing.projectId === project.id && <div className="customer-landing-error">
                <p role="alert" className="error-panel">{t('暂时无法读取项目进度。')}</p>
                <button type="button" onClick={retryLanding}>{t('重新读取')}</button>
              </div>}
              <ProjectDetails project={project} showHeading={false} showLanguage={!isThesis} onUpdated={details.refresh} registerLeaveGuard={registerLeaveGuard} />
              {isThesis && hasAnalysisHistory && <button type="button" className="button-quiet" onClick={() => chooseStep('deliveries')}>{t('历史分析交付')}</button>}
              {project.project_type === 'sci' && <CustomerSciSettings projectId={project.id} registerLeaveGuard={registerLeaveGuard}
                onContinue={() => chooseStep('materials', true)} />}
              {isThesis && <CustomerThesisRequirements projectId={project.id}
                onContinue={() => chooseStep('materials', true)} onLanguageChanged={details.refresh} registerLeaveGuard={registerLeaveGuard} />}
            </div>
            <footer className="customer-step-actions">
              <button type="button" className="button-primary" onClick={() => chooseStep(isAnalysis ? 'upload' : 'materials')}>{t('下一步 上传资料')}</button>
            </footer>
          </div>}
          {isThesis && activeStep === 'school' && <section className="customer-section thesis-organizer">
            <div className="customer-section-heading">
              <h1 ref={heading} tabIndex={-1} className={schoolPanel ? undefined : 'visually-hidden'}>{t(schoolPanel ? '学校模板' : '模板与资料整理')}</h1>
              {schoolPanel && <button type="button" className="button-accent" onClick={() => chooseStep('school')}>{t('返回模板与资料整理')}</button>}
            </div>
            {schoolPanel ? (templateId && !validCustomerRouteId(templateId) ? <p role="alert">{t('指定学校模板版本不可用。')}</p>
              : <SchoolTemplates projectId={project.id} active customerView registerLeaveGuard={registerLeaveGuard}
                  navigation={{view:templateView ?? 'detail', templateId:templateId ?? ''}}
                  onNavigate={({view, templateId}) => updatePaperRoute({schoolView:view, view:undefined, template:templateId || undefined}, true)}
                  onAdopted={() => chooseStep('school', true)}/>) : <ModuleViews label={t('模板与资料整理')} lazy>
              <ModuleView id="template" title={t('学校模板')}>
                <ThesisTemplateOrganizer projectId={project.id} registerLeaveGuard={registerLeaveGuard}
                  figureConfigRevision={figureConfigRevision}
                  onOpenProject={() => chooseStep('details')}
                  onSectionsSaved={() => setChapterRevision(value => value + 1)}
                  onOpenTemplate={hasTemplate => updatePaperRoute({schoolView:hasTemplate ? 'list' : 'upload'})}/>
              </ModuleView>
              <ModuleView id="materials" title={t('资料整理')}>
                <ThesisMaterialOrganizer projectId={project.id} registerLeaveGuard={registerLeaveGuard} chapterRevision={chapterRevision}/>
              </ModuleView>
              <ModuleView id="figures" title={t('图件配置')}>
                <CustomerSciResources projectType="thesis" projectId={project.id} registerLeaveGuard={registerLeaveGuard}
                  chapterRevision={chapterRevision} onSaved={() => setFigureConfigRevision(value => value + 1)}
                  onFigures={() => chooseStep('thesis-figures')} />
              </ModuleView>
            </ModuleViews>}
            {!schoolPanel && <footer className="customer-step-actions">
              <button type="button" className="button-primary" onClick={() => chooseStep('manuscripts')}>{t('下一步 文献与初稿')}</button>
            </footer>}
          </section>}
          {activeStep === 'upload' && <CustomerMaterials key={supplementing ? 'supplement' : 'upload'} projectId={project.id} headingRef={heading}
            onContinue={() => chooseStep('requirements')} onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard}
            supplement={supplementing ? {
              returnTarget, onReturn: href => followReturn(href), onSubmitted: finishSupplement, onProgress: () => chooseStep('progress'),
            } : undefined} />}
          {activeStep === 'requirements' && <CustomerRequirements projectId={project.id} headingRef={heading}
            onSubmitted={() => chooseStep('progress', true)} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'progress' && <CustomerProgress projectId={project.id} headingRef={heading} onRequirements={() => chooseStep('requirements')}
            onUpload={openSupplement} onDeliveries={() => chooseStep('deliveries')} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'deliveries' && <CustomerDeliveries projectId={project.id} headingRef={heading} showHeading={!isAnalysis}
            initialSnapshotId={routeParams.get('snapshot') ?? undefined} initialDeliveryId={routeParams.get('delivery') ?? undefined}
            onSelectSnapshot={snapshot => updatePaperRoute({ snapshot: snapshot ?? undefined }, true)}
            registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'tasks' && isTaskId(routeParams.get('task')) && <CustomerLegacyTask project={project}
            taskId={routeParams.get('task')!} taskView={taskDetailViews.find(view => view === routeParams.get('view'))}
            onTaskViewChange={view => updatePaperRoute({ view })} returnTarget={returnTarget}
            onFollowReturn={href => followReturn(href, false, 'details')} onBack={() => chooseStep('details')}
            onOpenFiles={() => chooseStep(isAnalysis ? 'upload' : 'materials')}
            headingRef={heading} registerLeaveGuard={registerLeaveGuard} />}
          {isSci && activeStep === 'materials' && <CustomerMaterials key="sci-upload" projectId={project.id} forWriting="sci"
            headingRef={heading} onContinue={() => chooseStep('sci-figures')} onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} />}
          {(isSci && activeStep === 'sci-figures' || isThesis && activeStep === 'thesis-figures') &&
            <CustomerSciFigures projectType={isThesis ? 'thesis' : 'sci'} projectId={project.id} headingRef={heading}
              registerLeaveGuard={registerLeaveGuard} onContinue={() => chooseStep(isThesis ? 'school' : 'sci-template')} />}
          {isSci && activeStep === 'sci-template' && (sciResources
            ? <CustomerSciResources key={project.id} projectId={project.id} headingRef={heading} registerLeaveGuard={registerLeaveGuard}
                onTemplate={() => chooseStep('sci-template')} onFigures={() => chooseStep('sci-figures')}
                onContinue={() => chooseStep('manuscripts', true, 'select')} />
            : <CustomerSciTemplate key={project.id} projectId={project.id} language={project.default_output_language ?? 'zh-CN'}
                headingRef={heading} registerLeaveGuard={registerLeaveGuard} onDetails={() => chooseStep('details')}
                onContinue={() => chooseStep('sci-template', true, 'resources')} />)}
          {isThesis && activeStep === 'materials' && <CustomerWritingMaterials project={project} params={routeParams} headingRef={heading}
            onUpdateRoute={updatePaperRoute} onContinue={() => chooseStep('thesis-figures')}
            onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} onOpenAnalysisResults={openMaterialsAnalysisResults}
            materialsReturn={returnTarget} onFollowReturn={href => followReturn(href, false, 'materials')} />}
          {(isSci || isThesis) && activeStep === 'manuscripts' &&
            <CustomerSciWorkflow key={project.id} project={project} headingRef={heading} params={manuscriptParams} onUpdateRoute={updatePaperRoute}
              onDetails={() => chooseStep('details')} onMaterials={() => chooseStep('materials')} onOrganizer={() => chooseStep(isSci ? 'sci-template' : 'school')}
              onResources={isSci ? () => chooseStep('sci-template', false, 'resources') : undefined}
              openSearch={oldLiterature || requestedStep === 'citations'} />}
        </div>
      </>}
    </div>
    {creating && <CustomerProjectCreate onClose={() => setCreating(false)} onCreated={created => {
      setCreating(false)
      setQuery({ page: 1, q: '', type: '' })
      setSearch('')
      navigate({ projectId: created.id, step: created.project_type === 'sci' ? 'materials' : 'details' }, { confirmed: true })
    }} />}
  </WorkspaceFrame>
}
