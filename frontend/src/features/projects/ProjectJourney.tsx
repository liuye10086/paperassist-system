import { useI18n } from '../../shared/i18n'
import type { Project } from './projectTypes'
import type { ProjectSection } from './WorkspaceShell'
import type { OverviewView } from './projectNavigation'
import './projectJourney.css'

type Props = {
  project: Project; section: ProjectSection; overviewView: OverviewView
  onOverview: (view: OverviewView) => void; onUpload: () => void
  onAnalysis: () => void; onResults: () => void
}
export default function ProjectJourney({ project, section, overviewView, onOverview, onUpload, onAnalysis, onResults }: Props) {
  const { t } = useI18n()
  const step = section === 'files' ? 1 : section === 'overview' && ['requirements', 'design'].includes(overviewView) ? 2
    : section === 'analysis' ? 3 : section === 'artifacts' ? 4 : section === 'overview' ? 0 : -1
  const steps = [
    { title: '项目资料', description: '给研究起个名字', action: () => onOverview('settings') },
    { title: '上传文件', description: '数据、报告或图片', action: onUpload },
    { title: '选择需求', description: '按模块勾选内容', action: () => onOverview('requirements') },
    { title: '执行分析', description: '核对材料并开始', action: onAnalysis },
    { title: '查看结果', description: '查看、下载或继续', action: onResults },
  ]
  return <div className="project-journey">
    <nav aria-label={t('项目操作步骤')}><ol>{steps.map((item, index) => <li key={item.title}>
      <button type="button" aria-label={t('第 {number} 步：{title}', { number: index + 1, title: t(item.title) })} aria-current={step === index ? 'step' : undefined} onClick={item.action}>
        <span className="journey-number" aria-hidden="true">{index + 1}</span><span><strong>{t(item.title)}</strong><small>{t(item.description)}</small></span>
      </button>
    </li>)}</ol></nav>
    {section === 'files' && <section className="journey-context"><div><span className="workspace-eyebrow">{t('第 2 步 · 准备材料')}</span><h2>{t('先把研究资料放进来')}</h2><p>{t('上传原始数据、分组表、已有报告或图片。已有成果可以继续使用。')}</p></div><button type="button" onClick={() => onOverview('requirements')}>{t(project.file_count > 0 ? '下一步：选择需求' : '先填写需求，稍后补充文件')}<span aria-hidden="true">→</span></button></section>}
    {section === 'overview' && overviewView === 'requirements' && <div className="journey-intro"><span className="workspace-eyebrow">{t('第 3 步 · 告诉我们你的需求')}</span><h2>{t('想分析什么，想得到什么？')}</h2><p>{t('按顺序选择需要的内容。不确定的地方可以保留“待确认”，保存后再继续。')}</p></div>}
    {section === 'analysis' && <div className="journey-intro"><span className="workspace-eyebrow">{t('第 4 步 · 分析数据')}</span><p>{t('先核对数据和分组，再开始所选分析。运行进度与结果会保留在本项目中。')}</p></div>}
  </div>
}

export function ProjectResultActions({ projectType, onWriting, onExit }: { projectType: Project['project_type']; onWriting: (kind: 'sci_draft' | 'thesis_draft') => void; onExit: () => void }) {
  const { t } = useI18n()
  return <section className="journey-result-actions" aria-label={t('结果之后的下一步')}>
    <div><span className="workspace-eyebrow">{t('接下来，由你选择')}</span><h2>{t('只做分析，或继续完成论文')}</h2><p>{t('先查看下方已有成果。需要写作时，可以将已核对的结果带入下一模块。')}</p></div>
    <div className="journey-actions">
      {projectType !== 'thesis' && <button type="button" className="button-primary" onClick={() => onWriting('sci_draft')}>{t('继续写 SCI 论文')}<span aria-hidden="true">→</span></button>}
      {projectType !== 'sci' && <button type="button" onClick={() => onWriting('thesis_draft')}>{t('继续写毕业论文')}<span aria-hidden="true">→</span></button>}
      <button type="button" className="button-quiet" onClick={onExit}>{t('暂时结束，返回我的项目')}</button>
    </div><p className="muted">{t('已保存的成果会保留，之后可从“我的项目”继续。')}</p>
  </section>
}
