import { useI18n } from '../../shared/i18n'
import { useId, useRef, useState, type ReactNode } from 'react'
import type { Project } from './projectTypes'
import type { OverviewView } from './projectNavigation'
import { WorkspaceIcon } from './WorkspaceShell'
import ProjectSummary from './ProjectSummary'
import ProjectModelUsage from '../model-usage/ProjectModelUsage'
import './projectOverview.css'

type InfoView = Extract<OverviewView, 'settings' | 'activity' | 'usage'>
const views = [
  { value: 'settings', label: '项目资料', icon: 'folder' },
  { value: 'activity', label: '进展记录', icon: 'files' },
  { value: 'usage', label: '项目用量', icon: 'chart' },
] as const

export default function ProjectInfoActions({ project, active, view, onViewChange, children, error, onOpenJournals, onOpenManuscripts, analysisOnly = false }: {
  project: Project; active: boolean; error?: string
  view: OverviewView; onViewChange: (view: InfoView) => void; children: ReactNode
  onOpenJournals: () => void; onOpenManuscripts: () => void
  analysisOnly?: boolean
}) {
  const { t } = useI18n()
  const panelId = useId()
  const buttons = useRef<Partial<Record<InfoView, HTMLButtonElement | null>>>({})
  const [usageOpened, setUsageOpened] = useState(view === 'usage')
  if (view === 'usage' && !usageOpened) setUsageOpened(true)
  return <section className="project-info-card project-info-main" aria-label={t('项目资料')} hidden={!active}>
    <header className="project-info-title"><WorkspaceIcon name="folder"/><h1>{project.name}</h1></header>
    {analysisOnly ? children : <>
    <div className="project-info-tabs" role="tablist" aria-label={t('项目资料')}>
      {views.map((item, index) => <button key={item.value} type="button" role="tab"
        ref={element => { buttons.current[item.value] = element }}
        id={`${panelId}-tab-${item.value}`} aria-selected={view === item.value}
        aria-controls={`${panelId}-${item.value}`} tabIndex={view === item.value ? 0 : -1}
        onClick={() => onViewChange(item.value)} onKeyDown={event => {
          const target = event.key === 'ArrowRight' ? (index + 1) % views.length
            : event.key === 'ArrowLeft' ? (index + views.length - 1) % views.length
              : event.key === 'Home' ? 0 : event.key === 'End' ? views.length - 1 : -1
          if (target < 0) return
          event.preventDefault()
          onViewChange(views[target].value)
          buttons.current[views[target].value]?.focus()
        }}><WorkspaceIcon name={item.icon}/><span>{t(item.label)}</span></button>)}
    </div>
    {error && <p role="status">{t('流程状态读取失败，请刷新页面后重试。')}</p>}
    {views.map(item => <div key={item.value} id={`${panelId}-${item.value}`} role="tabpanel" tabIndex={0}
      aria-labelledby={`${panelId}-tab-${item.value}`} className={`project-info-panel project-info-panel-${item.value}`}
      hidden={view !== item.value}>
      {item.value === 'settings' ? children : item.value === 'activity'
        ? <ProjectSummary projectId={project.id} projectType={project.project_type} view="overview" active={active && view === 'activity'} onOpenJournals={onOpenJournals} onOpenManuscripts={onOpenManuscripts}/>
        : <ProjectModelUsage layered projectId={project.id} active={active && (view === 'usage' || usageOpened)}/>}
    </div>)}
    </>}
  </section>
}
