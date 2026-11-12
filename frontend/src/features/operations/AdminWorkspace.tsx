import { useCallback, useContext, useEffect, useId, useState, type ComponentProps } from 'react'
import { createPortal } from 'react-dom'
import { WorkspaceChromeContext } from '../../shared/components/WorkspaceChromeContext'
import { useI18n } from '../../shared/i18n'
import { WorkspaceFrame, WorkspaceIcon } from '../projects/WorkspaceShell'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import AccountsPanel from './AccountsPanel'
import ConfigurationsPanel from './ConfigurationsPanel'
import LogsPanel from './LogsPanel'
import { Table } from './OperationsCommon'
import ProjectAssignmentsPanel from './ProjectAssignmentsPanel'
import RegistrationQueuePanel from './RegistrationQueuePanel'
import RuntimeStatus from './RuntimeStatus'
import StoragePanel from './StoragePanel'
import TasksPanel from './TasksPanel'
import UsagePanel from './UsagePanel'
import { accountRoleName } from './operationsApi'

const pageNames = {
  reviews: '审核管理',
  accounts: '账号管理',
  permissions: '权限管理',
  tasks: '系统任务',
  usage: '用量统计',
  logs: '运行日志',
  configurations: '配置治理',
  storage: '存储治理',
  runtime: '运行状态',
} as const
type Page = keyof typeof pageNames

const primaryPages = [['reviews', 'file'], ['accounts', 'home'], ['permissions', 'files']] as const
const toolPages = ['tasks', 'usage', 'logs', 'configurations', 'storage', 'runtime'] as const

function addressPage(): Page {
  const value = window.location.hash.slice('#admin='.length)
  return window.location.hash.startsWith('#admin=') && Object.hasOwn(pageNames, value) ? value as Page : 'reviews'
}

const rolePermissions = [
  { role: 'admin', pages: '审核管理、账号管理、权限管理、运营工具', actions: '审核注册、管理账号、分配项目、查看操作审计' },
  { role: 'customer', pages: '客户项目工作台、账号菜单', actions: '上传资料、提交需求、查看进度与交付、发送反馈' },
  { role: 'analyst', pages: '本人项目、分配给我的项目、本人用量', actions: '整理资料、执行分析、发布客户交付' },
] as const

