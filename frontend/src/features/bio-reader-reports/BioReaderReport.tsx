import {useLayoutEffect,useState,type ReactNode} from 'react'
import {translateForLocale,useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import type {NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import {projectBase,RESEARCH_LOADING_MESSAGE,RESEARCH_TIMEOUT_MS,useResearchRead} from '../research-results/api'
import type {Page,Report} from '../research-results/contracts'
import {NarrativePreparation} from '../research-results/ResearchReportNarrative'
import {Members,OperationStatus,Paging,TaskStatus} from '../research-results/ResearchShared'
import useResearchCompletion from '../research-results/useResearchCompletion'
import useResearchDraft from '../research-results/useResearchDraft'
import useResearchOperation from '../research-results/useResearchOperation'
import {useReportNarrative,type NarrativeBinding} from '../research-results/useReportNarrative'
import {bioReportLink,bioReportTaskLink,type ReportLocation} from './navigation'
import {
 bioReportsBase,matchesRequest,reportIdentityError,validContext,type BioReportContext,type BioReportExport,
 type BioReportRequest,type BulkSelection,type FigureChoice,type NativeSelection,type ReportLanguage,
} from './contracts'

type Common={projectId:string;active?:boolean;title:string;location?:ReportLocation;deliveryTarget?:NativeDeliveryTarget}
type Props=Common&{
 selection:NativeSelection|BulkSelection
 figures?:FigureChoice[]
 initialLanguage?:ReportLanguage
 restored?:BioReportContext
 figureLimit?:number
 renderSelection?:(ids:string[])=>ReactNode
 onPrepareBlocked?:(blocked:boolean)=>void
 fixedEditing?:boolean
}
type Draft={language:ReportLanguage;figureIds:string[];prepared:{id:string;signature:string}|null}

function sourceScope(selection:Props['selection']){
 switch(selection.kind){
  case 'processed':return `processed:${selection.processed_version_id}:${selection.annotation_version_id??'base'}`
  case 'insight':return `insight:${selection.result_version_id}`
  case 'bulk':return `bulk:${selection.delivery.comparison_version_id}:${selection.delivery.facts_digest}`
 }
}

export default function BioReaderReport(props:Props) {
 if(props.active===false)return null
 const scope=`bio-reader:${sourceScope(props.selection)}${props.restored?':'+props.restored.id:''}`
 return <SelectionPanel key={props.projectId+':'+scope} {...props} scope={scope}/>
}

export function ReportSelectionToggle({editing,onToggle}:{editing:boolean;onToggle:()=>void}){
 const {t}=useI18n()
 return <button type="button" onClick={onToggle}>{t(editing?'查看固定报告选材':'编辑报告选材草稿')}</button>
}

function SelectionPanel({projectId,active=true,title,selection,figures=[],initialLanguage,restored,scope,location,deliveryTarget,
 figureLimit=50,renderSelection,onPrepareBlocked,fixedEditing}:Props&{scope:string}){
 const {t,locale}=useI18n()
 const bulk=selection.kind==='bulk'
 const [editing,setEditing]=useState(false)
 const editSelection=fixedEditing??editing
 const showFixed=!!restored&&!editSelection
 function initialDraft():Draft{
  const language=restored?.language??initialLanguage??locale
  const source=restored?.selection
  const figureIds=source?.kind==='bulk'
   ?selection.kind==='insight'?source.delivery.result_version_ids.slice(source.delivery.comparison_version_id===selection.result_version_id?0:1):[]
   :source?.figure_version_ids??[]
  return {language,figureIds,prepared:null}
 }
 const [savedDraft,saveDraft]=useResearchDraft<Draft>(projectId,scope,initialDraft)
 const draft=showFixed?initialDraft():savedDraft
 const language=bulk?(selection.delivery.language==='en'?'en':'zh-CN'):draft.language
 const body:BioReportRequest={
  title:translateForLocale(title,language),language,
  selection:bulk?selection:{...selection,figure_version_ids:draft.figureIds},
 }
 const signature=JSON.stringify(body)
 const prepare=useResearchOperation<BioReportContext>(projectId,'bio_report_context',scope,{
  onResolved:result=>{
   if(!validContext(result as BioReportContext))return
   const context=result as BioReportContext
   if(matchesRequest(context,body))saveDraft(old=>({...old,prepared:{id:context.id,signature}}))
  },
 })
 const last=prepare.value&&validContext(prepare.value)&&matchesRequest(prepare.value,body)?prepare.value:null
 const restoredContext=restored&&matchesRequest(restored,{...body,title:restored.title})?restored:null
 const savedId=draft.prepared?.signature===signature?draft.prepared.id:''
 const read=useResearchRead<BioReportContext>(!showFixed&&!last&&!restoredContext&&savedId?`${bioReportsBase(projectId)}/${encodeURIComponent(savedId)}`:'',active)
 const saved=validContext(read.data,savedId)&&matchesRequest(read.data,body)?read.data:null
 const context=showFixed?restored:last??restoredContext??saved
 const locked=prepare.busy||prepare.unknown||!prepare.valid
 useLayoutEffect(()=>{
  onPrepareBlocked?.(locked)
  return ()=>onPrepareBlocked?.(false)
 },[onPrepareBlocked,locked])
 const byId=new Map(figures.map(figure=>[figure.id,figure.title]))
 const missing=draft.figureIds.some(id=>!byId.has(id))

 function setFigures(ids:string[]){
  prepare.clear()
  saveDraft(old=>({...old,figureIds:ids}))
 }
 function move(index:number,direction:-1|1){
  const ids=[...draft.figureIds]
  ;[ids[index],ids[index+direction]]=[ids[index+direction],ids[index]]
  setFigures(ids)
 }
 return <section className="research-detail-block" aria-label={t('详细分析报告')}>
  <h3>{t('详细分析报告')}</h3>
  {restored&&fixedEditing===undefined&&<ReportSelectionToggle editing={editSelection} onToggle={()=>setEditing(value=>!value)}/>}
  <fieldset disabled={!active||locked||showFixed}>
   {!bulk&&<>
    <label>{t('报告语言')} <select value={draft.language} onChange={event=>{
     prepare.clear()
     saveDraft(old=>({...old,language:event.target.value as ReportLanguage}))
    }}><option value="zh-CN">{t('简体中文')}</option><option value="en">English</option></select></label>
    <fieldset><legend>{t('报告图件')}</legend>
     {draft.figureIds.length?<p>{t('使用所选重绘图')}{' '}
      <button type="button" onClick={()=>setFigures([])}>{t('使用原结果图件')}</button>
     </p>:<p>{t('使用原结果图件')}</p>}
     {figures.map(figure=><label key={figure.id} className="intake-check">
      <input type="checkbox" checked={draft.figureIds.includes(figure.id)}
       disabled={!draft.figureIds.includes(figure.id)&&draft.figureIds.length>=figureLimit}
       onChange={event=>setFigures(event.target.checked?[...draft.figureIds,figure.id]:draft.figureIds.filter(id=>id!==figure.id))}/>
      {figure.title}
     </label>)}
     {!!draft.figureIds.length&&<ol>{draft.figureIds.map((id,index)=><li key={id}>
      {byId.get(id)??t('选定图件当前不可用')}{' '}
      <button type="button" disabled={!index} onClick={()=>move(index,-1)}>{t('上移')}</button>{' '}
      <button type="button" disabled={index===draft.figureIds.length-1} onClick={()=>move(index,1)}>{t('下移')}</button>{' '}
      <button type="button" onClick={()=>setFigures(draft.figureIds.filter(value=>value!==id))}>{t('移除')}</button>
     </li>)}</ol>}
    </fieldset>
   </>}
   {!context&&<button type="button" className="button-primary" disabled={missing||read.loading}
    onClick={()=>void prepare.submit(bioReportsBase(projectId)+'/prepare',body)}>{t('准备详细报告')}</button>}
  </fieldset>
  {!showFixed&&<>
   <OperationStatus operation={prepare}/>
   {prepare.busy&&<button type="button" onClick={prepare.cancelWaiting}>{t('取消等待')}</button>}
   {read.loading&&<p role="status">{t(RESEARCH_LOADING_MESSAGE)}</p>}
   {read.error&&<p role="alert">{t(read.error)} <button type="button" onClick={read.refresh}>{t('重新读取')}</button></p>}
   {(prepare.value&&!last||read.data&&!saved)&&<p role="alert">{t(reportIdentityError)}</p>}
  </>}
  {context&&<FixedBioReaderReport key={context.id} {...{projectId,context,active,location,deliveryTarget}}/>}
  {renderSelection?.(draft.figureIds.filter(id=>byId.has(id)))}
 </section>
}

export function FixedBioReaderReport({projectId,context,active=true,location,deliveryTarget,recovered,standalone=false}:{
 projectId:string;context:BioReportContext;active?:boolean;location?:ReportLocation;deliveryTarget?:NativeDeliveryTarget;
 recovered?:NarrativeBinding;standalone?:boolean
}){
 const {t,locale}=useI18n(),[page,setPage]=useState(1)
 const base=projectBase(projectId)
 const contextUrl=`${bioReportsBase(projectId)}/${encodeURIComponent(context.id)}`
 const history=useResearchRead<Page<BioReportExport>>(`${contextUrl}/reports?page=${page}`,active,
  value=>value.items.some(item=>['queued','running'].includes(item.task.status)))
 const scope='bio-reader:'+context.id
 const [binding,saveBinding]=useResearchDraft<NarrativeBinding|undefined>(projectId,scope+':narrative',()=>undefined)
 const [changedRecovered,setChangedRecovered]=useState(false)
 const report=context.report
 const operation=useResearchOperation<Report>(projectId,'report',scope)
 const preparation=useReportNarrative(projectId,scope,active,report,(!changedRecovered&&recovered)||binding,update=>{
  saveBinding(update)
  setChangedRecovered(true)
 })
 useResearchCompletion(operation.value?.id??operation.found?.id,history.refresh)
 const valid=(item:BioReportExport)=>item.task?.project_id===projectId&&item.task.id===item.task_id&&item.task.task_type==='research_report'
 const items=history.data?.items.filter(valid)??[]
 const canGenerate=active&&history.valid&&!history.error&&history.data?.total===0&&!operation.busy&&!operation.unknown&&operation.valid
 const hasReport=!!history.data?.total||!!operation.value||!!operation.found
 const reportReturn=bioReportLink(projectId,context.id,location)
 const taskLink=(id:string)=>bioReportTaskLink(projectId,id,reportReturn)
 const navigateReport=(id:string)=>'#'+new URLSearchParams({project:projectId,section:'artifacts',view:'research-reports',artifact:id,
  reportReturn})
 return <section className="research-detail-block" aria-label={t('已固定的报告选材')}>
  <h4>{context.title}</h4>
  {!standalone&&<a href={bioReportLink(projectId,context.id,location)}>{t('打开固定报告选材')}</a>}
  {history.error&&<p role="alert">{t(history.error)}</p>}
  {history.loading&&<p role="status">{t(RESEARCH_LOADING_MESSAGE)}</p>}
  <button type="button" disabled={history.loading||!history.valid} onClick={history.refresh}>{t('刷新报告版本')}</button>
  {history.data&&history.data.items.length!==items.length&&<p role="alert">{t(reportIdentityError)}</p>}
  {items.map(item=>{
   const prefix=`${contextUrl}/reports/${encodeURIComponent(item.id)}`
   const members=item.task.status==='succeeded'?item.members.filter(member=>
    ['docx','xlsx','zip'].includes(member.role)&&member.format===member.role&&member.download_url===`${prefix}/members/${member.role}/download`):[]
   return <article key={item.id} className="bio-result-block">
    {item.task.updated_at&&<time dateTime={item.task.updated_at}>{new Date(item.task.updated_at).toLocaleString(locale)}</time>}
    <TaskStatus {...{projectId}} task={item.task} href={taskLink(item.task_id)}/>
    <a href={navigateReport(item.id)}>{t('打开正式报告')}</a>
    {!!members.length&&<Members items={members} title={context.title} showDetails={false} zipLabel="报告复现成果包"/>}
    {members.length!==item.members.length&&<p role="alert">{t(reportIdentityError)}</p>}
    {context.selection.kind==='bulk'&&members.some(member=>member.role==='docx')&&members.some(member=>member.role==='xlsx')&&
     <ProjectDownloadLink nativePrepared href={prefix+'/bulk-reproduction/prepare'}
      preparedFactsDigest={context.selection.delivery.facts_digest} filename={t('Bulk 完整分析复现资料')+'.zip'} timeoutMs={RESEARCH_TIMEOUT_MS}>
      {t('下载 Bulk 完整分析复现包')}
     </ProjectDownloadLink>}
    {deliveryTarget?.onDeliveries&&members.some(member=>member.role==='docx'||member.role==='xlsx')&&<p>
     {t('固定 Word 和 Excel 可在分析交付中选用。')}{' '}
     <button type="button" onClick={deliveryTarget.onDeliveries}>{t('打开分析交付')}</button>
    </p>}
   </article>
  })}
  {history.data&&<Paging page={page} total={history.data.total} size={history.data.page_size} onPage={setPage}/>}
  {!hasReport&&<>
   <NarrativePreparation projectId={projectId} enabled={canGenerate} preparation={preparation} taskLink={taskLink}/>
   <button type="button" className="button-primary" disabled={!canGenerate||preparation.blocking||!preparation.ready}
    onClick={()=>{if(canGenerate&&preparation.ready&&!preparation.blocking)
     void operation.submit(base+'/research-reports',{...report,reader_narrative_id:preparation.ready.id})}}>
    {t('生成固定报告与成果包')}
   </button>
  </>}
  <OperationStatus operation={operation}/>
  {operation.busy&&<button type="button" onClick={operation.cancelWaiting}>{t('取消等待')}</button>}
 </section>
}
