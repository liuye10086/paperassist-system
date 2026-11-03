import { useI18n } from '../../shared/i18n'
import { useEffect, useId, useState } from 'react'
import type { Project } from './projectTypes'
import { WorkspaceIcon } from './WorkspaceShell'
import ProjectSummary from './ProjectSummary'
import ProjectModelUsage from '../model-usage/ProjectModelUsage'
import './projectOverview.css'

const views: { value: 'activity' | 'usage'; label: string }[] = [
  { value: 'activity', label: '进展记录' }, { value: 'usage', label: '项目用量' },
]

export default function ProjectInfoActions({ project, active, error, onOpenJournals, onOpenManuscripts }: {
  project: Project; active: boolean; error?: string
  onOpenJournals: () => void; onOpenManuscripts: () => void
}) {
  const { t } = useI18n()
  const [panel, setPanel] = useState<'activity' | 'usage' | null>('activity')
  const panelId = useId()
  useEffect(() => { if (!active) setPanel('activity') }, [active])
  return <section className="project-info-actions" aria-label={t('项目记录与用量')}>
    <header className="project-info-actions-heading"><h3>{t('项目记录与用量')}</h3></header>
    {error && <p role="status">{t('流程状态读取失败，请刷新页面后重试。')}</p>}
    <nav className="project-info-links" aria-label={t('项目记录与用量')}>
      {views.map(item => <button key={item.value} type="button" aria-expanded={panel === item.value} aria-controls={panelId}
        onClick={() => setPanel(current => current === item.value ? null : item.value)}><WorkspaceIcon name={item.value === 'activity' ? 'files' : 'chart'}/><span>{t(item.label)}</span></button>)}
    </nav>
    <div id={panelId} className="project-info-inline-content" hidden={!panel}>
      {panel === 'activity' && <ProjectSummary projectId={project.id} projectType={project.project_type} view="overview" active={active} onOpenJournals={onOpenJournals} onOpenManuscripts={onOpenManuscripts}/>}
      {panel === 'usage' && <ProjectModelUsage layered projectId={project.id} active={active}/>}
    </div>
  </section>
}
