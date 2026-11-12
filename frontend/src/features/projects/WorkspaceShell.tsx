import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import './workspace.css'
import Brand from '../../shared/components/Brand'
import type { OverviewView } from './projectNavigation'

export type WorkspaceView = 'home' | 'projects' | 'assigned' | 'project'
export type ProjectSection = 'overview' | 'files' | 'analysis' | 'artifacts' | 'tasks' | 'literature' | 'manuscripts' | 'school-templates' | 'journals' | 'reviews'
const projectSections: { value: ProjectSection; label: string; icon: 'home' | 'folder' | 'chart' | 'files' }[] = [
  { value: 'files', label: '项目文件', icon: 'folder' },
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
  analysisOnly?: boolean
  overviewView?: OverviewView
  onOverviewChange?: (view: OverviewView) => void
  onSectionChange?: (section: ProjectSection) => void
  onCurrentProject: () => void
  sectionBlocked?: (section: ProjectSection) => string
  hasAnalysis?: boolean
  children: ReactNode
}

export function WorkspaceFrame({ className, homeLabel = '返回工作台', onHome, sidebarAction, navigation, children }: {
  className?: string
  homeLabel?: string
  onHome: () => void
  sidebarAction?: (closeMenu: () => void) => ReactNode
  navigation: (closeMenu: () => void) => ReactNode
  children: ReactNode
}) {
  const { t } = useI18n()
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const sidebarId = useId()
  const menuButton = useRef<HTMLButtonElement>(null)
  const sidebar = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!menuOpen) return
    const previous = document.activeElement as HTMLElement | null
    const panel = sidebar.current
    const desktop = window.matchMedia?.('(min-width: 761px)')
    const closeOnDesktop = (event: MediaQueryListEvent) => { if (event.matches) setMenuOpen(false) }
    panel?.querySelector<HTMLButtonElement>('.workspace-brand')?.focus()
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setMenuOpen(false); menuButton.current?.focus() }
      if (event.key === 'Tab') {
        const buttons = Array.from(panel?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []).filter(button => button.getClientRects().length > 0)
        const first = buttons[0], last = buttons[buttons.length - 1]
        const outside = !panel?.contains(document.activeElement)
        if (event.shiftKey && (outside || document.activeElement === first)) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && (outside || document.activeElement === last)) { event.preventDefault(); first?.focus() }
      }
    }
    desktop?.addEventListener('change', closeOnDesktop)
    document.addEventListener('keydown', handleKey)
    return () => {
      desktop?.removeEventListener('change', closeOnDesktop)
      document.removeEventListener('keydown', handleKey)
      if (!desktop?.matches && panel?.contains(document.activeElement)) previous?.focus()
    }
  }, [menuOpen])
  const closeMenu = () => setMenuOpen(false)
  return <div className={['workbench-shell', className, collapsed && 'is-collapsed'].filter(Boolean).join(' ')}>
    <button ref={menuButton} type="button" className="workspace-mobile-menu button-quiet" aria-expanded={menuOpen} aria-controls={sidebarId}
      onClick={() => setMenuOpen(value => !value)}><WorkspaceIcon name="menu" />{t('导航')}</button>
    {menuOpen && <button type="button" tabIndex={-1} className="workspace-nav-backdrop" aria-label={t('关闭导航')} onClick={() => { closeMenu(); menuButton.current?.focus() }} />}
    <aside ref={sidebar} role={menuOpen ? 'dialog' : undefined} aria-modal={menuOpen ? true : undefined} aria-label={t('主要导航')} className={`workspace-sidebar${menuOpen ? ' is-open' : ''}`} id={sidebarId}>
      <div className="sidebar-header">
        <div className="sidebar-brand-row">
          <button type="button" className="workspace-brand" aria-label={t(homeLabel)} onClick={() => { onHome(); closeMenu() }}>
            <Brand />
            <span className="sidebar-text"><strong>PaperAssist</strong></span>
          </button>
          <button type="button" className="sidebar-toggle button-quiet" aria-expanded={!collapsed} aria-controls={sidebarId}
            aria-label={t(collapsed ? '展开侧边栏' : '收起侧边栏')} title={t(collapsed ? '展开侧边栏' : '收起侧边栏')}
            onClick={() => setCollapsed(value => !value)}><WorkspaceIcon name={collapsed ? 'expand' : 'collapse'} /></button>
        </div>
        {sidebarAction?.(closeMenu)}
      </div>
      <div className="sidebar-navigation">{navigation(closeMenu)}</div>
    </aside>
    <main className="workbench-content" tabIndex={-1}>{children}</main>
  </div>
}

