import {StrictMode} from 'react'
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import StatisticsTaskRecovery from './StatisticsTaskRecovery'
import {isWorkspace,type TaskWorkspace} from '../tasks/taskTypes'
import {workspaceFixture} from '../tasks/taskFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it.each([true,false])('refreshes and releases busy after StrictMode retry success=%s',async success=>{
 let finish!:(response:Response)=>void
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>{finish=resolve})))
 const onChanged=vi.fn(),value:unknown={...workspaceFixture,allowed_actions:['retry']}
 if(!isWorkspace(value,'p1','t1'))throw new Error('Invalid synthetic workspace')
 const workspace:TaskWorkspace=value
 render(<StrictMode><StatisticsTaskRecovery workspace={workspace} blocked={false} onChanged={onChanged}/></StrictMode>)
 const button=screen.getByRole('button',{name:'重试原任务'}) as HTMLButtonElement
 fireEvent.click(button);expect(button.disabled).toBe(true)
 await act(async()=>finish(success?Response.json(workspace.task):Response.json({detail:'失败'},{status:500})))
 expect(onChanged).toHaveBeenCalledTimes(1);expect(button.disabled).toBe(false)
 expect(Boolean(screen.queryByRole('alert'))).toBe(!success)
})
