import { useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AuthIdentityContext } from '../auth/AuthIdentityContext'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { onApiSessionChanged } from '../../shared/api/client'
import { ProjectWorkspaceVisibleContext, WorkspaceChromeContext } from '../../shared/components/WorkspaceChromeContext'
import { safeError, useI18n } from '../../shared/i18n'
import AdminWorkspace from './AdminWorkspace'
import UsagePanel from './UsagePanel'
import { operationsRequest } from './operationsApi'
import './operations.css'

type Identity = { id: string; email: string; role: string }
type View = 'projects' | 'own' | 'admin'

export default function OperationsWorkspace({ children }: { children?: ReactNode }) {
  const hasProjects = children != null
  const confirmedIdentity = useContext(AuthIdentityContext)
  const chrome = useContext(WorkspaceChromeContext)
  const { t } = useI18n()
  const [identityRead, setIdentityRead] = useState<{ context: Identity | null; user: Identity | null } | null>(null)
  const user = identityRead?.context === confirmedIdentity ? identityRead.user : confirmedIdentity
  const [view, setView] = useState<View>(hasProjects ? 'projects' : 'admin')
  const [adminOpened, setAdminOpened] = useState(!hasProjects)
  const [ownOpened, setOwnOpened] = useState(false)
  const [error, setError] = useState('')
  const [valid, setValid] = useState(true)
  const identityRequest = useRef<AbortController | null>(null)
  const validRef = useRef(true)
  const guards = useRef(new Map<() => boolean, () => boolean>())

  const registerLeaveGuard = useCallback<RegisterLeaveGuard>((guard, isDirty = () => true) => {
    guards.current.set(guard, isDirty)
    return () => { guards.current.delete(guard) }
  }, [])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (Array.from(guards.current.values()).some(dirty => dirty())) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  const readIdentity = useCallback(async () => {
    identityRequest.current?.abort()
    const controller = new AbortController()
    identityRequest.current = controller
    try {
      const response = await operationsRequest<{ user: Identity }>('/api/v1/auth/me', controller.signal)
      if (!controller.signal.aborted && validRef.current && typeof response.user?.id === 'string') {
        setIdentityRead({ context: confirmedIdentity, user: response.user })
      }
    } catch (cause) {
      if (!controller.signal.aborted && validRef.current) {
        setIdentityRead({ context: confirmedIdentity, user: null })
        setView('projects')
        setError(safeError(cause, '运营信息读取失败，请重试。'))
      }
    }
  }, [confirmedIdentity])
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- The state update follows the server response.
    if (!confirmedIdentity) void readIdentity()
    const unsubscribe = onApiSessionChanged(() => {
      validRef.current = false
      identityRequest.current?.abort()
      setValid(false)
      setAdminOpened(false)
      setOwnOpened(false)
      setIdentityRead(null)
      setView('projects')
      setError('')
    })
    return () => { unsubscribe(); identityRequest.current?.abort() }
  }, [readIdentity, confirmedIdentity])
  const forbidden = useCallback(() => {
    setAdminOpened(false)
    setOwnOpened(false)
    setIdentityRead({ context: confirmedIdentity, user: null })
    setView('projects')
    setError('无法访问管理页面，请核对账号权限。')
    void readIdentity()
  }, [confirmedIdentity, readIdentity])

  function openWorkspace(next: View) {
    setView(next)
    if (next === 'admin') setAdminOpened(true)
    if (next === 'own') setOwnOpened(true)
    setError('')
    if (next !== 'projects') void readIdentity()
    chrome?.closeAccount()
  }

  const isAdmin = user?.role === 'admin' && valid && (!confirmedIdentity || confirmedIdentity.role === 'admin')
  const navigation = hasProjects && <nav className={chrome ? 'account-workspace-nav' : 'operations-nav'} aria-label={t('工作区入口')}>
    <button aria-pressed={view === 'projects'} onClick={() => openWorkspace('projects')}>{t('项目工作区')}</button>
    {user && valid && <button aria-pressed={view === 'own'} onClick={() => openWorkspace('own')}>{t('本人用量')}</button>}
    {isAdmin && <button aria-pressed={view === 'admin'} onClick={() => openWorkspace('admin')}>{t('管理员')}</button>}
  </nav>

  return <>
    {chrome?.accountMenu ? createPortal(navigation, chrome.accountMenu) : !chrome && navigation}
    {error && <div className="auth-session-error">
      <p role="alert">{t(error)}</p>
      {!hasProjects && isAdmin && !adminOpened && <button type="button" className="button-quiet" onClick={() => openWorkspace('admin')}>
        {t('重新打开管理页面')}
      </button>}
    </div>}
    {hasProjects && <div hidden={view !== 'projects'}>
      <ProjectWorkspaceVisibleContext.Provider value={view === 'projects'}>{children}</ProjectWorkspaceVisibleContext.Provider>
    </div>}
    {ownOpened && user && valid && <main hidden={view !== 'own'} className="operations-workspace">
      <h1>{t('本人用量')}</h1>
      <UsagePanel admin={false} onForbidden={forbidden} active={view === 'own'} registerLeaveGuard={registerLeaveGuard} />
    </main>}
    {isAdmin && adminOpened && <AdminWorkspace key={user.id} userId={user.id} active={view === 'admin'}
      onForbidden={forbidden} registerLeaveGuard={registerLeaveGuard} onProject={hasProjects ? () => openWorkspace('projects') : undefined} />}
  </>
}
