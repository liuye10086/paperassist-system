import {expect,it,vi} from 'vitest'
import {emptyInput,type Manuscript,type SourceCandidate} from './manuscriptTypes'
import {manuscriptFixture} from './manuscriptFixtures'
import {preparePaperDraft, defaultPaperFiles} from './preparePaperDraft'
import {taskFixture, workspaceFixture} from '../tasks/taskFixtures'

const original=manuscriptFixture as unknown as Manuscript
const base=emptyInput('Paper','en')
const chosen=[{project_reference_id:'ref1',search_id:'search1',quote:'Observed in the saved abstract.'}]
it('resumes the frozen preparation task without writing new selections or another manuscript version',async()=>{
 const version={...original.versions[0],status:'failed',current_changes:[]}
 const task={...taskFixture,id:version.task_id,task_type:'manuscript_draft',status:'failed',display_status:'failed',phase:'write',
  input_version:{kind:'manuscript',manuscript_version_id:version.id,output_language:'en',workflow_version:'manuscript_fact_draft_v1'}}
 let resumed=false
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/workspace'))return Response.json({...workspaceFixture,task,source:{file_id:null,filename:'Paper',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry']})
  if(url.endsWith('/resume')&&init?.method==='POST'){resumed=true;return Response.json({...task,status:'queued',display_status:'queued'})}
  if(url.endsWith('/manuscripts/m1')&&!init?.method)return Response.json({...original,versions:[{...version,status:resumed?'published':'failed'}]})
  throw Error('Unexpected request')
 })
 vi.stubGlobal('fetch',fetcher)
 try{
  const result=await preparePaperDraft({projectId:'p1',manuscriptId:'m1',existingRevision:1,input:base,references:chosen,attemptKey:'same-version',signal:new AbortController().signal})
  expect(result.version.id).toBe(version.id)
  expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST').map(([url])=>url)).toEqual(['/api/v1/tasks/'+task.id+'/resume'])
 }finally{vi.unstubAllGlobals()}
})
it('uses the verified reference draft and the original version returned by a replay',async()=>{
 const prepared={...original,current_revision:2,versions:[...original.versions,{...original.versions[0],id:'v2',revision:2,exports:[]}]}
 const calls:{url:string;body:unknown;key:string|null}[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init:RequestInit)=>{
  calls.push({url,body:JSON.parse(String(init.body)),key:new Headers(init.headers).get('Idempotency-Key')})
  return Response.json(url.endsWith('/selected-references')?{id:'citation1',revision:1}:prepared)
 }))
 try{
  const result=await preparePaperDraft({projectId:'p1',attemptKey:'attempt',manuscriptId:'m1',input:{...base,expected_revision:1},references:chosen,signal:new AbortController().signal})
  expect(result.version.id).toBe('v2')
  expect(calls[0].body).toEqual({references:chosen,output_language:'en'})
  expect(calls[1].body).toMatchObject({expected_revision:1,citation_draft:{id:'citation1',revision:1}})
  expect(calls[0].key).not.toBe(calls[1].key)
 }finally{vi.unstubAllGlobals()}
})
it('chooses the reviewed or parsed copy of an upload once, skipping the school template and linked materials',()=>{
 const file=(kind:string,id:string,file_id:string,version:number|null=null)=>({kind,id,file_id,version,label:id,allowed_roles:['methods'],download_url:null}) as SourceCandidate
 const options=defaultPaperFiles([file('original','f','f'),file('document_version','p1','f',1),file('document_version','p2','f',2),file('original','t','t'),file('original','plan','plan')],new Set(['t','plan']))
 expect(options.map(o=>o.id)).toEqual(['p2'])
})
