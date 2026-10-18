import {validStatisticsContext} from './statisticsContext'
import {sameSource, validOptionalSource, type DatasetAnalysisSource} from './datasetSource'
import type {Result} from './StatisticsResults'
import type {TaskView} from '../tasks/taskTypes'
import {sameSelection,type AnalysisSelection} from './analysisSelection'

export type StatisticsTaskContext={base:string;revision:number;source?:DatasetAnalysisSource;plan?:{plan_id:string;sha256:string};language?:'zh-CN'|'en';selection?:AnalysisSelection}
const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)
const integer=(value:unknown,min=0):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=min
const text=(value:unknown):value is string=>typeof value==='string'&&value.length>0
const strings=(value:unknown)=>Array.isArray(value)&&value.every(item=>typeof item==='string')
function summary(value:unknown):boolean{
 return object(value)&&integer(value.n,1)&&['mean','min','q1','median','q3','max'].every(key=>typeof value[key]==='number'&&Number.isFinite(value[key]))&&['std','iqr'].every(key=>value[key]===null||typeof value[key]==='number'&&Number.isFinite(value[key]))&&strings(value.warnings)
}
export function taskMatchesStatisticsContext(task:TaskView, context:StatisticsTaskContext):boolean{
 const match=/^\/api\/v1\/projects\/([^/]+)\/files\/([^/]+)$/.exec(context.base)
 const input=task.input_version
 return !!match&&task.project_id===decodeURIComponent(match[1])&&task.task_type==='statistics_compute'&&input.kind==='statistics_compute'&&input.setup_revision===context.revision&&(context.language===undefined||input.output_language===context.language)&&sameSource(input.source,context.source)&&input.analysis_plan_id===(context.plan?.plan_id??null)&&(input.source===null||input.source.file_id===decodeURIComponent(match[2]))
}
export function validStatisticsTaskResult(value:unknown, context:StatisticsTaskContext, runId?:string):value is Result{
 if(!object(value)||!text(value.id)||runId!==undefined&&value.id!==runId||!object(value.selection)||!text(value.filename)||!text(value.source_sha256)||!object(value.check)||!text(value.completed_at)||!Number.isFinite(Date.parse(value.completed_at))||!text(value.started_at)||!Number.isFinite(Date.parse(value.started_at))||value.setup_revision!==context.revision)return false
 const match=/^\/api\/v1\/projects\/([^/]+)\/files\/([^/]+)$/.exec(context.base)
 if(!match||value.file_id!==decodeURIComponent(match[2]))return false
 const result=value as unknown as Result
 try{
  if(!validOptionalSource(result,context.source)||!validStatisticsContext(result,context.base,context.plan))return false
  if(context.selection&&!sameSelection(result.selection,context.selection))return false
  if(context.language!==undefined&&(result.analysis_context?.plan.research_request?.output_language??'zh-CN')!==context.language)return false
  if(result.result_type===undefined&&(!summary(result.overall)||!Array.isArray(result.groups)||!result.groups.every(group=>object(group)&&typeof group.label==='string'&&summary(group.statistics))||!text(result.numeric_name)||!(result.group_name===null||typeof result.group_name==='string')||!integer(result.check.row_count)||!integer(result.check.valid_count,1)||!integer(result.check.excluded_count)||!strings(result.check.warnings)))return false
  return true
 }catch{return false}
}
