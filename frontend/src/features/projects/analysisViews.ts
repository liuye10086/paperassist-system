import type { AnalysisStage } from '../analysis/analysisWorkflowContext'
import type {BulkPanel} from '../bio-insights/bulk'
export const bioResultTabs=['qc','embedding','clusters','markers','spatial','methods'] as const
export type BioResultTab=typeof bioResultTabs[number]
export const bulkWorkflowViews=['design','data','qc','differential','functional','delivery'] as const
export type BulkWorkflowView=typeof bulkWorkflowViews[number]
export function isBulkWorkflowView(value:unknown):value is BulkWorkflowView {
  return (bulkWorkflowViews as readonly unknown[]).includes(value)
}
export const analysisEntryIntents=['table','bio','comparison','ora','gsea_prerank','candidate','integration','single_cell_topic','evidence','qpcr','figure','report'] as const
export type AnalysisEntryIntent=typeof analysisEntryIntents[number]
export type AnalysisEntryContext={requirementVersionId:string;scopeItemId:string}
export type AnalysisNavigation = { entry?:AnalysisEntryContext;intent?:AnalysisEntryIntent; view: 'bulk-workflow' | 'bio-insights' | 'bio-insight-plan' | 'bio-insight-result' | 'bio-resources' | 'bio-candidates' | 'research-findings' | 'overview' | 'research-request' | AnalysisStage | 'bio-datasets' | 'bio-import' | 'bio-dataset' | 'bio-analysis-setup' | 'bio-analysis' | 'bio-result' | 'bio-annotation' | 'bio-figure'; fileId: string; importId?: string; datasetId?: string; versionId?: string; setupId?:string;runId?:string;processedId?:string;tab?:BioResultTab;annotationSetId?:string;annotationVersionId?:string;planId?:string;planVersionId?:string;resultVersionId?:string;resourceVersionId?:string;figureId?:string;findingSetId?:string;findingVersionId?:string;bulkPanel?:BulkPanel;bulkView?:BulkWorkflowView }
export const analysisViews = ['bulk-workflow','bio-insights','bio-insight-plan','bio-insight-result','bio-resources','bio-candidates','research-findings','overview','research-request','setup','profile','plan','statistics','figure','explanation','report','bio-datasets','bio-import','bio-dataset','bio-analysis-setup','bio-analysis','bio-result','bio-annotation','bio-figure'] as const
export type ArtifactNavigation = { view:'list'|'detail'|'layout'|'research-figures'|'research-reports'; artifactId:string; kind:''|'figure'|'report'; page:number }
