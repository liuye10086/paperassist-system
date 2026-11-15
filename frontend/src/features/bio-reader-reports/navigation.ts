import type {AnalysisNavigation} from '../projects/analysisViews'

export type ReportLocation=Pick<AnalysisNavigation,'entry'|'intent'|'view'|'processedId'|'resultVersionId'|'tab'>

export function bioReportTaskLink(projectId:string,taskId:string,reportReturn:string){
 return '#'+new URLSearchParams({project:projectId,section:'tasks',view:'result',task:taskId,reportReturn})
}

export function bioReportLink(projectId:string,contextId:string,location?:ReportLocation,taskId?:string){
 const params=new URLSearchParams({project:projectId,section:'analysis',view:'bio-reader-report',reportContext:contextId})
 if(location?.entry){
  params.set('requirement',location.entry.requirementVersionId)
  params.set('scope',location.entry.scopeItemId)
  if(location.intent)params.set('intent',location.intent)
 }
 if((location?.view==='bio-result'||location?.view==='bio-reader-report')&&location.processedId){
  params.set('processed',location.processedId)
  if(location.tab)params.set('tab',location.tab)
 }
 if((location?.view==='bio-insight-result'||location?.view==='bio-reader-report')&&location.resultVersionId)
  params.set('resultVersionId',location.resultVersionId)
 if(taskId)params.set('reportTask',taskId)
 return '#'+params.toString()
}
