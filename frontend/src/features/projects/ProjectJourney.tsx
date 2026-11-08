import { useI18n } from '../../shared/i18n'
import { useContext } from 'react'
import { createPortal } from 'react-dom'
import { ProjectWorkspaceVisibleContext, WorkspaceChromeContext } from '../../shared/components/WorkspaceChromeContext'
import type { Project } from './projectTypes'
import type { ProjectSection } from './WorkspaceShell'
import type { OverviewView } from './projectNavigation'
import './projectJourney.css'
import { projectFlowStep } from './useProjectFlow'
import type {AnalysisNavigation} from './analysisViews'

type Props = {
  project: Project; section: ProjectSection; overviewView: OverviewView
  onOverview: (view: OverviewView) => void; onUpload: () => void
  onAnalysis: () => void; onResults: () => void
  active?: boolean
  hasAnalysis?: boolean
  analysisView?: AnalysisNavigation['view']
  onWriting: () => void
  blocked: (section: ProjectSection, view?: OverviewView) => string
}
export default function ProjectJourney({ section, overviewView, onOverview, onUpload, onAnalysis, onResults, onWriting, blocked, hasAnalysis = true, active = true, analysisView }: Props) {
  const { t } = useI18n()
  const chrome = useContext(WorkspaceChromeContext)
  const workspaceVisible = useContext(ProjectWorkspaceVisibleContext)
  const step = section==='analysis' && ['bio-result','bio-insight-result','report'].includes(analysisView??'') ? 4 : projectFlowStep(section, overviewView, hasAnalysis)
  const reasons = ['', '', blocked('overview','requirements'), blocked(hasAnalysis?'analysis':'manuscripts'), blocked('artifacts')]
  const steps = [
    { title: '项目资料', description: '给研究起个名字', action: () => onOverview('settings') },
    { title: '文件上传/整理', description: '上传、核对并整理数据、报告或图片', action: onUpload },
    { title: '选择需求', description: '按模块勾选内容', action: () => onOverview('requirements') },
    { title: hasAnalysis?'执行分析':'稿件写作', description: '核对材料并开始', action: hasAnalysis?onAnalysis:onWriting },
    { title: '查看结果', description: '查看、下载或继续', action: onResults },
  ]
  const navigation = <nav className={`project-steps${chrome ? ' is-compact' : ''}`} aria-label={t('项目操作步骤')}><ol>{steps.map((item, index) => <li key={item.title}>
      <button type="button" disabled={!!reasons[index]} title={t(reasons[index]||item.description)} aria-label={t('第 {number} 步：{title}', { number: index + 1, title: t(item.title) })} aria-current={step === index ? 'step' : undefined} onClick={item.action}>
        <span className="journey-number" aria-hidden="true">{index + 1}</span><span><strong>{t(item.title)}</strong><small>{t(item.description)}</small></span>
      </button>
    </li>)}</ol></nav>
  return <div className="project-journey">
    {active && workspaceVisible && (chrome ? chrome.navigation && createPortal(navigation, chrome.navigation) : navigation)}
  </div>
}

export function ProjectJourneyNextAction({onUpload}:{onUpload:()=>void}) {
  const {t}=useI18n()
  return <footer className="journey-next-action">
    <p>{t('项目资料可分别保存。接下来准备本次分析的矩阵、样本信息或已有材料。')}</p>
    <button type="button" className="button-primary" onClick={onUpload}>{t('下一步：上传矩阵与样本材料')}<span aria-hidden="true"> →</span></button>
  </footer>
}

export function ProjectResultActions({ projectType, onWriting, onExit, onExistingManuscripts, onDeliveries }: { projectType: Project['project_type']; onWriting: (kind: 'sci_draft' | 'thesis_draft') => void; onExit: () => void; onExistingManuscripts: () => void; onDeliveries: () => void }) {
  const { t } = useI18n()
  return <section className="journey-result-actions" aria-label={t('结果之后的下一步')}>
    <div className="result-action-group"><h3>{t('稿件与交付')}</h3><div className="journey-actions">
      <button type="button" onClick={onExistingManuscripts}>{t('查看已有稿件与 Word 下载')}</button>
      <button type="button" onClick={onDeliveries}>{t('交付登记')}</button>
    </div></div><div className="result-action-group"><h3>{t('继续写作')}</h3><div className="journey-actions">
      {projectType !== 'thesis' && <button type="button" className="button-primary" onClick={() => onWriting('sci_draft')}>{t('继续写 SCI 论文')}<span aria-hidden="true">→</span></button>}
      {projectType !== 'sci' && <button type="button" onClick={() => onWriting('thesis_draft')}>{t('继续写毕业论文')}<span aria-hidden="true">→</span></button>}
    </div></div>
      <button type="button" className="button-quiet result-exit" onClick={onExit}>{t('暂时结束，返回我的项目')}</button>

  </section>
}
