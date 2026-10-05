import './App.css'
import ProjectWorkspace from './ProjectWorkspace'
import AuthBoundary from './auth/AuthBoundary'
import { useI18n } from './i18n'
function App() {
  const { t } = useI18n()
  return <main className="workspace"><h1>PaperAssist System</h1><p>{t('科研论文辅助系统')}</p><AuthBoundary><ProjectWorkspace /></AuthBoundary></main>
}
export default App
