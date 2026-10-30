import type {AnalysisNavigation} from '../projects/analysisViews'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import BioAnalysisSetup from './BioAnalysisSetup'
import BioAnalysisReview from './BioAnalysisReview'
import BioAnalysisResult from './BioAnalysisResult'
import BioFigureDetail from './BioFigureDetail'
import {BioAnnotationDetail} from './BioAnnotationEditor'
import './spatial.css'
export default function BioSpatialWorkspace({projectId,navigation:n,onNavigate,registerLeaveGuard}:{projectId:string;navigation:AnalysisNavigation;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const common={projectId,onNavigate,registerLeaveGuard}
 if(n.view==='bio-analysis-setup'&&n.setupId)return <BioAnalysisSetup key={n.setupId} {...common} setupId={n.setupId}/>
 if(n.view==='bio-analysis'&&n.runId)return <BioAnalysisReview key={n.runId} {...common} runId={n.runId}/>
 if(n.view==='bio-result'&&n.processedId&&n.tab)return <BioAnalysisResult key={n.processedId} {...common} processedId={n.processedId} tab={n.tab}/>
 if(n.view==='bio-annotation'&&n.annotationSetId&&n.annotationVersionId)return <BioAnnotationDetail key={n.annotationVersionId} {...common} setId={n.annotationSetId} versionId={n.annotationVersionId}/>
 if(n.view==='bio-figure'&&n.figureId)return <BioFigureDetail key={n.figureId} {...common} figureId={n.figureId}/>
 return null
}
