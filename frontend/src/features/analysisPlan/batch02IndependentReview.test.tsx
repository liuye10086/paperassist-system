import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisRecommendation from './AnalysisRecommendation'
import AnalysisPlanLauncher from './AnalysisPlanLauncher'
import { reviewFixture } from './analysisPlanFixtures'
import type { PreparedDatasetAnalysisSource } from '../analysis/datasetSource'
import type { Selection } from '../analysis/AnalysisSetup'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const source=reviewFixture.source as PreparedDatasetAnalysisSource
const input={...reviewFixture.input_version,kind:'analysis_recommendation',workflow_version:'analysis_recommendation_v1'}
const oldSelection={...reviewFixture.selection,unit:'kg'} as Selection
const task=(id:string,status:string,reason_code:string|null=null)=>({...reviewFixture.task,id,task_type:'analysis_recommendation',status,display_status:status,reason_code,input_version:input})
const projection={file_id:'f1',filename:'synthetic.xlsx',analysis_run_id:null,is_current:true,dataset_source:source}
const fields=[{column:'C',name:'weight',unit:'kg',numeric:true},{column:'D',name:'height',unit:'cm',numeric:true}]
function savedReview(id:string,status:string,reason_code:string|null=null) {
 const t=task(id,status,reason_code)
 return {task:t,source,input_version:input,request:{dataset_id:source.dataset_id,sheet_name:source.sheet_name,candidate_columns:['C','D'],output_language:'zh-CN',research_summary:''},external_processing:{version:1,provider:'openai',task_type:'analysis_recommendation',source_digest:'digest',labels:{'field:C':'weight','field:D':'height',research_summary:''},confirmed_by:'user',confirmed_at:t.created_at,confirmation_digest:'d'.repeat(64)},recommendation:status==='succeeded'?{schema_version:1,task_id:id,sha256:'c'.repeat(64),method:'descriptive',mode:null,columns:['D'],output_language:'zh-CN',rationale:['Use height'],assumptions:[],missing_information:[],model_call_id:'call'}:null}
}
function listFetch(url:string) {
 if(url.includes('/tasks?')) return Response.json({project_id:'p1',items:['new','old'].map(id=>({task:task(id,id==='new'?'waiting_confirmation':'succeeded',id==='new'?'submission_unknown':null),source:projection})),total:2,page:1,page_size:10})
 const id=url.includes('/new/')?'new':'old';const r=savedReview(id,id==='new'?'waiting_confirmation':'succeeded',id==='new'?'submission_unknown':null)
 if(url.endsWith('/workspace')) return Response.json({task:r.task,source:projection,wait:id==='new'?{id:'w-new',kind:'submission_unknown',status:'open',task_revision:r.task.revision,input_version:input,reason_code:'submission_unknown',error_code:null,created_at:r.task.created_at,resolved_at:null}:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}})
 if(url.endsWith('/analysis-recommendation')) return Response.json(r)
 return Response.json({items:[],total:0,page:1,page_size:5})
}
test('review: adopting a descriptive field uses that field unit rather than old numeric unit',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>listFetch(url)))
 const adopted=vi.fn();render(<AnalysisRecommendation projectId="p1" fileId="f1" source={source} descriptiveSelection={oldSelection} fields={fields} language="zh-CN" disabled={false} onAdopt={adopted}/>)
 const user=userEvent.setup();await user.click(screen.getByRole('button',{name:'读取已保存建议'}));await user.click(await screen.findByRole('button',{name:'建议 2 · 已完成'}));await user.click(await screen.findByRole('button',{name:'采纳为候选计划，仍需独立确认'}))
 expect(adopted.mock.calls[0][0]).toMatchObject({numeric_column:'D',unit:'cm'})
})
test('review: main descriptive edits after adoption are reflected in the create request',async()=>{
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{if(url.endsWith('/analysis-plans')&&init?.method==='POST') return Response.json(null,{status:422});return listFetch(url)});vi.stubGlobal('fetch',fetch)
 const props={projectId:'p1',fileId:'f1',source,selection:oldSelection,fields,setupRevision:0,disabled:false,onPublished:()=>{}}
 const view=render(<AnalysisPlanLauncher {...props}/>)
 const user=userEvent.setup();await user.click(screen.getByRole('button',{name:'读取已保存建议'}));await user.click(await screen.findByRole('button',{name:'建议 2 · 已完成'}));await user.click(await screen.findByRole('button',{name:'采纳为候选计划，仍需独立确认'}));await user.type(screen.getByLabelText('研究问题'),'Height description')
 view.rerender(<AnalysisPlanLauncher {...props} selection={{...oldSelection,numeric_column:'D',unit:'cm'}}/>);await user.click(screen.getByRole('button',{name:'生成分析计划'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([url,init])=>url.endsWith('/analysis-plans')&&init?.method==='POST')).toBe(true))
 const post=fetch.mock.calls.find(([url,init])=>url.endsWith('/analysis-plans')&&init?.method==='POST')!
 expect(JSON.parse(String(post[1]?.body)).selection).toMatchObject({numeric_column:'D',unit:'cm'})
})
test('review: selecting completed history does not clear another unknown recommendation guard',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>listFetch(url)))
 render(<AnalysisRecommendation projectId="p1" fileId="f1" source={source} descriptiveSelection={oldSelection} fields={fields} language="zh-CN" disabled={false} onAdopt={()=>{}}/>)
 const user=userEvent.setup();await user.click(screen.getByLabelText('候选字段 C · weight'));await user.click(screen.getByRole('button',{name:'读取已保存建议'}));await user.click(await screen.findByRole('button',{name:'建议 1 · 待用户确认'}));await waitFor(()=>expect((screen.getByRole('button',{name:'预览受限模型建议资料'}) as HTMLButtonElement).disabled).toBe(true))
 await user.click(screen.getByRole('button',{name:'建议 2 · 已完成'}));await screen.findByRole('button',{name:'采纳为候选计划，仍需独立确认'})
 expect((screen.getByRole('button',{name:'预览受限模型建议资料'}) as HTMLButtonElement).disabled).toBe(true)
})
