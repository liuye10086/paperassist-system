import {useI18n} from '../../shared/i18n'
import BioReaderReport from '../bio-reader-reports/BioReaderReport'
import type {ReportLocation} from '../bio-reader-reports/navigation'
import type {BioReportContext} from '../bio-reader-reports/contracts'
import type {NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import {figureConfigName} from './bioPresentation'
import {sameProcessedBioSource,type BioProcessed} from './spatialContracts'

export default function ProcessedReaderReport({projectId,result,title,annotationId=null,active,location,deliveryTarget,restored,fixedEditing}:{
 projectId:string;result:BioProcessed;title:string;annotationId?:string|null;active?:boolean;location?:ReportLocation;
 deliveryTarget?:NativeDeliveryTarget;restored?:BioReportContext;fixedEditing?:boolean
}){
 const {t}=useI18n()
 const figures=result.figures.filter(figure=>figure.processed_source&&sameProcessedBioSource(figure.processed_source,result.source)
  &&(!figure.annotation_version_id||figure.annotation_version_id===annotationId)
  &&figure.members.some(member=>member.format==='png')&&(!figure.task||figure.task.status==='succeeded'))
  .map(figure=>({id:figure.id,title:figureConfigName(figure.config,t)}))
 return <BioReaderReport {...{projectId,active,title,location,deliveryTarget,restored,figures,fixedEditing}}
  selection={{kind:'processed',processed_version_id:result.id,annotation_version_id:annotationId}}/>
}