function PermissionsPanel({ onAccounts, active, onForbidden, registerLeaveGuard }: {
  onAccounts: () => void
  active: boolean
  onForbidden: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  return <section aria-label={t('权限管理')}>
    <ProjectAssignmentsPanel active={active} onForbidden={onForbidden} registerLeaveGuard={registerLeaveGuard} />
    <h2>{t('角色权限')}</h2>
    <Table headers={['角色', '可进入的页面', '可执行的关键操作']}>
      {rolePermissions.map(({ role, pages, actions }) => <tr key={role}>
        <td>{t(accountRoleName(role))}</td><td>{t(pages)}</td><td>{t(actions)}</td>
      </tr>)}
    </Table>
    <button onClick={onAccounts}>{t('去账号管理')}</button>
  </section>
}

export default function AdminWorkspace({ userId, active, onForbidden, onProject, registerLeaveGuard }: {
  userId: string
  active: boolean
  onForbidden: () => void
  onProject?: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const chrome = useContext(WorkspaceChromeContext)
  const toolsId = useId()
  const rememberAddress = !onProject
  const [page, setPage] = useState<Page>(() => rememberAddress ? addressPage() : 'reviews')
  const [visited, setVisited] = useState<Page[]>([page])
  const [toolsOpen, setToolsOpen] = useState(() => toolPages.some(value => value === page))
  const [logLink, setLogLink] = useState({ auditTarget: '', taskId: '', linkIntent: 0 })

  const showPage = useCallback((next: Page) => {
    setPage(next)
    setVisited(pages => pages.includes(next) ? pages : [...pages, next])
    if (toolPages.some(value => value === next)) setToolsOpen(true)
  }, [])

  useEffect(() => {
    if (!rememberAddress) return
    const restorePage = () => showPage(addressPage())
    window.addEventListener('popstate', restorePage)
    window.addEventListener('hashchange', restorePage)
    return () => {
      window.removeEventListener('popstate', restorePage)
      window.removeEventListener('hashchange', restorePage)
    }
  }, [rememberAddress, showPage])

  function selectPage(next: Page) {
    showPage(next)
    if (rememberAddress && page !== next) window.history.pushState(null, '', `#admin=${next}`)
  }

  function openLogs(auditTarget: string, taskId: string) {
    setLogLink(link => ({ auditTarget, taskId, linkIntent: link.linkIntent + 1 }))
    selectPage('logs')
  }

  function renderNavigation(closeMenu: () => void) {
    function pageButton(value: Page, icon: ComponentProps<typeof WorkspaceIcon>['name']) {
      const label = t(pageNames[value])
      return <button key={value} type="button" className="workspace-nav-item" aria-label={label} title={label}
        aria-current={page === value ? 'page' : undefined} onClick={() => { selectPage(value); closeMenu() }}>
        <WorkspaceIcon name={icon} /><span className="sidebar-text">{label}</span>
      </button>
    }
    return <nav aria-label={t('管理员页面')}>
      {primaryPages.map(([value, icon]) => pageButton(value, icon))}
      <div className="workspace-nav-group admin-sidebar-tools">
        <button type="button" className="workspace-nav-item workspace-group-toggle" aria-label={t('运营工具')} title={t('运营工具')}
          aria-expanded={toolsOpen} aria-controls={toolsId} onClick={() => setToolsOpen(open => !open)}>
          <WorkspaceIcon name="chart" /><span className="sidebar-text">{t('运营工具')}</span>
          <span className="group-chevron sidebar-text" aria-hidden="true">›</span>
        </button>
        <div className="workspace-group-children" id={toolsId} hidden={!toolsOpen}>
          {toolPages.map(value => pageButton(value, 'file'))}
        </div>
      </div>
    </nav>
  }

  const shown = (name: Page) => active && page === name
  const pageHeading = <h1 className="admin-page-title">{t(pageNames[page])}</h1>
  const shared = { onForbidden, registerLeaveGuard }
  return <div hidden={!active}>
    {active && chrome?.navigation && createPortal(pageHeading, chrome.navigation)}
    <WorkspaceFrame className="admin-workbench" homeLabel="返回审核管理" onHome={() => selectPage('reviews')} navigation={renderNavigation}>
      <div className="operations-workspace">
        {!chrome?.navigation && pageHeading}
        {visited.includes('reviews') && <div hidden={!shown('reviews')}><RegistrationQueuePanel {...shared} active={shown('reviews')} /></div>}
        {visited.includes('accounts') && <div hidden={!shown('accounts')}><AccountsPanel {...shared} userId={userId} active={shown('accounts')} onAudit={id => openLogs(id, '')} /></div>}
        {visited.includes('permissions') && <div hidden={!shown('permissions')}><PermissionsPanel {...shared}
          active={shown('permissions')} onAccounts={() => selectPage('accounts')} /></div>}
        {visited.includes('tasks') && <div hidden={!shown('tasks')}><TasksPanel {...shared} userId={userId} active={shown('tasks')} onProject={onProject} onLogs={id => openLogs('', id)} /></div>}
        {visited.includes('usage') && <div hidden={!shown('usage')}><UsagePanel {...shared} admin active={shown('usage')} /></div>}
        {visited.includes('logs') && <div hidden={!shown('logs')}><LogsPanel onForbidden={onForbidden} active={shown('logs')} {...logLink} /></div>}
        {visited.includes('configurations') && <div hidden={!shown('configurations')}><ConfigurationsPanel {...shared} active={shown('configurations')} /></div>}
        {visited.includes('storage') && <div hidden={!shown('storage')}><StoragePanel {...shared} admin active={shown('storage')} /></div>}
        {visited.includes('runtime') && <div hidden={!shown('runtime')}><RuntimeStatus onForbidden={onForbidden} active={shown('runtime')} /></div>}
      </div>
    </WorkspaceFrame>
  </div>
}
