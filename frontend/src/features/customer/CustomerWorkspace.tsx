import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { watchProjectAccess } from '../../shared/api/projectAccess'
import { useI18n } from '../../shared/i18n'
import ProjectDetails from '../projects/ProjectDetails'
import ProjectList, { type ProjectListQuery } from '../projects/ProjectList'
import { customerProjectTypeNames, type Project, type ProjectPage } from '../projects/projectTypes'
import type { LeaveGuard, RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { WorkspaceFrame, WorkspaceIcon } from '../projects/WorkspaceShell'
import WorkspaceSteps from '../projects/WorkspaceSteps'
import { taskDetailViews } from '../projects/reviewViews'
import { isTaskId } from '../tasks/taskTypes'
import type { AnalysisPlace, ManuscriptPlace } from '../reviews/ReviewsWorkspace'
import type { ManuscriptInput } from '../reviews/continuationTypes'
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
import { readSummary, summaryRoute } from './customerWorkspaceApi'
import { buildReturn, carryReturnParams, readReturn } from './returnToken'
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
  // Summary landing for “打开项目” only (接口设计第一节 2); `failed` keeps the retry on project details.
  const [landing, setLanding] = useState<{ projectId: string; attempt: number; failed: boolean } | null>(null)
  const projectListHeading = useRef<HTMLHeadingElement | null>(null)
  const heading = useRef<HTMLHeadingElement | null>(null)
  const manuscriptReviewOrigin = useRef<string | null>(null)
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

  const params = new URLSearchParams({ page: String(query.page), page_size: String(customerPageSize) })
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
  const requestedStep = route?.step === 'upload' && (isSci || isThesis) ? 'materials' : route?.step
  const activeStep = requestedStep && allowedStep(requestedStep) ? requestedStep : 'details'
  const routeParams = route?.params ?? new URLSearchParams()
  const reviewNavigation = activeStep === 'reviews' ? readCustomerReviewNavigation(routeParams) : null
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
  }, [projectId, activeStep, project?.id, reviewNavigation?.view, reviewNavigation?.taskId, reviewNavigation?.analysisResults, supplementing])

  useLayoutEffect(() => {
    const previousOrigin = manuscriptReviewOrigin.current
    const params = route?.params
    const label = params?.get('returnLabel')
    manuscriptReviewOrigin.current = route?.step === 'manuscripts' && params &&
      (label === 'review-round' || label === 'review-item') ? readReturn(params, route.projectId)?.href ?? null : null
    if (route?.step !== 'reviews' || previousOrigin !== address(route)) return
    const pageHeading = heading.current
    const section = pageHeading?.closest('section')
    if (!pageHeading || !section || document.activeElement !== pageHeading) return

    // The fixed round is read asynchronously. Stop waiting as soon as the customer moves focus.
    const restore = () => {
      const target = section.querySelector<HTMLElement>('[data-review-return-focus]')
      if (target && document.activeElement === pageHeading) {
        observer.disconnect()
        target.focus()
      }
    }
    const observer = new MutationObserver(restore)
    const stop = () => observer.disconnect()
    pageHeading.addEventListener('blur', stop, { once: true })
    observer.observe(section, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-review-return-focus'] })
    restore()
    return () => { stop(); pageHeading.removeEventListener('blur', stop) }
  }, [route])

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

  // A review paragraph lacks a source (B03 task 7). The paragraph is written into the current address first, so
  // the token and Back both lead to it; leaving is still guarded by a running or unknown submission.
  function openWithReturn(kind: 'literature' | 'materials', place: Record<string, string>, location: { section: string; paragraph: number }) {
    const current = currentRoute.current
    if (!project || !current || current.projectId !== project.id) return
    const origin = new URLSearchParams(current.params)
    for (const [key, value] of Object.entries(place)) origin.set(key, value)
    const here = { ...current, params: origin }
    navigate(here, { confirmed: true, replace: true })
    navigate({ projectId: project.id, step: kind === 'literature' ? 'citations' : 'materials', params: new URLSearchParams({
      view: kind === 'literature' ? 'list' : 'files',
      ...buildReturn(new URLSearchParams(address(here).slice(1)), 'paragraph', {
        returnSection: location.section, returnParagraph: String(location.paragraph),
      }),
    }) })
  }
  // A thesis chapter lacks a school template (B04 task 8, wireframe 13b). As above, the chapter is written into the
  // current address first (`focus=chapters` without one), so the token and Back both lead to it.
  function openTemplateWithReturn(place: { chapter?: string; title: string }) {
    const current = currentRoute.current
    if (!project || !current || current.projectId !== project.id) return
    const origin = new URLSearchParams(current.params)
    origin.delete('chapter')
    origin.delete('focus')
    if (place.chapter) origin.set('chapter', place.chapter)
    else origin.set('focus', 'chapters')
    const here = { ...current, params: origin }
    navigate(here, { confirmed: true, replace: true })
    navigate({ projectId: project.id, step: 'school', params: new URLSearchParams(
      buildReturn(new URLSearchParams(address(here).slice(1)), 'chapter', { returnChapter: place.title })) })
  }
  // An opinion needs an analysis result (B05 task 5, wireframe 17). The opinion's supplement view is written into the
  // current address first, so the token and Back both lead to it. The paper project stays the workspace project.
  function openAnalysisResults(place: AnalysisPlace) {
    const current = currentRoute.current
    if (!project || !current || current.projectId !== project.id || current.step !== 'reviews') return
    const origin = carryReturnParams(current.params ?? new URLSearchParams(),
      customerReviewParams({ view: 'supplements', roundId: place.roundId, itemId: place.itemId }))
    const here = { ...current, params: origin }
    navigate(here, { confirmed: true, replace: true })
    navigate({ projectId: project.id, step: 'reviews', params: new URLSearchParams({
      view: 'analysis-results',
      ...buildReturn(new URLSearchParams(address(here).slice(1)), 'review-item', {
        returnRound: String(place.roundNumber), returnItem: String(place.itemNumber),
      }),
    }) })
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
  // A fixed manuscript opened from a review (B05 task 7): the token leads back to the opinion, or to the round when no
  // opinion is selected. Leaving the review step is still guarded by unsaved review work.
  function openReviewManuscript(manuscript: ManuscriptInput, place: ManuscriptPlace) {
    const current = currentRoute.current
    if (!project || !current || current.projectId !== project.id || current.step !== 'reviews') return
    const origin = new URLSearchParams(address(current).slice(1))
    navigate({ projectId: project.id, step: 'manuscripts', params: new URLSearchParams({
      manuscript: manuscript.id, revision: String(manuscript.revision), view: 'body',
      ...(place.itemNumber
        ? buildReturn(origin, 'review-item', { returnRound: String(place.roundNumber), returnItem: String(place.itemNumber) })
        : buildReturn(origin, 'review-round', { returnRound: String(place.roundNumber) })),
    }) })
  }
  function finishSupplement() {
    if (returnTarget) followReturn(returnTarget.href, true)
    else chooseStep('progress', true)
  }

  // Choosing a step leaves the target page, so it deliberately drops any return token.
  function chooseStep(step: Step, confirmed = false) {
    if (project && allowedStep(step)) {
      navigate({ projectId: project.id, step }, { confirmed })
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

  function openWordTask(task: string) {
    const current = currentRoute.current
    if (!current) return
    navigate({ projectId: current.projectId, step: 'tasks', params: new URLSearchParams({
      task, ...buildReturn(new URLSearchParams(address(current).slice(1)), 'word'),
    }) })
  }

  // The Word page of one fixed version (B03). Adopting has already saved the version, so it leaves without a prompt.
  function openWord(manuscriptId: string, revision: number, { adopted = false }: { adopted?: boolean } = {}) {
    if (!project) return
    navigate({ projectId: project.id, step: 'word', params: new URLSearchParams({
      manuscript: manuscriptId, revision: String(revision), view: 'exports', ...(adopted ? { adopted: '1' } : {}),
    }) }, { confirmed: adopted })
  }

  // The migration page of one version with the new template preselected (B04 task 9, D6). The template change has
  // already been saved, so it leaves without a prompt; any chapter return token is dropped.
  function openMigration(manuscriptId: string, revision: number, confirmationId: string) {
    if (!project) return
    navigate({ projectId: project.id, step: 'manuscripts', params: new URLSearchParams({
      manuscript: manuscriptId, revision: String(revision), view: 'school', target: confirmationId,
    }) }, { confirmed: true })
  }

  const updateReviewRoute = useCallback((update: (current: CustomerReviewNavigation) => CustomerReviewNavigation,
    options?: RouteOptions) => {
    const current = currentRoute.current
    if (current?.projectId !== projectId || current.step !== 'reviews') return
    const navigation = readCustomerReviewNavigation(current.params ?? new URLSearchParams())
    if (navigation) navigate({ ...current, params: carryReturnParams(current.params ?? new URLSearchParams(), customerReviewParams(update(navigation))) }, options)
  }, [projectId, navigate])

  function startReview(manuscriptId: string, revision: number) {
    if (project) navigate({ projectId, step: 'reviews', params: carryReturnParams(currentRoute.current?.params ?? new URLSearchParams(),
      customerReviewParams({ view: 'create', manuscriptId, revision })) })
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
            {landing?.failed && landing.projectId === project.id && <div className="customer-landing-error">
              <p role="alert" className="error-panel">{t('暂时无法读取项目进度。')}</p>
              <button type="button" onClick={retryLanding}>{t('重新读取')}</button>
            </div>}
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
            {project.project_type === 'sci' && <CustomerSciSettings projectId={project.id} registerLeaveGuard={registerLeaveGuard}
              onContinue={() => chooseStep('materials', true)} />}
            {isThesis && <CustomerThesisRequirements projectId={project.id} onOpenTemplate={() => chooseStep('school')}
              onContinue={adopted => chooseStep(adopted ? 'materials' : 'school', true)}
              onLanguageChanged={details.refresh} registerLeaveGuard={registerLeaveGuard} />}
          </div>}
          {activeStep === 'upload' && <CustomerMaterials key={supplementing ? 'supplement' : 'upload'} projectId={project.id} headingRef={heading}
            onContinue={() => chooseStep('requirements')} onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard}
            supplement={supplementing ? {
              returnTarget, onReturn: href => followReturn(href), onSubmitted: finishSupplement, onProgress: () => chooseStep('progress'),
            } : undefined} />}
          {activeStep === 'requirements' && <CustomerRequirements projectId={project.id} headingRef={heading}
            onSubmitted={() => chooseStep('progress', true)} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'progress' && <CustomerProgress projectId={project.id} headingRef={heading} onRequirements={() => chooseStep('requirements')}
            onUpload={openSupplement} onDeliveries={() => chooseStep('deliveries')} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'deliveries' && <CustomerDeliveries projectId={project.id} headingRef={heading}
            initialSnapshotId={routeParams.get('snapshot') ?? undefined} initialDeliveryId={routeParams.get('delivery') ?? undefined}
            onSelectSnapshot={snapshot => updatePaperRoute({ snapshot: snapshot ?? undefined }, true)}
            registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'tasks' && isTaskId(routeParams.get('task')) && <CustomerLegacyTask project={project}
            taskId={routeParams.get('task')!} taskView={taskDetailViews.find(view => view === routeParams.get('view'))}
            onTaskViewChange={view => updatePaperRoute({ view })} returnTarget={returnTarget}
            onFollowReturn={href => followReturn(href, false, 'details')} onBack={() => chooseStep('details')}
            onOpenFiles={() => chooseStep(isAnalysis ? 'upload' : 'materials')}
            headingRef={heading} registerLeaveGuard={registerLeaveGuard} />}
          {activeStep === 'reviews' && (project.project_type === 'sci' || project.project_type === 'thesis') && reviewNavigation &&
            <CustomerReviewWorkflow project={project} projectType={project.project_type} navigation={reviewNavigation} onNavigate={updateReviewRoute}
              headingRef={heading} registerLeaveGuard={registerLeaveGuard} returnTarget={returnTarget}
              onFollowReturn={href => followReturn(href, false, 'reviews')} onOpenAnalysisResults={openAnalysisResults}
              onOpenManuscript={openReviewManuscript} />}
          {isSci && (activeStep === 'materials' || activeStep === 'citations' || activeStep === 'manuscripts' || activeStep === 'journals' || activeStep === 'word') &&
            <CustomerSciWorkflow key={activeStep} project={project} step={activeStep} headingRef={heading}
              registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable} onNavigate={chooseStep}
              params={routeParams} onUpdateRoute={updatePaperRoute} onStartReview={startReview} onOpenWord={openWord}
              onOpenWordTask={openWordTask} onNeedSource={openWithReturn} onFollowReturn={href => followReturn(href, false, 'manuscripts')}
              onOpenAnalysisResults={openMaterialsAnalysisResults} />}
          {isThesis && (activeStep === 'school' || activeStep === 'materials' || activeStep === 'citations' || activeStep === 'manuscripts' || activeStep === 'word') &&
            <CustomerThesisWorkflow key={activeStep} project={project} step={activeStep} headingRef={heading}
              registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable} onNavigate={chooseStep}
              params={routeParams} onUpdateRoute={updatePaperRoute} onStartReview={startReview} onOpenWord={openWord}
              onOpenWordTask={openWordTask} onNeedSource={openWithReturn} onFollowReturn={(href, confirmed) => followReturn(href, !!confirmed, 'manuscripts')}
              onOpenTemplateWithReturn={openTemplateWithReturn} onOpenMigration={openMigration}
              onOpenAnalysisResults={openMaterialsAnalysisResults} />}
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
