import type { AnalysisStage } from '../analysis/analysisWorkflowContext'
export type AnalysisNavigation = { view: 'overview' | AnalysisStage; fileId: string }
export const analysisViews = ['overview','setup','profile','plan','statistics','figure','explanation','report'] as const
export type ArtifactNavigation = { view:'list'|'detail'|'layout'; artifactId:string; kind:''|'figure'|'report'; page:number }
