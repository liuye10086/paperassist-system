import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { watchProjectAccess } from '../../shared/api/projectAccess'
import { useI18n } from '../../shared/i18n'
import ProjectDetails from '../projects/ProjectDetails'
import ProjectList, { type ProjectListQuery } from '../projects/ProjectList'
import { PROJECT_PAGE_SIZE, type Project, type ProjectPage } from '../projects/projectTypes'
import type { LeaveGuard, RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { WorkspaceFrame, WorkspaceIcon } from '../projects/WorkspaceShell'
import WorkspaceSteps from '../projects/WorkspaceSteps'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import CustomerDeliveries from './CustomerDeliveries'
import CustomerMaterials from './CustomerMaterials'
import CustomerProgress from './CustomerProgress'
import CustomerProjectCreate from './CustomerProjectCreate'
import CustomerRequirements from './CustomerRequirements'
import './customerWorkspace.css'

const steps = [
  ['details', '项目资料'],
  ['upload', '上传资料'],
  ['requirements', '选择需求'],
  ['progress', '任务进度'],
  ['deliveries', '查看交付'],
] as const
type Step = typeof steps[number][0]
type Route = { projectId: string; step: Step } | null
const navigationIndexKey = 'paperassistCustomerNavigationIndex'

function readRoute(): Route {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const projectId = params.get('customer-project')
  if (!projectId || !/^[A-Za-z0-9_-]{1,64}$/.test(projectId)) return null
  const step = steps.find(([key]) => key === params.get('step'))?.[0] ?? 'details'
  return { projectId, step }
}

function address(route: Route) {
  return route ? '#' + new URLSearchParams({ 'customer-project': route.projectId, step: route.step }).toString() : ''
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
  const heading = useRef<HTMLHeadingElement | null>(null)
  const guards = useRef(new Map<LeaveGuard, () => boolean>())
  const registerLeaveGuard = useCallback<RegisterLeaveGuard>((guard, isDirty = () => true) => {
    guards.current.set(guard, isDirty)
    return () => { guards.current.delete(guard) }
  }, [])
  // Form drafts are restored on re-entry. Browser File handles are local to the upload step.
  const canLeave = useCallback(() => [...guards.current.keys()].every(guard => guard(currentRoute.current?.step !== 'upload')), [])

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

  function navigate(next: Route, confirmed = false) {
    if (address(next) === address(currentRoute.current) || (!confirmed && !canLeave())) return
    currentRoute.current = next
    navigationIndex.current += 1
    window.history.pushState({ ...window.history.state, [navigationIndexKey]: navigationIndex.current }, '',
      window.location.pathname + window.location.search + address(next))
    setRoute(next)
  }

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
      if (!canLeave()) {
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
    heading.current?.focus({ preventScroll: true })
    if (window.scrollY > 0) window.scrollTo({ top: 0, behavior: 'instant' })
  }, [route, project?.id])

  function openProject(id: string) {
    if (unavailable === id) setUnavailable('')
    navigate({ projectId: id, step: 'details' })
  }

  function chooseStep(step: Step, confirmed = false) {
    if (project) navigate({ projectId: project.id, step }, confirmed)
  }

  return <WorkspaceFrame className="customer-workbench" homeLabel="返回我的项目" onHome={() => navigate(null)}
    sidebarAction={closeMenu => <button type="button" className="sidebar-create button-primary"
      aria-label={t('新建研究项目')} title={t('新建项目')} onClick={() => { if (canLeave()) setCreating(true); closeMenu() }}>
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
    <div className="customer-workspace">
      {!route && <>
        <header className="workspace-page-heading"><h1 ref={heading} tabIndex={-1}>{t('我的项目')}</h1></header>
        <ProjectList items={list.error ? [] : list.data?.items ?? []} total={list.data?.total ?? 0}
          query={query} searchDraft={search} loading={list.loading || (!list.data && !list.error)} error={list.error}
          onSearchDraftChange={setSearch} onQueryChange={setQuery} onOpen={openProject} onRetry={list.refresh} presentation="cards" />
      </>}
      {route && projectUnavailable && <div className="customer-section">
        <p role="alert">{t('项目不存在或无权访问。')}</p>
        <button type="button" onClick={() => navigate(null)}>{t('返回我的项目')}</button>
      </div>}
      {route && !projectUnavailable && details.error && <div className="customer-section">
        <p role="alert">{t(details.error)}</p>
        <button type="button" onClick={details.refresh}>{t('重新读取项目')}</button>
      </div>}
      {route && !projectUnavailable && !details.error && !project && <p role="status">{t('正在读取项目……')}</p>}
      {route && project && <>
        <WorkspaceSteps current={steps.findIndex(([key]) => key === route.step)} steps={steps.map(([key, title]) => ({
          title, action: () => chooseStep(key),
        }))} />
        <header className="workspace-page-heading"><h1 ref={heading} tabIndex={-1}>{project.name}</h1></header>
        <div key={project.id}>
          {route.step === 'details' && <div className="customer-section">
            <div className="customer-section-heading">
              <h2>{t('项目资料')}</h2>
              <button type="button" className="button-primary" onClick={() => chooseStep('upload')}>{t('下一步 上传资料')}</button>
            </div>
            <ProjectDetails project={project} showHeading={false} onUpdated={details.refresh} registerLeaveGuard={registerLeaveGuard} />
          </div>}
          {route.step === 'upload' && <CustomerMaterials projectId={project.id} onContinue={() => chooseStep('requirements')}
            onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} />}
          {route.step === 'requirements' && <CustomerRequirements projectId={project.id}
            onSubmitted={() => chooseStep('progress', true)} registerLeaveGuard={registerLeaveGuard} />}
          {route.step === 'progress' && <CustomerProgress projectId={project.id} onRequirements={() => chooseStep('requirements')}
            onUpload={() => chooseStep('upload')} onDeliveries={() => chooseStep('deliveries')} registerLeaveGuard={registerLeaveGuard} />}
          {route.step === 'deliveries' && <CustomerDeliveries projectId={project.id} registerLeaveGuard={registerLeaveGuard} />}
        </div>
      </>}
    </div>
    {creating && <CustomerProjectCreate onClose={() => setCreating(false)} onCreated={created => {
      setCreating(false)
      setQuery({ page: 1, q: '', type: '' })
      setSearch('')
      navigate({ projectId: created.id, step: 'details' }, true)
    }} />}
  </WorkspaceFrame>
}
