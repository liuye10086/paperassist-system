import './App.css'
import ProjectWorkspace from '../features/projects/ProjectWorkspace'
import AuthBoundary from '../features/auth/AuthBoundary'
function App() {
  return <div className="workspace"><AuthBoundary><ProjectWorkspace /></AuthBoundary></div>
}
export default App
