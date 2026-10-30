import type { AnalysisStage } from '../analysis/analysisWorkflowContext'
export const bioResultTabs=['qc','embedding','clusters','markers','spatial','methods'] as const
export type BioResultTab=typeof bioResultTabs[number]
export type AnalysisNavigation = { view: 'overview' | AnalysisStage | 'bio-datasets' | 'bio-import' | 'bio-dataset' | 'bio-analysis-setup' | 'bio-analysis' | 'bio-result' | 'bio-annotation' | 'bio-figure'; fileId: string; importId?: string; datasetId?: string; versionId?: string; setupId?:string;runId?:string;processedId?:string;tab?:BioResultTab;annotationSetId?:string;annotationVersionId?:string;figureId?:string }
export const analysisViews = ['overview','setup','profile','plan','statistics','figure','explanation','report','bio-datasets','bio-import','bio-dataset','bio-analysis-setup','bio-analysis','bio-result','bio-annotation','bio-figure'] as const
export type ArtifactNavigation = { view:'list'|'detail'|'layout'; artifactId:string; kind:''|'figure'|'report'; page:number }
