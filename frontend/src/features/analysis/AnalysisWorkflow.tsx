import { useState, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import { WorkflowContext, useWorkflowNavigation, type AnalysisStage } from './analysisWorkflowContext'
import './analysisWorkflow.css'

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [stage, setStage] = useState<AnalysisStage>('setup')
  return <WorkflowContext.Provider value={{ stage, setStage }}>{children}</WorkflowContext.Provider>
}
export function WorkflowStage({ stage, children }: { stage: AnalysisStage; children: ReactNode }) {
  const navigation = useWorkflowNavigation()
  return <div className="workflow-stage" hidden={!!navigation && navigation.stage !== stage}>{children}</div>
}
export function WorkflowNavigation({ onOpenFiles }: { onOpenFiles?: () => void }) {
  const { t } = useI18n()
  const navigation = useWorkflowNavigation()
  if (!navigation) return null
  const stages: [AnalysisStage, string][] = [['setup', '字段配置'], ['statistics', '描述统计'], ['figure', '图表'], ['explanation', '分析解释'], ['report', 'Word报告']]
  return <nav className="analysis-workflow-nav" aria-label={t('分析流程')}>
    <button type="button" disabled={!onOpenFiles} onClick={onOpenFiles}>{t('数据')}</button>
    {stages.map(([stage, label]) => <button type="button" key={stage} aria-current={navigation.stage === stage ? 'step' : undefined} onClick={() => navigation.setStage(stage)}>{t(label)}</button>)}
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
