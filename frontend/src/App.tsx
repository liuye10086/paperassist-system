import './App.css'
import ProjectWorkspace from './ProjectWorkspace'
import AuthBoundary from './auth/AuthBoundary'
function App() {
  return <main className="workspace"><h1>PaperAssist System</h1><p>科研论文辅助系统</p><AuthBoundary><ProjectWorkspace /></AuthBoundary></main>
}
export default App
