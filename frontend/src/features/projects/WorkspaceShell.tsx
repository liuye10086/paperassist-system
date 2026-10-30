import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import './workspace.css'
import Brand from '../../shared/components/Brand'

export type WorkspaceView = 'home' | 'projects' | 'project'
export type ProjectSection = 'overview' | 'files' | 'analysis' | 'artifacts' | 'tasks' | 'literature' | 'manuscripts' | 'school-templates' | 'journals' | 'reviews'
const projectSections: { value: ProjectSection; label: string; icon: 'home' | 'folder' | 'chart' | 'files' }[] = [
  { value: 'overview', label: '项目概览', icon: 'home' }, { value: 'files', label: '项目文件', icon: 'folder' },
  { value: 'analysis', label: '数据分析', icon: 'chart' }, { value: 'artifacts', label: '图表与报告', icon: 'files' },
  { value: 'literature', label: '文献', icon: 'files' },
  { value: 'manuscripts', label: 'SCI 写作', icon: 'files' },
  { value: 'reviews', label: '意见修改', icon: 'files' },
  { value: 'journals', label: '期刊建议', icon: 'files' },
  { value: 'school-templates', label: '学校模板', icon: 'files' },
  { value: 'tasks', label: '项目任务', icon: 'files' },
]

export function WorkspaceIcon({ name }: { name: 'home' | 'folder' | 'plus' | 'arrow' | 'file' | 'menu' | 'chart' | 'files' | 'collapse' | 'expand' }) {
  const paths = {
    home: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    folder: <path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    file: <><path d="M14 3H5v18h14V8l-5-5ZM14 3v6h5M8 13h8M8 17h5" /></>,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    chart: <path d="M4 3v17h17M9 16v-5M14 16V6M19 16V9" />,
    files: <><rect x="8" y="3" width="12" height="15" rx="2" /><path d="M4 7v12a2 2 0 0 0 2 2h10M12 8h4M12 12h4" /></>,
    collapse: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16m7-12-4 4 4 4" /></>,
    expand: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16m4-12 4 4-4 4" /></>,
  }
  return <svg className="workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

type Props = {
  view: WorkspaceView
  onNavigate: (view: WorkspaceView) => void
  onCreate: () => void
  projectName?: string
  projectType?: 'sci' | 'thesis' | 'research'
  section?: ProjectSection
  onSectionChange?: (section: ProjectSection) => void
  onCurrentProject: () => void
  children: ReactNode
}

export default function WorkspaceShell({ view, onNavigate, onCreate, projectName, projectType, section, onSectionChange, onCurrentProject, children }: Props) {
  const { t } = useI18n()
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const sidebar = useRef<HTMLElement>(null)
  const groups: { id: string; label: string; icon: 'folder' | 'chart' | 'files'; items: ProjectSection[] }[] = [
    { id: 'materials', label: '材料准备', icon: 'folder', items: ['files', 'literature'] },
    { id: 'analysis', label: '分析与成果', icon: 'chart', items: ['analysis', 'artifacts'] },
    { id: 'writing', label: '稿件写作', icon: 'files', items: ['manuscripts', projectType === 'thesis' ? 'school-templates' : 'journals'] },
    { id: 'reviews', label: '评审与修改', icon: 'files', items: ['reviews', 'tasks'] },
  ]
  const activeGroup = view === 'project' ? groups.find(group => group.items.includes(section ?? 'overview'))?.id : undefined
  useEffect(() => {
    if (!menuOpen) return
    const previous = document.activeElement as HTMLElement | null
    const panel = sidebar.current
    panel?.querySelector<HTMLButtonElement>('.workspace-brand')?.focus()
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setMenuOpen(false); menuButton.current?.focus() }
      if (event.key === 'Tab') {
        const buttons = Array.from(panel?.querySelectorAll<HTMLButtonElement>('button') ?? []).filter(button => button.getClientRects().length > 0)
        const first = buttons[0], last = buttons[buttons.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => { document.removeEventListener('keydown', handleKey); if (panel?.contains(document.activeElement)) previous?.focus() }
  }, [menuOpen])
  const chooseSection = (next: ProjectSection) => { setMenuOpen(false); onSectionChange?.(next) }
  const sectionLabel = (item: typeof projectSections[number]) => t(item.value === 'manuscripts' && projectType === 'thesis' ? '毕业论文写作' : item.label)
  const sectionButton = (value: ProjectSection) => {
    const item = projectSections.find(item => item.value === value)!
    return <button key={value} type="button" className="workspace-nav-item" aria-label={sectionLabel(item)} title={sectionLabel(item)}
      aria-current={view === 'project' && section === value ? 'page' : undefined} onClick={() => chooseSection(value)}>
      <WorkspaceIcon name={item.icon} /><span className="sidebar-text">{sectionLabel(item)}</span></button>
  }
  const navigate = (next: WorkspaceView) => { onNavigate(next); setMenuOpen(false) }
  return <div className={`workbench-shell${collapsed ? ' is-collapsed' : ''}`}>
    <button ref={menuButton} type="button" className="workspace-mobile-menu button-quiet" aria-expanded={menuOpen} aria-controls="workspace-sidebar"
      onClick={() => setMenuOpen(value => !value)}><WorkspaceIcon name="menu" />{t('导航')}</button>
    {menuOpen && <button className="workspace-nav-backdrop" aria-label={t('关闭导航')} onClick={() => { setMenuOpen(false); menuButton.current?.focus() }} />}
    <aside ref={sidebar} role={menuOpen ? 'dialog' : undefined} aria-modal={menuOpen ? true : undefined} aria-label={t('主要导航')} className={`workspace-sidebar${menuOpen ? ' is-open' : ''}`} id="workspace-sidebar">
      <button type="button" className="sidebar-toggle button-quiet" aria-expanded={!collapsed} aria-controls="workspace-sidebar"
        aria-label={t(collapsed ? '展开侧边栏' : '收起侧边栏')} title={t(collapsed ? '展开侧边栏' : '收起侧边栏')}
        onClick={() => setCollapsed(value => !value)}><WorkspaceIcon name={collapsed ? 'expand' : 'collapse'} /></button>
      <button type="button" className="workspace-brand" aria-label={t('返回工作台')} onClick={() => navigate('home')}>
        <Brand />
        <span className="sidebar-text"><strong>PaperAssist</strong><small>{t('让研究有条不紊')}</small></span>
      </button>
      <button type="button" className="sidebar-create button-primary" aria-label={t('新建研究项目')} title={t('新建项目')}
        onClick={() => { setMenuOpen(false); onCreate() }}><WorkspaceIcon name="plus" /><span className="sidebar-text">{t('新建项目')}</span></button>
      <p className="sidebar-label">{t('工作空间')}</p>
      <nav aria-label={t('主要导航')}>
        <button type="button" className="workspace-nav-item" aria-current={view === 'home' ? 'page' : undefined}
          aria-label={t('工作台')} title={t('工作台')} onClick={() => navigate('home')}><WorkspaceIcon name="home" /><span className="sidebar-text">{t('工作台')}</span></button>
        <button type="button" className="workspace-nav-item" aria-current={view === 'projects' ? 'page' : undefined}
          aria-label={t('我的项目')} title={t('我的项目')} onClick={() => navigate('projects')}><WorkspaceIcon name="folder" /><span className="sidebar-text">{t('我的项目')}</span></button>
      </nav>
      {projectName && <div className="sidebar-current"><p className="sidebar-label">{t('当前项目')}</p>
        <button type="button" className="workspace-nav-item current-project-name" aria-label={projectName} title={projectName}
          onClick={() => { setMenuOpen(false); onCurrentProject() }}>
          <WorkspaceIcon name="file" /><span className="sidebar-text">{projectName}</span>
        </button>
        <nav className="project-section-nav" aria-label={t('项目导航')}>
          {sectionButton('overview')}
          {groups.filter(group => projectType !== 'research' || group.id !== 'writing').map(group => <div className={`workspace-nav-group${activeGroup === group.id ? ' is-current' : ''}`} key={group.id}>
            <button type="button" className="workspace-nav-item workspace-group-toggle" aria-label={t(group.label)} title={t(group.label)}
              aria-expanded={activeGroup === group.id} aria-controls={`workspace-group-${group.id}`} onClick={() => chooseSection(group.items[0])}>
              <WorkspaceIcon name={group.icon} /><span className="sidebar-text">{t(group.label)}</span><span className="group-chevron sidebar-text" aria-hidden="true">›</span>
            </button>
            <div className="workspace-group-children" id={`workspace-group-${group.id}`} hidden={activeGroup !== group.id}>{group.items.filter(item => projectType !== 'research' || item !== 'reviews').map(sectionButton)}</div>
          </div>)}
        </nav>
      </div>}
      <div className="sidebar-note"><WorkspaceIcon name="file" /><strong>{t('从一份数据开始')}</strong>
        <p>{t('在项目中整理文件，让分析与成果始终有据可循。')}</p></div>
      <p className="sidebar-footer">{t('科研论文辅助系统')}</p>
    </aside>
    <main className="workbench-content" tabIndex={-1}>
      <nav className="workspace-breadcrumbs" aria-label={t('面包屑导航')}><button type="button" aria-label={t('面包屑：工作台')} onClick={() => navigate('home')}>{t('工作台')}</button>
        {view !== 'home' && <><span aria-hidden="true">/</span><button type="button" aria-label={t('面包屑：我的项目')} onClick={() => navigate('projects')}>{t('我的项目')}</button></>}
        {view === 'project' && <><span aria-hidden="true">/</span><button type="button" aria-label={t('面包屑：当前项目')} onClick={onCurrentProject}>{projectName}</button><span aria-hidden="true">/</span><span aria-current="page">{sectionLabel(projectSections.find(item => item.value === (section ?? 'overview'))!)}</span></>}
      </nav>{children}<footer className="workspace-footer"><span>PaperAssist</span><span>{t('以清晰的过程，支持严谨的研究。')}</span></footer></main>
  </div>
}
