import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import RequirementReview from './RequirementReview'
import fixture from './batch09ConfirmedFixture.json'
import {setLocale} from '../../shared/i18n'
const value=()=>{const v=structuredClone(fixture) as any;v.task.input_version.workflow_version='analysis_plan_v5';v.input_version.workflow_version='analysis_plan_v5';v.task.status='waiting_input';v.task.display_status='waiting_input';v.task.reason_code='input_required';v.check={rules_version:'analysis_plan_rules_v5',research_missing:['source_confirmation'],data_check:null,limitations:[]};v.wait_id='source-wait';v.result=null;v.source_reference={status:'ambiguous',references:[],evidence:[]};v.source_resolution=null;v.source_mapping=[{code:'F1',level:'file',name:'synthetic.xlsx'},{code:'S1',level:'sheet',name:v.source.sheet_name},{code:'D1',level:'dataset',name:'v1'}];return v}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('sends a separate generation-bound source decision and never approves from that control',async()=>{
 const v=value();const fetch=vi.fn(async(url:string)=>url.endsWith('/source-decisions')?Response.json({...v.task,status:'queued',display_status:'queued',revision:v.task.revision+1,reason_code:'input_provided'}):Response.json(v));vi.stubGlobal('fetch',fetch)
 render(<RequirementReview projectId={v.task.project_id} taskId={v.task.id}/>)
 await screen.findByText('F1 ↔ synthetic.xlsx')
 expect(screen.queryByRole('button',{name:'确认并发布分析计划'})).toBeNull()
 const button=screen.getByRole('button',{name:'确认当前来源并重新检查'}) as HTMLButtonElement
 expect(button.disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('来源澄清说明'),{target:{value:'此问题指当前整理版本。'}})
 fireEvent.click(button)
 await waitFor(()=>expect(fetch.mock.calls.filter(([url])=>url.endsWith('/source-decisions'))).toHaveLength(1))
 const call=(fetch.mock.calls as unknown as [string,RequestInit][]).find(([url])=>url.endsWith('/source-decisions'))!
 const body=JSON.parse(String(call[1].body));expect(body).toEqual({expected_task_revision:v.task.revision,input_version:v.input_version,checkpoint_id:v.checkpoint_id,wait_id:'source-wait',plan_revision:v.plan_revision,source_resolution:{confirmed:true,note:'此问题指当前整理版本。'}})
 expect(fetch.mock.calls.some(([url])=>url.endsWith('/decisions'))).toBe(false)
})
it('shows English source labels and keeps local names and aliases visible without hashes',async()=>{
 setLocale('en');const v=value();vi.stubGlobal('fetch',vi.fn(async()=>Response.json(v)))
 render(<RequirementReview projectId={v.task.project_id} taskId={v.task.id}/>)
 await screen.findByText('Independent source confirmation')
 expect(screen.getByText('F1 ↔ synthetic.xlsx')).toBeTruthy()
 expect(screen.getByLabelText('Source clarification')).toBeTruthy()
 expect(screen.queryByText(v.source.source_sha256)).toBeNull()
})
