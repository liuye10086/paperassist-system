import './App.css'
import ProjectWorkspace from '../features/projects/ProjectWorkspace'
import AuthBoundary from '../features/auth/AuthBoundary'
import OperationsWorkspace from '../features/operations/OperationsWorkspace'
function App() {
  return <div className="workspace"><AuthBoundary><OperationsWorkspace layered><ProjectWorkspace /></OperationsWorkspace></AuthBoundary></div>
}
export default App
