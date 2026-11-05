import {useEffect,useRef} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import useResearchDraft from '../research-results/useResearchDraft'

export type ManuscriptRequestScope={projectId:string;manuscriptId:string;versionId:string;operation:string}
export type PendingManuscriptRequest={key:string;url:string;body:string;phase:'sending'|'unknown'}
export default function useManuscriptPendingRequest(scope?:ManuscriptRequestScope){
 const [saved,setSaved]=useResearchDraft<PendingManuscriptRequest|null>(scope?.projectId??'',`manuscript-request:${scope?.manuscriptId??''}:${scope?.versionId??''}:${scope?.operation??''}`,()=>null)
 const pending=useRef<PendingManuscriptRequest|null>(scope&&saved?{...saved,phase:'unknown'}:null),valid=useRef(true)
 useEffect(()=>onApiSessionChanged(()=>{valid.current=false;pending.current=null}),[])
 function save(value:PendingManuscriptRequest|null){pending.current=value;if(scope)setSaved(value)}
 function begin(url:string,body:unknown,key?:string){
  if(!valid.current)return null
  const serialized=JSON.stringify(body),old=pending.current
  if(old&&(old.url!==url||old.body!==serialized))return null
  const next:PendingManuscriptRequest={key:old?.key??key??crypto.randomUUID(),url,body:old?.body??serialized,phase:'sending'}
  save(next);return next
 }
 return{pending:pending.current,begin,unknown:()=>{if(pending.current)save({...pending.current,phase:'unknown'})},complete:()=>save(null)}
}
