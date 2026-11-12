import './App.css'
import { useContext } from 'react'
import ProjectWorkspace from '../features/projects/ProjectWorkspace'
import AuthBoundary from '../features/auth/AuthBoundary'
import { AuthIdentityContext } from '../features/auth/AuthIdentityContext'
import OperationsWorkspace from '../features/operations/OperationsWorkspace'
import CustomerWorkspace from '../features/customer/CustomerWorkspace'
import { useI18n } from '../shared/i18n'

function RoleWorkspace() {
  const role = useContext(AuthIdentityContext)?.role
  const { t } = useI18n()
  if (role === 'admin') return <OperationsWorkspace key="admin" />
  if (role === 'customer') return <CustomerWorkspace key="customer" />
  if (role === 'analyst' || role === 'user') {
    return <OperationsWorkspace key="analyst"><ProjectWorkspace analysisOnly /></OperationsWorkspace>
  }
  return <main className="auth-account-status">
    <p role="alert">{t('当前账号角色无法识别。')}</p>
  </main>
}

function App() {
  return <div className="workspace"><AuthBoundary><RoleWorkspace /></AuthBoundary></div>
}
export default App
