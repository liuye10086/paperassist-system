import {useRef} from 'react'
import {manuscriptBase} from './manuscriptTypes'
import {canonicalJson,listOf,requestUsesGroup,validAuthorization,validLiveRequest,wireDigest,type Authorization,type Bundle,type Grant,type LiveRequest} from './writingLiveTypes'
import type {useWritingOperation} from './useWritingOperation'

type Operation=ReturnType<typeof useWritingOperation>
export const materialsChanged='材料已变化，请重新预览本次写作材料。'
export const resultNotFound='还没有找到这次提交的记录。请稍后再查看提交结果；不会自动重新提交。'
export const authorizationsUrl=(projectId:string)=>`/api/v1/projects/${encodeURIComponent(projectId)}/writing-authorizations`
const singleBundle=(grant:Grant,bundle:Bundle)=>grant.bundles.length===1&&grant.bundles[0].bundle_id===bundle.id&&grant.bundles[0].bundle_sha256===bundle.bundle_sha256

// The exact SHA check runs here, on the client, before anything is sent (DESIGN 8.2).
export async function intactBundle(bundle:Bundle){
 try{return await wireDigest(bundle.wire_json)===bundle.bundle_sha256&&new TextEncoder().encode(bundle.wire_json).length===bundle.wire_bytes}catch{return false}
}

// One confirmation for customer writing (D5). The calls and bodies are the same as the internal step-by-step flow:
// an authorization bound to exactly [{bundle_id,bundle_sha256}] with confirmed:true, then the unchanged
// writing request. Both POSTs go through the scoped operation, so an unknown result survives a reload and blocks
// any further submission until the customer checks it.
export default function useCustomerWritingSubmit({op,projectId,manuscriptId,items,onRequest,onRefresh}:{op:Operation;projectId:string;manuscriptId:string;items:LiveRequest[];onRequest:(request:LiveRequest)=>void;onRefresh:()=>Promise<boolean>}){
 const running=useRef(false)
 const authUrl=authorizationsUrl(projectId),requestUrl=`${manuscriptBase(projectId)}/${encodeURIComponent(manuscriptId)}/writing-requests`
 const authorizations=listOf((v):v is Authorization=>validAuthorization(v,projectId))
 // An authorization already used for this preview is never reused: generating again always needs a new one. A queued
 // request can already identify its execution group before the first model call.
 const used=(auth:Authorization,bundle:Bundle,logical:string)=>items.some(item=>requestUsesGroup(item,{bundle_id:bundle.id,authorization_id:auth.id,logical_task_id:logical}))
 function reusable(list:Authorization[],bundle:Bundle){
  for(const auth of list){
   if(auth.status!=='active'||auth.occupied_posts>=auth.manifest.max_posts)continue
   const grant=auth.manifest.tasks.find(g=>singleBundle(g,bundle))
   if(grant&&!used(auth,bundle,grant.logical_task_id))return {auth,logical:grant.logical_task_id}
  }
  return null
 }
 async function submit(bundle:Bundle){
  if(running.current||op.busy||op.pending||!op.valid)return
  running.current=true
  try{
   if(!await intactBundle(bundle)){op.setError(materialsChanged);return}
   const list=await op.run(authUrl,authorizations)
   if(!list)return
   let chosen=reusable(list.items,bundle)
   if(!chosen){
    const created=await op.run(authUrl,(v):v is Authorization=>validAuthorization(v,projectId),{schema_version:2,confirmed:true,tasks:[{logical_task_id:'task-1',bundles:[{bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256}]}]},{freshAfterSuccess:true})
    if(!created)return
    const grant=created.manifest.tasks.find(g=>singleBundle(g,bundle))
    if(created.status!=='active'||!grant){op.setError(materialsChanged);return}
    chosen={auth:created,logical:grant.logical_task_id}
   }
   const result=await op.run(requestUrl,(v):v is LiveRequest=>validLiveRequest(v,projectId,manuscriptId),{schema_version:2,bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256,authorization_id:chosen.auth.id,logical_task_id:chosen.logical})
   if(result)onRequest(result)
  }finally{running.current=false}
 }
 // Reads what the server recorded. A writing request is never sent again from here. An authorization whose
 // exact manifest is not found is replayed once with its original idempotency key: it sends no materials and
 // costs nothing, and generating still needs a new click afterwards.
 async function checkResult(){
  const pending=op.pending
  if(!pending||op.busy||running.current)return
  running.current=true
  try{
   if(pending.url===authUrl){
    let sent:{tasks?:unknown}
    try{sent=JSON.parse(pending.body) as {tasks?:unknown}}catch{op.setError(resultNotFound);return}
    const list=await op.run(authUrl,authorizations)
    if(!list)return
    const found=list.items.some(auth=>auth.status==='active'&&canonicalJson(auth.manifest.tasks)===canonicalJson(sent.tasks)&&!auth.manifest.tasks.some(g=>items.some(item=>[item.execution,...item.model_calls].some(call=>call?.authorization_id===auth.id&&call.logical_task_id===g.logical_task_id))))
    if(found)op.resolvePending()
    else await op.run(authUrl,(v):v is Authorization=>validAuthorization(v,projectId),sent,{freshAfterSuccess:true})
    return
   }
   if(pending.url===requestUrl&&!await onRefresh())op.setError(resultNotFound)
  }finally{running.current=false}
 }
 return {submit,checkResult}
}
