import {expect,it,vi} from 'vitest'
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import TaskPendingAction from './TaskPendingAction'
import {isWorkspace} from './taskTypes'
import {runFixture} from '../bioinformatics/spatialFixtures'
const task={...runFixture.task,status:'running',display_status:'computing',input_version:{...runFixture.task.input_version,workflow_version:'bio_analysis_v3'}}
const workspace={task,source:{file_id:null,filename:'Local analysis',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['cancel'],artifacts:{figure:null,explanation:null,report:null}}
it('accepts cancel only for running or queued local bio tasks',()=>{
 expect(isWorkspace(workspace,'p1',task.id)).toBe(true)
 expect(isWorkspace({...workspace,task:{...task,status:'cancelled',display_status:'cancelled'}},'p1',task.id)).toBe(false)
})
it('sends versioned cancel to the real cancellation endpoint',async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({...task,status:'cancelled',display_status:'cancelled',revision:(task.revision??1)+1}),{status:200}))
 vi.stubGlobal('fetch',fetch)
 const changed=vi.fn()
 render(<TaskPendingAction workspace={workspace as never} blocked={false} onChanged={changed}/> )
 fireEvent.click(screen.getByRole('button',{name:'取消任务'}))
 await waitFor(()=>expect(changed).toHaveBeenCalled())
 expect(fetch.mock.calls[0][0]).toContain(`/tasks/${task.id}/cancel`)
 expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({expected_revision:task.revision})
 cleanup();vi.unstubAllGlobals()
})
