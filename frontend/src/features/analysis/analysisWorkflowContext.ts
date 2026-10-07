import { createContext, useContext } from 'react'

export type AnalysisStage = 'setup' | 'statistics' | 'figure' | 'explanation' | 'report'
type WorkflowContextValue = { stage: AnalysisStage; setStage: (stage: AnalysisStage) => void }
export const WorkflowContext = createContext<WorkflowContextValue | null>(null)
export function useWorkflowNavigation() { return useContext(WorkflowContext) }
