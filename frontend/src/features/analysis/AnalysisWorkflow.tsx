import { useState, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import { WorkflowContext, useWorkflowNavigation, type AnalysisStage } from './analysisWorkflowContext'
import './analysisWorkflow.css'

export function WorkflowProvider({ children, stage, onStageChange }: { children: ReactNode; stage?: AnalysisStage; onStageChange?: (stage: AnalysisStage) => void }) {
  const [localStage, setLocalStage] = useState<AnalysisStage>('setup')
  function setStage(next: AnalysisStage) { if (stage === undefined) setLocalStage(next); onStageChange?.(next) }
  return <WorkflowContext.Provider value={{ stage: stage ?? localStage, setStage }}>{children}</WorkflowContext.Provider>
}
export function WorkflowStage({ stage, children }: { stage: AnalysisStage; children: ReactNode }) {
  const navigation = useWorkflowNavigation()
  return <div className="workflow-stage" hidden={!!navigation && navigation.stage !== stage}>{children}</div>
}
export function WorkflowNavigation({ onOpenFiles,readiness }: { onOpenFiles?: () => void;readiness?:{source:boolean;configured:boolean} }) {
  const { t } = useI18n()
  const navigation = useWorkflowNavigation()
  if (!navigation) return null
  const stages: [AnalysisStage, string][] = [['setup', '字段配置'], ['profile', '数据概况'], ['plan', '分析方案'], ['statistics', '统计结果'], ['figure', '图表'], ['explanation', '分析解释'], ['report', 'Word报告']]
  return <nav className="analysis-workflow-nav" aria-label={t('分析流程')}>
    {stages.map(([stage, label], index) => <button type="button" key={stage} aria-current={navigation.stage === stage ? 'step' : undefined} disabled={!!readiness&&stage!=='setup'&&(['profile','plan'].includes(stage)?!readiness.source:!readiness.configured)} title={readiness&&!readiness.source&&stage!=='setup'?t('先选择数据版本与工作表'):readiness&&!readiness.configured&&!['setup','profile','plan'].includes(stage)?t('先保存有效分析配置'):undefined} onClick={() => navigation.setStage(stage)}><span aria-hidden="true">{index+1}. </span>{t(label)}</button>)}
    {readiness&&!readiness.source&&onOpenFiles&&<button type="button" className="button-quiet" onClick={onOpenFiles}>{t('返回上传文件')}</button>}
  </nav>
}
export function WorkflowEmptyResults({ message }: { message: string }) {
  const { t } = useI18n()
  return <>{(['figure', 'explanation', 'report'] as const).map(stage => <WorkflowStage key={stage} stage={stage}><p className="workflow-empty">{t(message)}</p></WorkflowStage>)}</>
}

export function WorkflowReadStatus({ stages, loading, error, loadingMessage, reloadLabel, onReload, disabled }: {
  stages: AnalysisStage[]; loading: boolean; error: string; loadingMessage: string; reloadLabel: string
  onReload: () => void; disabled?: boolean
}) {
  const { t } = useI18n()
  const navigation = useWorkflowNavigation()
  if (!navigation || !stages.includes(navigation.stage) || (!loading && !error)) return null
  return <div className="workflow-read-status">
    {loading ? <p role="status">{t(loadingMessage)}</p> : <p role="alert" className="error-panel">{t(error)}</p>}
    <button type="button" disabled={loading || disabled} onClick={onReload}>{t(reloadLabel)}</button>
  </div>
}
