import { createContext, useContext } from 'react'

export type AnalysisStage = 'setup' | 'profile' | 'plan' | 'statistics' | 'figure' | 'explanation' | 'report'
export type TableQualityOptions = { requireQuality?: boolean; onOpenQuality?: (fileId: string) => void }
type WorkflowContextValue = TableQualityOptions & { stage: AnalysisStage; setStage: (stage: AnalysisStage) => void }
export const WorkflowContext = createContext<WorkflowContextValue | null>(null)
export function useWorkflowNavigation() { return useContext(WorkflowContext) }
