import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {clearApiSession,setApiSession} from '../../shared/api/client'
import {taskFixture,workspaceFixture} from '../tasks/taskFixtures'
import type {ReportNarrative} from '../research-results/contracts'
import BioReaderReportWorkspace from './BioReaderReportWorkspace'
import {fixedContext,fixedSha} from './testFixtures'

const projectId='p1',taskId='task1',narrativeId='narrative1'
const base='/api/v1/projects/p1'
const contextUrl=base+'/bio-reader-reports/context1'
const narrativeUrl=base+'/research-report-narratives/'+narrativeId
const context=fixedContext({title:'Native title',language:'en',
 selection:{kind:'processed',processed_version_id:'data1',annotation_version_id:null,figure_version_ids:['nativeFigure']}})
const report={...context.report,title:'Customized report title'}
const task={...taskFixture,id:taskId,task_type:'reader_report_narrative',status:'succeeded',display_status:'succeeded',
 phase:'interpret',reason_code:null,error_code:null,input_version:{kind:'reader_report_narrative',workflow_version:'reader_report_narrative_v1',
  narrative_id:narrativeId,binding_sha256:'b'.repeat(64),bundle_sha256:fixedSha}}
const workspace={...workspaceFixture,task,wait:null,allowed_actions:[],
 source:{file_id:null,filename:report.title,analysis_run_id:null,is_current:true},
 artifacts:{...workspaceFixture.artifacts,bio_reader_report_context_id:context.id,bio_reader_report_request:report}}
const result:ReportNarrative={narrative:{abstract:'Saved customized interpretation',design_and_data:'Design',quality_control:'Quality',
 methods_summary:'Methods',key_findings:'Findings',limitations:'Limitations',reader_cautions:'Cautions'},figures:[]}
const status={id:narrativeId,task,binding_sha256:task.input_version.binding_sha256,bundle_sha256:fixedSha,artifact_sha256:fixedSha,result}

beforeEach(()=>{setApiSession('csrf','account');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession();sessionStorage.clear()})

function mount(frozen:unknown=workspace,saved:unknown=status,expectedExport=report,exportPath='/research-reports'){
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===contextUrl)return Response.json(context)
  if(url===`/api/v1/tasks/${taskId}/workspace`)return Response.json(frozen)
  if(url===contextUrl+'/reports?page=1')return Response.json({items:[],total:0,page:1,page_size:20,export_state:'available'})
  if(url===narrativeUrl)return Response.json(saved)
  if(url===base+exportPath&&init?.method==='POST'){
   const submitted=JSON.parse(String(init.body))
   const matches=Object.entries({...expectedExport,reader_narrative_id:narrativeId}).every(([key,value])=>
    JSON.stringify(submitted[key])===JSON.stringify(value))
   return matches?Response.json({id:'formal1'}):Response.json({detail:{code:'research_source_conflict'}},{status:409})
  }
  return Response.json({}, {status:404})
 })
 vi.stubGlobal('fetch',fetch)
 render(<BioReaderReportWorkspace projectId={projectId} navigation={{view:'bio-reader-report',fileId:'',
  reportContextId:context.id,reportTaskId:taskId,processedId:'data1'}}/>)
 return fetch
}

it.each([null,'old-root'])('exports the exact recovered report and saved interpretation (root %s)',async(root_id)=>{
 const expected={...report,root_id,expected_revision:root_id?2:0}
 const path=root_id?'/research-reports/'+root_id+'/versions':'/research-reports'
 const fetch=mount({...workspace,artifacts:{...workspace.artifacts,bio_reader_report_request:expected}},status,expected,path)
 await screen.findByText('Saved customized interpretation')
 fireEvent.click(screen.getByRole('button',{name:'生成固定报告与成果包'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([url,init])=>url===base+path&&init?.method==='POST')).toBe(true))
 const posts=fetch.mock.calls.filter(([,init])=>init?.method==='POST')
 expect(posts.map(([url])=>url)).toEqual([base+path])
 expect(JSON.parse(String(posts[0][1]?.body))).toEqual({...expected,reader_narrative_id:narrativeId})
 expect(screen.getByRole('heading',{name:report.title})).toBeTruthy()
})

it.each([
 {finding_version_id:'unrelated'},
 {language:'zh-CN'},
 {figure_version_ids:['unrelated']},
 {reader_narrative_id:'other-narrative'},
])('refuses a report projection outside the fixed selection (%j)',async(patch)=>{
 const fetch=mount({...workspace,artifacts:{...workspace.artifacts,bio_reader_report_request:{...report,...patch}}})
 expect((await screen.findByRole('alert')).textContent).toContain('固定来源身份不匹配')
 expect(fetch.mock.calls.some(([url])=>url===narrativeUrl)).toBe(false)
})

it.each([{id:'other-task'},{project_id:'other-project'}])('rejects a workspace outside the requested task and project (%j)',async(patch)=>{
 const fetch=mount({...workspace,task:{...task,...patch}})
 expect((await screen.findByRole('alert')).textContent).toContain('固定来源身份不匹配')
 expect(fetch.mock.calls.some(([url])=>url===narrativeUrl)).toBe(false)
})

it('rejects a matching narrative id and digests from a different task',async()=>{
 const fetch=mount(workspace,{...status,task:{...task,id:'unrelated'}})
 await waitFor(()=>expect(screen.getByText('详细解读与当前报告内容不一致。')).toBeTruthy())
 expect(screen.getByRole('button',{name:'生成固定报告与成果包'})).toHaveProperty('disabled',true)
 expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
})