export default function WorkspaceShell({ view, onNavigate, onCreate, projectName, projectType, section, onSectionChange, onCurrentProject, sectionBlocked, hasAnalysis = true, analysisOnly = false, overviewView, onOverviewChange, children }: Props) {
  const { t } = useI18n()
  const groups: { id: string; label: string; icon: 'folder' | 'chart' | 'files'; items: ProjectSection[] }[] = [
    { id: 'materials', label: '材料准备', icon: 'folder', items: ['files', 'literature'] },
    { id: 'analysis', label: hasAnalysis ? '分析与成果' : '成果与下载', icon: 'chart', items: hasAnalysis ? ['analysis', 'artifacts'] : ['artifacts'] },
    { id: 'writing', label: '稿件写作', icon: 'files', items: ['manuscripts', projectType === 'thesis' || projectType === 'research' ? 'school-templates' : 'journals'] },
    { id: 'reviews', label: '评审与修改', icon: 'files', items: ['reviews', 'tasks'] },
  ]
  const activeGroup = view === 'project' ? groups.find(group => group.items.includes(section ?? 'overview'))?.id : undefined
  const sectionLabel = (item: typeof projectSections[number]) => t(item.value === 'manuscripts' && projectType === 'research' ? '研究成果写作' : item.value === 'manuscripts' && projectType === 'thesis' ? '毕业论文写作' : item.label)
  const navigation = (closeMenu: () => void) => {
    const chooseSection = (next: ProjectSection) => { closeMenu(); onSectionChange?.(next) }
    const sectionButton = (value: ProjectSection) => {
      const item = projectSections.find(item => item.value === value)!
      return <button key={value} type="button" className="workspace-nav-item" disabled={!!sectionBlocked?.(value)} aria-label={sectionLabel(item)} title={t(sectionBlocked?.(value)||sectionLabel(item))}
        aria-current={view === 'project' && section === value ? 'page' : undefined} onClick={() => chooseSection(value)}>
        <WorkspaceIcon name={item.icon} /><span className="sidebar-text">{sectionLabel(item)}</span></button>
    }
    const navigate = (next: WorkspaceView) => { onNavigate(next); closeMenu() }
    function overviewButton(value: 'settings' | 'requirements' | 'deliveries', label: string, icon: 'folder' | 'file' | 'files') {
      const current = view === 'project' && section === 'overview' && (overviewView === value || value === 'requirements' && overviewView === 'design')
      return <button type="button" className="workspace-nav-item" aria-label={t(label)} title={t(label)} aria-current={current ? 'page' : undefined}
        onClick={() => { closeMenu(); onOverviewChange?.(value) }}><WorkspaceIcon name={icon} /><span className="sidebar-text">{t(label)}</span></button>
    }
    return <>
      <p className="sidebar-label">{t('工作空间')}</p>
      <nav aria-label={t('主要导航')}>
        <button type="button" className="workspace-nav-item" aria-current={view === 'home' ? 'page' : undefined}
          aria-label={t('工作台')} title={t('工作台')} onClick={() => navigate('home')}><WorkspaceIcon name="home" /><span className="sidebar-text">{t('工作台')}</span></button>
        <button type="button" className="workspace-nav-item" aria-current={view === 'projects' ? 'page' : undefined}
          aria-label={t('我的项目')} title={t('我的项目')} onClick={() => navigate('projects')}><WorkspaceIcon name="folder" /><span className="sidebar-text">{t('我的项目')}</span></button>
        {analysisOnly && <button type="button" className="workspace-nav-item" aria-current={view === 'assigned' ? 'page' : undefined}
          aria-label={t('分配给我的项目')} title={t('分配给我的项目')} onClick={() => navigate('assigned')}><WorkspaceIcon name="files" /><span className="sidebar-text">{t('分配给我的项目')}</span></button>}
      </nav>
      {projectName && <div className="sidebar-current"><p className="sidebar-label">{t('当前项目')}</p>
        <button type="button" className="workspace-nav-item current-project-name" aria-label={projectName} title={projectName}
          onClick={() => { closeMenu(); onCurrentProject() }}>
          <WorkspaceIcon name="file" /><span className="sidebar-text">{projectName}</span>
        </button>
        <nav className="project-section-nav" aria-label={t('项目导航')}>
          {analysisOnly ? <>
            {overviewButton('settings', '项目资料', 'folder')}
            {sectionButton('files')}
            {overviewButton('requirements', '需求与分析方案', 'file')}
            {sectionButton('analysis')}
            {sectionButton('artifacts')}
            {sectionButton('tasks')}
            {overviewButton('deliveries', '分析交付', 'files')}
          </> : groups.map(group => <div className={`workspace-nav-group${activeGroup === group.id ? ' is-current' : ''}`} key={group.id}>
            <button type="button" className="workspace-nav-item workspace-group-toggle" disabled={!!sectionBlocked?.(group.id==='reviews'?'reviews':group.items[0])} aria-label={t(group.label)} title={t(sectionBlocked?.(group.id==='reviews'?'reviews':group.items[0])||group.label)}
              aria-expanded={activeGroup === group.id} aria-controls={`workspace-group-${group.id}`} onClick={() => chooseSection(group.items.filter(item => projectType !== 'research' || item !== 'reviews')[0])}>
              <WorkspaceIcon name={group.icon} /><span className="sidebar-text">{t(group.label)}</span><span className="group-chevron sidebar-text" aria-hidden="true">›</span>
            </button>
            <div className="workspace-group-children" id={`workspace-group-${group.id}`} hidden={activeGroup !== group.id}>{group.items.filter(item => projectType !== 'research' || item !== 'reviews').map(sectionButton)}</div>
          </div>)}
        </nav>
      </div>}
    </>
  }
  return <WorkspaceFrame onHome={() => onNavigate('home')} navigation={navigation} sidebarAction={closeMenu =>
    <button type="button" className="sidebar-create button-primary" aria-label={t('新建研究项目')} title={t('新建项目')}
      onClick={() => { closeMenu(); onCreate() }}><WorkspaceIcon name="plus" /><span className="sidebar-text">{t('新建项目')}</span></button>
  }>{children}</WorkspaceFrame>
}
