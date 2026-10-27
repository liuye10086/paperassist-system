import { useI18n } from '../../shared/i18n'
import { WorkspaceIcon, type ProjectSection } from './WorkspaceShell'
import type { Project } from './projectTypes'
import './projectOverview.css'

export type OverviewView = 'tasks' | 'settings' | 'activity' | 'usage'
const views: { value: OverviewView; label: string }[] = [
  { value: 'tasks', label: '研究任务' }, { value: 'settings', label: '项目资料' },
  { value: 'activity', label: '进展记录' }, { value: 'usage', label: '项目用量' },
]

export default function ProjectOverview({ project, view, onViewChange, onNavigate }: {
  project: Project; view: OverviewView; onViewChange: (view: OverviewView) => void
  onNavigate: (section: ProjectSection) => void
}) {
  const { t, locale } = useI18n()
  const groups: { title: string; description: string; icon: 'folder' | 'chart' | 'file' | 'files'; links: { section: ProjectSection; label: string }[] }[] = [
    { title: '材料准备', description: '归集研究文件，整理文献与引用依据。', icon: 'folder', links: [
      { section: 'files', label: '整理研究资料' }, { section: 'literature', label: '检索与核验文献' },
    ] },
    { title: '分析与成果', description: '从数据与方案，走向可追溯的图表和报告。', icon: 'chart', links: [
      { section: 'analysis', label: '继续数据分析' }, { section: 'artifacts', label: '查看图表与报告' },
    ] },
    { title: '稿件写作', description: '组织事实与依据，按目标规范完成稿件。', icon: 'file', links: [
      { section: 'manuscripts', label: project.project_type === 'thesis' ? '打开毕业论文写作' : '打开 SCI 写作' },
      { section: project.project_type === 'thesis' ? 'school-templates' : 'journals', label: project.project_type === 'thesis' ? '查看学校模板' : '打开期刊建议' },
    ] },
    { title: '评审与修改', description: '逐轮处理意见，跟进修改、回复与任务。', icon: 'files', links: [
      { section: 'reviews', label: '处理评审意见' }, { section: 'tasks', label: '查看项目任务' },
    ] },
  ]
  return <>
    <div className="project-overview-heading"><h2>{t('项目概览')}</h2>
      <span className="muted">{t('最近更新 {date}', { date: new Date(project.updated_at).toLocaleDateString(locale) })}</span>
    </div>
    <nav className="overview-view-switcher" aria-label={t('项目概览视图')}>
      {views.map(item => <button key={item.value} type="button" aria-pressed={view === item.value}
        onClick={() => onViewChange(item.value)}>{t(item.label)}</button>)}
    </nav>
    <section className="project-task-groups" aria-label={t('研究任务')} hidden={view !== 'tasks'}>
      <p className="overview-intro">{t('选择当前要推进的工作，每次专注一项任务。')}</p>
      <div className="project-task-grid">{groups.map((group, index) => <article key={group.title} className="project-task-card">
        <div className="task-card-top"><span className="task-card-icon"><WorkspaceIcon name={group.icon} /></span><span className="task-card-number">0{index + 1}</span></div>
        <h3>{t(group.title)}</h3><p>{t(group.description)}</p>
        <div className="task-card-actions">{group.links.map(link => <button key={link.section} type="button" className="button-quiet"
          onClick={() => onNavigate(link.section)}>{t(link.label)}<WorkspaceIcon name="arrow" /></button>)}</div>
      </article>)}</div>
    </section>
  </>
}
