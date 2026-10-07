import { apiFetch } from '../../shared/api/client'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import ProjectDetails from './ProjectDetails'
import ProjectResources from './ProjectResources'
import './projectContent.css'
import ProjectSummary from './ProjectSummary'
import ProjectList, { type ProjectListQuery } from './ProjectList'
import WorkspaceShell, { WorkspaceIcon, type WorkspaceView, type ProjectSection } from './WorkspaceShell'
import ProjectCreateDialog from './ProjectCreateDialog'
import useProjectSelection from './useProjectSelection'
import { PROJECT_PAGE_SIZE, isProject, type Project, type ProjectPage } from './projectTypes'
import { apiError, safeError, useI18n } from '../../shared/i18n'
async function responseData(response: Response, fallback: string) {
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(apiError(data, fallback))
  return data
}

export default function ProjectWorkspace() {
  const { t, locale } = useI18n()
  const [view, setView] = useState<WorkspaceView>(() => new URLSearchParams(window.location.hash.slice(1)).has('project') ? 'project' : 'home')
  const [section, setSection] = useState<ProjectSection>('overview')
  const [navigationSequence, setNavigationSequence] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState<ProjectListQuery>({ page: 1, q: '', type: '' })
  const [searchDraft, setSearchDraft] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [createError, setCreateError] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [topic, setTopic] = useState('')
  const [projectType, setProjectType] = useState<'' | 'sci' | 'thesis'>('')
  const createController = useRef<AbortController | null>(null)
  const listRequest = useRef<{ controller: AbortController; timeout: number } | null>(null)
  const listSequence = useRef(0)
  const unavailableIds = useRef(new Set<string>())
  const selectedRegion = useRef<HTMLElement | null>(null)
  const listRegion = useRef<HTMLElement | null>(null)
  const workspaceRegion = useRef<HTMLDivElement | null>(null)
  const selection = useProjectSelection(id => {
    unavailableIds.current.add(id)
    setProjects(previous => previous.filter(item => item.id !== id))
    refresh()
  }, id => {
    if (unavailableIds.current.delete(id)) refresh()
  })
  const project = selection.project

  const selectedKey = selection.instance?.key
  useLayoutEffect(() => {
    const target = view === 'project' ? selectedRegion.current : listRegion.current
    target?.focus({ preventScroll: true })
    if (window.scrollY > 0) window.scrollTo({ top: 0, behavior: 'instant' })
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const animation = workspaceRegion.current?.animate?.([
      { opacity: 0.45, transform: 'translateY(6px)' },
      { opacity: 1, transform: 'translateY(0)' },
    ], { duration: 180, easing: 'cubic-bezier(.2,.7,.2,1)' })
    return () => animation?.cancel()
  }, [selectedKey, view, section, navigationSequence])

  function navigate(next: WorkspaceView) {
    setView(next)
    setNavigationSequence(value => value + 1)
  }

  function openProject(id: string) {
    navigate('project')
    setSection('overview')
    selection.open(id)
  }

  function changeSection(next: ProjectSection) {
    setSection(next)
    navigate('project')
  }

  function closeProject() {
    selection.close()
    navigate('projects')
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
    const controller = new AbortController()
    let active = true
    const sequence = ++listSequence.current
    const timeout = window.setTimeout(() => {
      if (!active || sequence !== listSequence.current) return
      controller.abort()
      listSequence.current++
      setLoadError('项目列表读取超时，请稍后重试。')
      setLoading(false)
    }, 15_000)
    listRequest.current = { controller, timeout }
    async function load() {
      try {
        const parameters = new URLSearchParams({ page: String(query.page), page_size: String(PROJECT_PAGE_SIZE) })
        if (query.q) parameters.set('q', query.q)
        if (query.type) parameters.set('type', query.type)
        const response = await apiFetch(`/api/v1/projects?${parameters}`, { signal: controller.signal })
        const result = await responseData(response, '项目列表读取失败。')
        if (!active || sequence !== listSequence.current || controller.signal.aborted) return
        if (!result || !Array.isArray(result.items) || !result.items.every(isProject)
          || !Number.isSafeInteger(result.total) || result.total < 0 || result.page !== query.page || result.page_size !== PROJECT_PAGE_SIZE) {
          throw new Error('项目列表格式不正确。')
        }
        const data: ProjectPage = result
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
  }, [query, attempt])

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
    if (!projectType) { setCreateError('请选择项目类型。'); return }
    const controller = new AbortController()
    createController.current = controller
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 15_000)
    setCreating(true)
    setCreateError('')
    try {
      const response = await apiFetch('/api/v1/projects', { method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), research_topic: topic.trim(), project_type: projectType }),
      })
      const created: Project = await responseData(response, '创建项目失败，请检查输入后重试。')
      if (!controller.signal.aborted) {
        if (!isProject(created)) throw new Error('项目响应格式不正确，请刷新项目列表。')
        setProjects([created])
        selection.open(created.id, created)
        setView('project')
        setSection('overview')
        setSearchDraft('')
        changeQuery({ ...query, page: 1, q: '', type: '' })
        setName('')
        setTopic('')
        setProjectType('')
        setShowCreate(false)
      }
    } catch (cause) {
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

  return <WorkspaceShell view={view} onNavigate={navigate} onCreate={() => setShowCreate(true)} projectName={project?.name}
    section={section} onSectionChange={changeSection} onCurrentProject={() => navigate('project')}>
    <div ref={workspaceRegion} className="project-workspace">
    <section ref={listRegion} tabIndex={-1} hidden={view === 'project'} aria-labelledby="projects-title">
    <div className="workspace-page-heading"><div><span className="workspace-eyebrow">{t(view === 'home' ? '你的科研工作空间' : '我的项目')}</span>
      <h1 id="projects-title">{t("项目中心")}</h1><p>{t(view === 'home' ? '把研究资料、分析过程和成果，放在同一个地方。' : '通过名称和类型，找到你需要的研究。')}</p></div>
      <button type="button" className="button-primary" aria-label={t('开始一项新研究')} onClick={() => setShowCreate(true)}><WorkspaceIcon name="plus" />{t('新建项目')}</button>
    </div>
    {recentProject && <section className="continue-research" aria-label={t('最近更新的研究')}>
      <div className="continue-research-icon" aria-hidden="true"><WorkspaceIcon name="file" /></div>
      <div className="continue-research-copy"><span className="workspace-eyebrow">{t('最近更新的研究')}</span><h2>{recentProject.name}</h2>
        <p>{recentProject.research_topic}</p><span className="muted">{t('最近更新 {date}', { date: new Date(recentProject.updated_at).toLocaleDateString(locale) })}</span></div>
      <button type="button" onClick={() => openProject(recentProject.id)}>{t('继续研究')}<WorkspaceIcon name="arrow" /></button>
    </section>}
    <div className="workspace-list-heading"><h2>{t('项目记录')}</h2><p>{t('按项目保存研究资料，继续查看已上传的数据。')}</p></div>
    <ProjectList items={projects} total={total} query={query} searchDraft={searchDraft} loading={loading} error={loadError}
      onSearchDraftChange={setSearchDraft} onQueryChange={changeQuery} onOpen={openProject} onRetry={refresh}
      onCreate={() => setShowCreate(true)} />
    </section>
    {showCreate && <ProjectCreateDialog busy={creating} onClose={() => setShowCreate(false)}>
    <form className="project-form" onSubmit={create} aria-busy={creating}>
      <div className="project-fields">
        <label>{t("项目名称")}<input value={name} onChange={event => setName(event.target.value)} required maxLength={120} disabled={creating} /></label>
        <label>{t("项目类型")}<select value={projectType} onChange={event => setProjectType(event.target.value as '' | 'sci' | 'thesis')} required disabled={creating}>
          <option value="">{t("请选择项目类型")}</option><option value="sci">{t("SCI 科研论文")}</option><option value="thesis">{t("毕业论文")}</option>
        </select></label>
      </div>
      <label>{t("研究主题")}<textarea value={topic} onChange={event => setTopic(event.target.value)} required maxLength={500} rows={2} disabled={creating} /></label>
      {createError && <p className="error-panel" role="alert">{t(createError)}</p>}
      <div className="project-form-actions"><button type="submit" className="button-primary" disabled={creating}>{creating ? t("正在创建……") : t("创建项目")}</button>
        <button type="button" disabled={creating} onClick={() => setShowCreate(false)}>{t('取消创建')}</button></div>
    </form>
    </ProjectCreateDialog>}

    {selection.unavailableId && <div className="error-panel" role="alert">{t("项目不存在或无权访问。")}{' '}
      <button type="button" className="project-back button-quiet" onClick={closeProject}>← {t("返回项目列表")}</button>{' '}
      <button type="button" onClick={() => openProject(selection.unavailableId)}>{t("重试打开项目")}</button>
    </div>}
    {selection.instance && <section ref={selectedRegion} hidden={view !== 'project'} tabIndex={-1} className="selected-project" aria-label={t("当前项目工作区")}>
      <button type="button" className="project-back button-quiet" onClick={closeProject}>← {t("返回项目列表")}</button>
      {selection.loading && <p role="status">{t("正在读取项目详情……")}</p>}
      {selection.error && <div className="error-panel" role="alert">{t(selection.error)}{' '}
        <button type="button" onClick={selection.refresh}>{t("重试项目详情")}</button>
      </div>}
      {project && <div key={selection.instance.key}>
        <header className="project-page-heading"><span className="workspace-eyebrow">{t('当前研究')}</span>
          <h1>{project.name}</h1><p>{project.research_topic}</p>
        </header>
        <div hidden={section !== 'overview'}>
          <div className="project-overview-heading"><h2>{t('项目概览')}</h2><span className="muted">{t('最近更新 {date}', { date: new Date(project.updated_at).toLocaleDateString(locale) })}</span></div>
          <ProjectDetails project={project} onUpdated={updated} showHeading={false} />
          <div className="project-shortcuts">
            <button type="button" onClick={() => changeSection('files')}><WorkspaceIcon name="file" /><span><strong>{t('整理研究资料')}</strong><small>{t('查看文件与上传数据')}</small></span><WorkspaceIcon name="arrow" /></button>
            <button type="button" onClick={() => changeSection('analysis')}><WorkspaceIcon name="folder" /><span><strong>{t('继续数据分析')}</strong><small>{t('配置字段，探索数据与结果')}</small></span><WorkspaceIcon name="arrow" /></button>
          </div>
        </div>
        <div hidden={section !== 'overview' && section !== 'artifacts'}>
          <ProjectSummary projectId={project.id} projectType={project.project_type} view={section === 'artifacts' ? 'artifacts' : 'overview'}
            active={view === 'project' && (section === 'overview' || section === 'artifacts')} />
        </div>
        <ProjectResources projectId={project.id} section={section} onSectionChange={changeSection} onSaved={() => { refresh(); selection.refresh() }} />
      </div>}
    </section>}
  </div>
  </WorkspaceShell>
}
