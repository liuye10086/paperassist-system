import {useEffect,useState} from 'react'
import {basePath,literatureRequest,validPage,validReference,type Page,type Reference} from '../literature/literatureApi'
import {citationBase,citationPage,validCandidate,type Candidate} from '../literature/citationApi'

/** A shortlisted project reference with a usable bibliography and saved abstract text (B03 task 7). */
export type ProjectEvidenceOption={project_reference_id:string;title:string;search_id:string;metadata_version_id:string;texts:string[]}

const maxPages=10
async function readAll<T>(url:(page:number)=>string,guard:(page:number)=>(v:unknown)=>v is Page<T>,controller:AbortController){
 const items:T[]=[]
 for(let page=1;page<=maxPages;page++){
  const result=await literatureRequest(url(page),controller,guard(page))
  items.push(...result.items)
  if(page*result.page_size>=result.total)break
 }
 return items
}

/** Project literature a customer may cite although it was added after the writing materials were frozen. */
export function projectEvidenceOptions(references:Reference[],candidates:Candidate[]):ProjectEvidenceOption[]{
 const usable=new Map(candidates.filter(c=>c.metadata?.usable===true).map(c=>[c.id,c.metadata!.id]))
 return references.flatMap(r=>{
  const metadata=usable.get(r.id),texts=r.record.abstract_status==='available'?r.record.abstract.map(a=>a.text).filter(text=>!!text.trim()):[]
  return r.selection.status==='shortlisted'&&metadata&&texts.length?[{project_reference_id:r.id,title:r.record.title||r.pmid,search_id:r.source.search_id,metadata_version_id:metadata,texts}]:[]
 })
}

/** Reads the options once per project; `null` while unread or when either list cannot be read. */
export function useProjectEvidenceOptions(projectId:string,enabled:boolean){
 const [state,setState]=useState<{key:string;options:ProjectEvidenceOption[]|null}>({key:'',options:null})
 const key=enabled?projectId:''
 useEffect(()=>{
  if(!key)return
  const controller=new AbortController()
  void Promise.all([
   readAll<Reference>(page=>`${basePath(projectId)}/references?selection=shortlisted&page=${page}`,page=>(v):v is Page<Reference>=>validPage(v,projectId,page,x=>validReference(x,projectId)),controller),
   readAll<Candidate>(page=>`${citationBase(projectId)}/candidates?page=${page}`,page=>citationPage(projectId,page,validCandidate),controller),
  ]).then(([references,candidates])=>{if(!controller.signal.aborted)setState({key,options:projectEvidenceOptions(references,candidates)})},()=>{})
  return()=>controller.abort()
 },[key,projectId])
 return state.key===key&&key?state.options:null
}
