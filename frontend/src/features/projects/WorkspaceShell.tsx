import { useState, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import './workspace.css'

export type WorkspaceView = 'home' | 'projects' | 'project'
export type ProjectSection = 'overview' | 'files' | 'analysis' | 'artifacts'
const projectSections: { value: ProjectSection; label: string; icon: 'home' | 'folder' | 'chart' | 'files' }[] = [
  { value: 'overview', label: '项目概览', icon: 'home' }, { value: 'files', label: '项目文件', icon: 'folder' },
  { value: 'analysis', label: '数据分析', icon: 'chart' }, { value: 'artifacts', label: '图表与报告', icon: 'files' },
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
  section?: ProjectSection
  onSectionChange?: (section: ProjectSection) => void
  onCurrentProject: () => void
  children: ReactNode
}

export default function WorkspaceShell({ view, onNavigate, onCreate, projectName, section, onSectionChange, onCurrentProject, children }: Props) {
  const { t } = useI18n()
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const navigate = (next: WorkspaceView) => { onNavigate(next); setMenuOpen(false) }
  return <div className={`workbench-shell${collapsed ? ' is-collapsed' : ''}`}>
    <button type="button" className="workspace-mobile-menu button-quiet" aria-expanded={menuOpen} aria-controls="workspace-sidebar"
      onClick={() => setMenuOpen(value => !value)}><WorkspaceIcon name="menu" />{t('导航')}</button>
    <aside className={`workspace-sidebar${menuOpen ? ' is-open' : ''}`} id="workspace-sidebar">
      <button type="button" className="sidebar-toggle button-quiet" aria-expanded={!collapsed} aria-controls="workspace-sidebar"
        aria-label={t(collapsed ? '展开侧边栏' : '收起侧边栏')} title={t(collapsed ? '展开侧边栏' : '收起侧边栏')}
        onClick={() => setCollapsed(value => !value)}><WorkspaceIcon name={collapsed ? 'expand' : 'collapse'} /></button>
      <button type="button" className="workspace-brand" aria-label={t('返回工作台')} onClick={() => navigate('home')}>
        <span className="workspace-brand-mark" aria-hidden="true"><i /><i /><i /></span>
        <span className="sidebar-text"><strong>PaperAssist</strong><small>{t('让研究有条不紊')}</small></span>
      </button>
      <button type="button" className="sidebar-create button-primary" aria-label={t('新建研究项目')} title={t('新建项目')}
        onClick={onCreate}><WorkspaceIcon name="plus" /><span className="sidebar-text">{t('新建项目')}</span></button>
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
        <nav className="project-section-nav" aria-label={t('项目导航')}>{projectSections.map(item =>
          <button key={item.value} type="button" className="workspace-nav-item"
            aria-label={t(item.label)} title={t(item.label)}
            aria-current={view === 'project' && section === item.value ? 'page' : undefined}
            onClick={() => { setMenuOpen(false); onSectionChange?.(item.value) }}><WorkspaceIcon name={item.icon} /><span className="sidebar-text">{t(item.label)}</span></button>)}</nav>
      </div>}
      <div className="sidebar-note"><WorkspaceIcon name="file" /><strong>{t('从一份数据开始')}</strong>
        <p>{t('在项目中整理文件，让分析与成果始终有据可循。')}</p></div>
      <p className="sidebar-footer">{t('科研论文辅助系统')}</p>
    </aside>
    <main className="workbench-content" tabIndex={-1}>{children}<footer className="workspace-footer"><span>PaperAssist</span><span>{t('以清晰的过程，支持严谨的研究。')}</span></footer></main>
  </div>
}
