import { useI18n } from '../../shared/i18n'
import { useContext } from 'react'
import { ProjectWorkspaceVisibleContext } from '../../shared/components/WorkspaceChromeContext'
import type { Project } from './projectTypes'
import type { ProjectSection } from './WorkspaceShell'
import type { OverviewView } from './projectNavigation'
import './projectJourney.css'
import WorkspaceSteps from './WorkspaceSteps'
import { projectFlowStep, type WorkflowState } from './useProjectFlow'
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
  workflowState?: WorkflowState
  analysisOnly?: boolean
  assigned?: boolean
}
export default function ProjectJourney({ project, section, overviewView, onOverview, onUpload, onAnalysis, onResults, onWriting, blocked, hasAnalysis = true, active = true, analysisView, workflowState, analysisOnly = false, assigned = false }: Props) {
  const { t } = useI18n()
  const workspaceVisible = useContext(ProjectWorkspaceVisibleContext)
  if (analysisOnly) {
    const current = section === 'overview' && overviewView === 'deliveries' ? 5
      : section === 'analysis' && ['bio-result','bio-insight-result','report'].includes(analysisView ?? '') ? 4
        : projectFlowStep(section, overviewView, true)
    return active && workspaceVisible ? <div className="project-journey"><WorkspaceSteps current={current} steps={[
      { title: '项目资料', action: () => onOverview('settings') },
      { title: '文件上传/整理', action: onUpload },
      { title: assigned ? '已提交需求' : '需求与分析方案', action: () => onOverview('requirements') },
      { title: '执行分析', action: onAnalysis, disabledReason: blocked('analysis') },
      { title: '查看结果', action: onResults },
      { title: '分析交付', action: () => onOverview('deliveries') },
    ]}/></div> : null
  }
  const step = section==='analysis' && ['bio-result','bio-insight-result','report'].includes(analysisView??'') ? 4 : projectFlowStep(section, overviewView, hasAnalysis)
  const reasons = ['', '', blocked('overview','requirements'), blocked(hasAnalysis?'analysis':'manuscripts'), blocked('artifacts')]
  // The route identifies the current step. Completion comes from saved workflow state.
  const state: WorkflowState = workflowState ?? {
    project_id: project.id,
    project_type: project.project_type,
    files: { total: project.file_count, ready: project.file_count },
    requirements: { saved: false, version: null, services: [] },
    results: { available: false },
    next_step: step <= 1 ? 'upload' : step === 2 ? 'requirements' : step === 3 ? (hasAnalysis ? 'analysis' : 'writing') : 'results',
  }
  const steps = [
    { title: '项目资料', description: '给研究起个名字', action: () => onOverview('settings') },
    { title: '文件上传/整理', description: '上传、核对并整理数据、报告或图片', action: onUpload },
    { title: '选择需求', description: '按模块勾选内容', action: () => onOverview('requirements') },
    { title: hasAnalysis?'执行分析':'稿件写作', description: '核对材料并开始', action: hasAnalysis?onAnalysis:onWriting },
    { title: '查看结果', description: '查看、下载或继续', action: onResults },
  ]
  const completed = [true, state.files.ready > 0, state.requirements.saved, state.results.available, state.results.available && step > 4]
  const primary = {
    upload: { label: '上传并继续', action: onUpload },
    requirements: { label: '保存需求并继续', action: () => onOverview('requirements') },
    analysis: { label: '开始分析', action: onAnalysis },
    results: { label: '查看结果', action: onResults },
    writing: { label: '继续写作', action: onWriting },
  }[state.next_step]
  const status = (index: number) => completed[index] ? '已完成'
    : state.next_step === (index === 1 ? 'upload' : index === 2 ? 'requirements' : index === 3 ? (hasAnalysis ? 'analysis' : 'writing') : index === 4 ? 'results' : '')
      ? '进行中' : index === 1 && state.files.total > state.files.ready ? '待补材料' : '待处理'
  const nextAction = <section className="journey-next-action" aria-label={t('下一步')}>
    <div><span className="journey-next-kicker">{t('下一步')}</span><strong>{t(primary.label)}</strong></div>
    <button type="button" className="button-primary" onClick={primary.action}>{t('下一步')}<span aria-hidden="true"> →</span></button>
  </section>
  return <div className="project-journey">
    {active && workspaceVisible && nextAction}
    {active && workspaceVisible && <WorkspaceSteps current={step} steps={steps.map((item, index) => ({
      ...item, status: status(index), disabledReason: reasons[index],
    }))} />}
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
