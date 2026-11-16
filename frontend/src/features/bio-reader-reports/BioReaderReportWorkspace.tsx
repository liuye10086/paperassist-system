import {useI18n} from '../../shared/i18n'
import type {NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import type {AnalysisNavigation} from '../projects/analysisViews'
import {homeRoute,serializeNavigation} from '../projects/projectNavigation'
import {useResearchRead} from '../research-results/api'
import {isWorkspace} from '../tasks/taskTypes'
import {FixedBioReaderReport} from './BioReaderReport'
import {isBulkReportEnrichmentSource,reportIdentityError,type BioReportContext} from './contracts'
import {useBioReportContext} from './useBioReportContext'

function sourceMatches(context:BioReportContext,navigation:AnalysisNavigation){
 const selection=context.selection
 if(navigation.processedId)return selection.kind==='processed'&&selection.processed_version_id===navigation.processedId
  &&(!selection.annotation_version_id||!navigation.tab||navigation.tab==='spatial')
 if(navigation.resultVersionId)return selection.kind==='insight'?selection.result_version_id===navigation.resultVersionId:
  selection.kind==='bulk'&&(selection.delivery.comparison_version_id===navigation.resultVersionId
   ||isBulkReportEnrichmentSource(context,navigation.resultVersionId))
 return true
}

function reportSource(context:BioReportContext,navigation:AnalysisNavigation):AnalysisNavigation {
 const shared={fileId:'',entry:navigation.entry,intent:navigation.intent,reportContextId:context.id}
 const selection=context.selection
 if(selection.kind==='processed')return {...shared,view:'bio-result',processedId:selection.processed_version_id,
  tab:selection.annotation_version_id?'spatial':navigation.tab??'methods'}
 if(selection.kind==='insight')return {...shared,view:'bio-insight-result',resultVersionId:selection.result_version_id}
 if(navigation.resultVersionId)return {...shared,view:'bio-insight-result',resultVersionId:navigation.resultVersionId}
 return {...shared,view:'bulk-workflow',bulkView:'delivery',resultVersionId:selection.delivery.comparison_version_id}
}

export default function BioReaderReportWorkspace({projectId,navigation,deliveryTarget}:{
 projectId:string;navigation:AnalysisNavigation;deliveryTarget?:NativeDeliveryTarget
}){
 const {t}=useI18n()
 const fixed=useBioReportContext(projectId,navigation.reportContextId,true,context=>sourceMatches(context,navigation))
 const taskId=navigation.reportTaskId
 const task=useResearchRead<unknown>(taskId?`/api/v1/tasks/${encodeURIComponent(taskId)}/workspace`:'',!!fixed.data)
 const context=fixed.data
 if(fixed.error)return <p role="alert">{t(fixed.error)} <button type="button" onClick={fixed.refresh}>{t('重新读取')}</button></p>
 if(!context)return fixed.loading?<p role="status">{t(fixed.loadingMessage)}</p>:null
 let recovered
 if(taskId){
  if(task.error)return <p role="alert">{t(task.error)} <button type="button" onClick={task.refresh}>{t('重新读取')}</button></p>
  if(task.data===null)return <p role="status">{t(task.loadingMessage)}</p>
  if(!isWorkspace(task.data,projectId,taskId)||task.data.artifacts.bio_reader_report_context_id!==context.id
    ||task.data.task.input_version.kind!=='reader_report_narrative')return <p role="alert">{t(reportIdentityError)}</p>
  const input=task.data.task.input_version
  const report=task.data.artifacts.bio_reader_report_request
  if(!report||report.finding_version_id!==context.report.finding_version_id||report.language!==context.language)
   return <p role="alert">{t(reportIdentityError)}</p>
  recovered={id:input.narrative_id,taskId,binding:input.binding_sha256,bundle:input.bundle_sha256,fingerprint:JSON.stringify(report),report}
 }
 const source=serializeNavigation({...homeRoute(),workspaceView:'project',projectId,section:'analysis',analysisNavigation:reportSource(context,navigation)})
 return <section className="bio-workspace">
  <header className="bio-fixed-result-heading"><h2>{t('详细分析报告')}</h2>
   <a href={source}>{t('返回原分析选材')}</a>
  </header>
  <p>{t('报告语言')} · {t(context.language==='en'?'English':'简体中文')}</p>
  <FixedBioReaderReport key={projectId+':'+context.id+':'+(taskId??'')} {...{projectId,context,deliveryTarget,recovered}}
   location={navigation} standalone/>
 </section>
}
