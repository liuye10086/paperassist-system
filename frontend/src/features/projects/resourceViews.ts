import type { AnalysisNavigation } from './analysisViews'

export type ResourceView = 'list' | 'upload' | 'detail' | 'preview' | 'quality'
export type ResourceNavigation = { view: ResourceView; fileId: string; bio?: AnalysisNavigation }
