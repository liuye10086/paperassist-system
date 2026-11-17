import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { watchProjectAccess } from '../../shared/api/projectAccess'
import { useI18n } from '../../shared/i18n'
import ProjectDetails from '../projects/ProjectDetails'
import ProjectList, { type ProjectListQuery } from '../projects/ProjectList'
import { customerProjectTypeNames, PROJECT_PAGE_SIZE, type Project, type ProjectPage } from '../projects/projectTypes'
import type { LeaveGuard, RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { WorkspaceFrame, WorkspaceIcon } from '../projects/WorkspaceShell'
import WorkspaceSteps from '../projects/WorkspaceSteps'
import { taskDetailViews } from '../projects/reviewViews'
import { isTaskId } from '../tasks/taskTypes'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import CustomerDeliveries from './CustomerDeliveries'
import CustomerLegacyTask from './CustomerLegacyTask'
import CustomerMaterials from './CustomerMaterials'
import CustomerProgress from './CustomerProgress'
import CustomerProjectCreate from './CustomerProjectCreate'
import CustomerReviewWorkflow from './CustomerReviewWorkflow'
import CustomerRequirements from './CustomerRequirements'
import CustomerSciSettings from './CustomerSciSettings'
import CustomerSciWorkflow from './CustomerSciWorkflow'
import CustomerThesisRequirements from './CustomerThesisRequirements'
import CustomerThesisWorkflow from './CustomerThesisWorkflow'
import { readLegacyCustomerRoute } from './customerLegacyNavigation'
import { customerReviewParams, readCustomerReviewNavigation, validCustomerRouteId, type CustomerReviewNavigation } from './customerReviewNavigation'
import './customerWorkspace.css'

const steps = [
  ['details', '项目资料'],
  ['upload', '上传资料'],
  ['requirements', '选择需求'],
  ['progress', '任务进度'],
  ['deliveries', '查看交付'],
] as const
const sciSteps = [
  ['details', '项目资料'],
  ['materials', '写作资料与引用'],
  ['manuscripts', '稿件与复核'],
  ['journals', '期刊适配与 Word'],
  ['reviews', '意见与返修'],
] as const
const thesisSteps = [
  ['details', '项目资料'],
  ['school', '学校模板'],
  ['materials', '写作资料与引用'],
  ['manuscripts', '章节与复核'],
  ['word', '固定版本与 Word'],
  ['reviews', '意见与返修'],
] as const
type SciStep = typeof sciSteps[number][0]
type ThesisStep = typeof thesisSteps[number][0]
type Step = typeof steps[number][0] | SciStep | ThesisStep | 'citations' | 'tasks'
type Route = { projectId: string; step: Step; params?: URLSearchParams } | null
type RouteOptions = { confirmed?: boolean; replace?: boolean }
const allowedSteps = new Set<string>([...steps, ...sciSteps, ...thesisSteps].map(([key]) => key))
allowedSteps.add('citations').add('tasks')
const navigationIndexKey = 'paperassistCustomerNavigationIndex'

function readRoute(): Route {
  const hash = window.location.hash
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
  const projectList = useRef<HTMLElement | null>(null)
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
    const preserveDraft = !!samePage ||
      !['upload', 'school', 'materials', 'citations', 'manuscripts', 'journals', 'word', 'reviews', 'tasks'].includes(current?.step ?? '')
    return [...guards.current.keys()].every(guard => guard(preserveDraft))
  }, [])

  const projectId = route?.projectId ?? ''
  const projectUnavailable = !!projectId && unavailable === projectId
  const onUnavailable = useCallback(() => setUnavailable(projectId), [projectId])
  useLayoutEffect(() => projectId ? watchProjectAccess(projectId, onUnavailable) : undefined, [projectId, onUnavailable])

  const params = new URLSearchParams({ page: String(query.page), page_size: String(PROJECT_PAGE_SIZE) })
  if (query.q) params.set('q', query.q)
  if (query.type) params.set('type', query.type)
  const list = useResearchRead<ProjectPage>(`/api/v1/projects?${params}`, !route)
  const details = useResearchRead<Project>(projectId ? projectBase(projectId) : '', !!projectId && !projectUnavailable)
  const project = !details.error && !projectUnavailable && details.data?.id === projectId ? details.data : null
  const isAnalysis = project?.project_type === 'research'
  const isSci = project?.project_type === 'sci'
  const isThesis = project?.project_type === 'thesis'
  const hasAnalysisHistory = project?.has_analysis_history === true
  const allowedStep = (step: Step) => step === 'details' || step === 'tasks' || step === 'deliveries' && hasAnalysisHistory ||
    (isAnalysis && steps.some(([key]) => key === step)) ||
    (isSci && (sciSteps.some(([key]) => key === step) || step === 'word' || step === 'citations')) ||
    (isThesis && (thesisSteps.some(([key]) => key === step) || step === 'citations'))
  const activeStep = route && allowedStep(route.step) ? route.step : 'details'
  const routeParams = route?.params ?? new URLSearchParams()
  const reviewNavigation = activeStep === 'reviews' ? readCustomerReviewNavigation(routeParams) : null

  const navigate = useCallback((next: Route, { confirmed = false, replace = false }: RouteOptions = {}) => {
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
    const target = projectId ? heading.current : projectList.current
    target?.focus({ preventScroll: true })
    if (window.scrollY > 0) window.scrollTo({ top: 0, behavior: 'instant' })
  }, [projectId, activeStep, project?.id, reviewNavigation?.view, reviewNavigation?.taskId])

  function openProject(id: string) {
    if (unavailable === id) setUnavailable('')
    navigate({ projectId: id, step: 'details' })
  }

  function chooseStep(step: Step, confirmed = false) {
    if (project && allowedStep(step)) {
      navigate({ projectId: project.id, step }, { confirmed })
    }
  }

  function updatePaperRoute(patch: Record<string, string | number | undefined>, confirmed = false) {
    const current = currentRoute.current
    if (!current || current.projectId !== projectId) return
    const next = new URLSearchParams(current.params)
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, String(value))
      else next.delete(key)
    }
    navigate({ ...current, params: next }, { confirmed })
  }

  const updateReviewRoute = useCallback((update: (current: CustomerReviewNavigation) => CustomerReviewNavigation,
    options?: RouteOptions) => {
    const current = currentRoute.current
    if (current?.projectId !== projectId || current.step !== 'reviews') return
    const navigation = readCustomerReviewNavigation(current.params ?? new URLSearchParams())
    if (navigation) navigate({ ...current, params: customerReviewParams(update(navigation)) }, options)
  }, [projectId, navigate])

  function startReview(manuscriptId: string, revision: number) {
    if (project) navigate({ projectId, step: 'reviews', params: customerReviewParams({ view: 'create', manuscriptId, revision }) })
  }

  return <WorkspaceFrame className="customer-workbench" homeLabel="返回我的项目" onHome={() => navigate(null)}
    location="我的项目" projectName={project?.name}
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
      {!route && <ProjectList ref={projectList} items={list.error ? [] : list.data?.items ?? []} total={list.data?.total ?? 0}
        query={query} searchDraft={search} loading={list.loading || (!list.data && !list.error)} error={list.error}
        onSearchDraftChange={setSearch} onQueryChange={setQuery} onOpen={openProject} onRetry={list.refresh}
        presentation="cards" typeLabels={customerProjectTypeNames} />}
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
        {isAnalysis && <WorkspaceSteps current={steps.findIndex(([key]) => key === activeStep)} steps={steps.map(([key, title]) => ({
          title, action: () => chooseStep(key),
        }))} />}
        {(isSci || isThesis) && <nav className="customer-switches customer-manuscript-navigation" aria-label={t(isThesis ? '毕业论文项目步骤' : 'SCI 项目步骤')}>
          {(isThesis ? thesisSteps : sciSteps).map(([key, title]) => <button key={key} type="button" className="button-quiet"
            aria-current={activeStep === key || key === 'journals' && activeStep === 'word' ||
              key === 'materials' && activeStep === 'citations' ? 'step' : undefined}
            onClick={() => chooseStep(key)}>{t(title)}</button>)}
        </nav>}
        <div key={project.id} className="customer-step-content">
          {activeStep === 'details' && <div className="customer-section customer-project-details project-details-card">
            <div className="customer-section-heading">
              <h1 ref={heading} tabIndex={-1}>{t('项目资料')}</h1>
              {isAnalysis
                ? <button type="button" className="button-primary" onClick={() => chooseStep('upload')}>{t('下一步 上传资料')}</button>
                : <div className="sci-inline-controls">
                  <span className="project-type-badge">{t(customerProjectTypeNames[project.project_type])}</span>
                  {hasAnalysisHistory && <button type="button" className="button-quiet" onClick={() => chooseStep('deliveries')}>
                    {t('历史分析交付')}
                  </button>}
                </div>}
            </div>
            <ProjectDetails project={project} showHeading={false} showLanguage={!isThesis} onUpdated={details.refresh} registerLeaveGuard={registerLeaveGuard} />
            {project.project_type === 'sci' && <CustomerSciSettings projectId={project.id} registerLeaveGuard={registerLeaveGuard} />}
            {isThesis && <CustomerThesisRequirements projectId={project.id} onOpenTemplate={() => chooseStep('school')}
              onLanguageChanged={details.refresh} registerLeaveGuard={registerLeaveGuard} />}
          </div>}
          {activeStep === 'upload' && <CustomerMaterials projectId={project.id} headingRef={heading} onContinue={() => chooseStep('requirements')}
            onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'requirements' && <CustomerRequirements projectId={project.id} headingRef={heading}
            onSubmitted={() => chooseStep('progress', true)} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'progress' && <CustomerProgress projectId={project.id} headingRef={heading} onRequirements={() => chooseStep('requirements')}
            onUpload={() => chooseStep('upload')} onDeliveries={() => chooseStep('deliveries')} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'deliveries' && <CustomerDeliveries projectId={project.id} headingRef={heading}
            initialSnapshotId={routeParams.get('snapshot') ?? undefined} initialDeliveryId={routeParams.get('delivery') ?? undefined}
            onSelectSnapshot={snapshot => updatePaperRoute({ snapshot: snapshot ?? undefined }, true)}
            registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'tasks' && isTaskId(routeParams.get('task')) && <CustomerLegacyTask project={project}
            taskId={routeParams.get('task')!} taskView={taskDetailViews.find(view => view === routeParams.get('view'))}
            onTaskViewChange={view => updatePaperRoute({ view })}
            headingRef={heading} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'reviews' && (project.project_type === 'sci' || project.project_type === 'thesis') && reviewNavigation &&
            <CustomerReviewWorkflow project={project} projectType={project.project_type} navigation={reviewNavigation} onNavigate={updateReviewRoute}
              headingRef={heading} registerLeaveGuard={registerLeaveGuard} onOpenAnalysisDeliveries={() => navigate(null)} />}
          {isSci && (activeStep === 'materials' || activeStep === 'citations' || activeStep === 'manuscripts' || activeStep === 'journals' || activeStep === 'word') &&
            <CustomerSciWorkflow key={activeStep} project={project} step={activeStep} headingRef={heading}
              registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable} onNavigate={chooseStep}
              params={routeParams} onUpdateRoute={updatePaperRoute} onStartReview={startReview} />}
          {isThesis && (activeStep === 'school' || activeStep === 'materials' || activeStep === 'citations' || activeStep === 'manuscripts' || activeStep === 'word') &&
            <CustomerThesisWorkflow key={activeStep} project={project} step={activeStep} headingRef={heading}
              registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable} onNavigate={chooseStep}
              params={routeParams} onUpdateRoute={updatePaperRoute} onStartReview={startReview} />}
        </div>
      </>}
    </div>
    {creating && <CustomerProjectCreate onClose={() => setCreating(false)} onCreated={created => {
      setCreating(false)
      setQuery({ page: 1, q: '', type: '' })
      setSearch('')
      navigate({ projectId: created.id, step: 'details' }, { confirmed: true })
    }} />}
  </WorkspaceFrame>
}
