import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {createArtifactSubmission,type ArtifactSubmission} from '../../shared/api/artifactSubmission'
import {RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {safeError,useI18n} from '../../shared/i18n'
import {intakeRequest,jsonRequest,projectBase} from '../research-intake/api'
import type {BulkDeliveryRequest} from '../bio-insights/bulkWorkflow'
import useResearchDraft from '../research-results/useResearchDraft'

export type NativeDeliveryTarget = {assignmentRevision:number;onDeliveries?:()=>void}

type FixedArtifact =
 | {kind:'single_cell_word';version_id:string;annotation_version_id?:string}
 | {kind:'single_cell_png'|'bio_figure_png'|'bio_insight_png';version_id:string;member_id:string}
type BulkWord = {prepareUrl:string;body:BulkDeliveryRequest & {facts_digest:string}}
type Source = FixedArtifact | BulkWord
type Props = {projectId:string;deliveryTarget?:NativeDeliveryTarget;source:Source;name:string}

export default function NativeDeliveryArtifact(props:Props) {
 const {projectId,deliveryTarget,source}=props
 if(!deliveryTarget)return null
 return <ArtifactAction key={JSON.stringify([projectId,deliveryTarget.assignmentRevision,source])} {...props} deliveryTarget={deliveryTarget}/>
}

function ArtifactAction({projectId,deliveryTarget,source,name}:Props&{deliveryTarget:NativeDeliveryTarget}) {
 const {t}=useI18n()
 const [state,setState]=useState({busy:false,filename:'',error:'',valid:true})
 const pending=useRef<AbortController|null>(null)
 const bulkWord='prepareUrl' in source
 const identity=bulkWord?`bulk_word:${source.body.facts_digest}`:JSON.stringify(source)
 const [savedSubmission,setSavedSubmission]=useResearchDraft<ArtifactSubmission|null>(projectId,`delivery-artifact:${deliveryTarget.assignmentRevision}:${identity}`,()=>null)
 const submission=useRef(savedSubmission)
 useEffect(()=>{
  const stop=onApiSessionChanged(()=>{
   pending.current?.abort()
   setState({busy:false,filename:'',error:'',valid:false})
  })
  return ()=>{pending.current?.abort();stop()}
 },[])

 async function add() {
  if(pending.current||!state.valid||state.filename)return
  const controller=new AbortController()
  const signal=controller.signal
  pending.current=controller
  setState({busy:true,filename:'',error:'',valid:true})
  try{
   if(!submission.current){
    let artifact:FixedArtifact|{kind:'bulk_word';artifact_id:string;facts_digest:string}
    if(bulkWord){
     const prepared=await intakeRequest<{artifact_id:string;facts_digest:string}>(
      source.prepareUrl,{...jsonRequest(source.body),signal},RESEARCH_REQUEST_TIMEOUT_MS)
     if(prepared?.facts_digest!==source.body.facts_digest||!/^[a-f0-9]{64}$/.test(prepared.artifact_id))
      throw new Error(t('固定来源身份不匹配，请重新打开。'))
     artifact={kind:'bulk_word',artifact_id:prepared.artifact_id,facts_digest:prepared.facts_digest}
    }else artifact=source
    if(signal.aborted)return
    submission.current=createArtifactSubmission({assignment_revision:deliveryTarget.assignmentRevision,...artifact})
    setSavedSubmission(submission.current)
   }
   const {key,body}=submission.current
   const value=await intakeRequest<{file_id:string;filename:string;format:string}>(
    `${projectBase(projectId)}/analyst-workspace/delivery-artifacts`,
    {method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body,signal},RESEARCH_REQUEST_TIMEOUT_MS)
   const format=bulkWord||source.kind==='single_cell_word'?'docx':'png'
   if(!value?.file_id||!value.filename||value.format!==format)throw new Error(t('交付候选响应格式不正确。'))
   if(!signal.aborted){
    submission.current=null
    setSavedSubmission(null)
    setState({busy:false,filename:name,error:'',valid:true})
   }
  } catch(cause) {
   if(!signal.aborted)setState({busy:false,filename:'',error:safeError(cause,'加入交付候选失败，请重试。'),valid:true})
  } finally {
   if(pending.current===controller)pending.current=null
  }
 }

 return <div className="native-delivery-action">
  {state.filename?<><span role="status">{t('已加入交付候选 · {name}',{name:state.filename})}</span>
   {deliveryTarget.onDeliveries&&<button type="button" onClick={deliveryTarget.onDeliveries}>{t('打开分析交付')}</button>}</>:
   <button type="button" disabled={state.busy||!state.valid} onClick={()=>void add()}>{t(state.busy?'正在加入交付候选……':'加入交付候选 · {name}',{name})}</button>}
  {state.error&&<p role="alert">{t(state.error)}</p>}
 </div>
}
