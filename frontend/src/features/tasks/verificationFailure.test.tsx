import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import TaskDetail from './TaskDetail'
import {workspaceFixture,eventsFixture,usageFixture} from './taskFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
test('shows durable numeric mismatch while keeping receipt identifiers private',async()=>{
 const workspace={...workspaceFixture,task:{...workspaceFixture.task,status:'failed',display_status:'failed',error_code:'plot_result_mismatch'},wait:null,allowed_actions:[],verification_failure:{schema_version:1,status:'mismatched',recorded_at:'2026-10-14T00:00:00Z',differences:[{path:'$.statistics.coefficient',expected:0.8,actual:0.7,reason:'numeric mismatch'}],manifest:{},provenance:{response_id:'private-response',model_input_digest:'private-digest'}}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?workspace:url.includes('/events')?eventsFixture:usageFixture)))
 render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}}/>)
 expect(await screen.findByRole('table',{name:'图表数值核对差异'})).toBeTruthy()
 expect(screen.getByText('0.8')).toBeTruthy()
 expect(document.body.textContent).not.toContain('private-response')
 expect(document.body.textContent).not.toContain('private-digest')
})
