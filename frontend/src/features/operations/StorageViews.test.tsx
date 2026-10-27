import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import StoragePanel from './StoragePanel'
import StorageDeletion from './StorageDeletion'
const storage={usage_bytes:80,reserved_bytes:5,unknown_reservation_count:1,unknown_object_count:0,status:'unknown',retention_policy:'retain_all',cleanup_status:'disabled',quota:{mode:'observe_only',limit_bytes:100,revision:2},disk:{status:'unknown',free_bytes:null,total_bytes:null,threshold_bytes:null},policies:[{scope_type:'user',scope_id:'u1',mode:'observe_only',limit_bytes:100,revision:2}]}
const plan={id:'plan1',project_id:'p1',file_id:null,scope_kind:'project',reason:'Synthetic fixture',manifest_sha256:'a'.repeat(64),state:'preview',physical_deletion_available:false,blockers:['not_registered'],items:[],deleted_object_count:0,deleted_bytes:0}
let fetcher:ReturnType<typeof vi.fn>
beforeEach(()=>{setApiSession('csrf','self');fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/policy-events')?{items:[]}:url.endsWith('/recovery')?{status:'unavailable'}:storage));vi.stubGlobal('fetch',fetcher)})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('layers admin storage and only requests audit and recovery when selected',async()=>{
 render(<StoragePanel admin onForbidden={()=>{}} />)
 await screen.findByText('85 bytes / 100 bytes')
 expect(screen.getByRole('navigation',{name:'存储工作视图'})).toBeTruthy()
 expect(fetcher.mock.calls.some(([url])=>url.endsWith('/policy-events')||url.endsWith('/recovery'))).toBe(false)
 expect(screen.queryByRole('button',{name:'编辑配额 u1'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'配额政策'}))
 expect(screen.getByRole('button',{name:'编辑配额 u1'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'配额审计'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.endsWith('/policy-events'))).toBe(true))
 fireEvent.click(screen.getByRole('button',{name:'恢复回执'}))
 await screen.findByText('恢复回执不可用')
})
it('guards quota drafts and preserves a submitted mutation when switching storage views',async()=>{
 let finish!:(value:Response)=>void
 fetcher.mockImplementation(async(url:string,init?:RequestInit)=>init?.method==='PUT'?new Promise<Response>(resolve=>{finish=resolve}):Response.json(url.endsWith('/policy-events')?{items:[]}:storage))
 const register=vi.fn((_guard:()=>boolean,_dirty?:()=>boolean)=>()=>{})
 render(<StoragePanel admin registerLeaveGuard={register} onForbidden={()=>{}} />)
 await screen.findByText('85 bytes / 100 bytes')
 expect(register.mock.calls.at(-1)?.[1]?.()).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'配额政策'}))
 fireEvent.click(screen.getByRole('button',{name:'编辑配额 u1'}))
 fireEvent.change(screen.getByLabelText('配额变更理由'),{target:{value:'Explicit quota change'}})
 expect(register.mock.calls.at(-1)?.[1]?.()).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'保存配额'}))
 await waitFor(()=>expect(finish).toBeTruthy())
 const mutation=fetcher.mock.calls.find(([,init])=>init?.method==='PUT')!
 fireEvent.click(screen.getByRole('button',{name:'存储概览'}))
 expect(mutation[1].signal.aborted).toBe(false)
 await act(async()=>finish(Response.json({})))
 expect(register.mock.calls.at(-1)?.[1]?.()).toBe(false)
})
it('lazily mounts own controlled disposal and retains required input when hidden',async()=>{
 const register=vi.fn((_guard:()=>boolean,_dirty?:()=>boolean)=>()=>{})
 render(<StoragePanel admin={false} registerLeaveGuard={register} onForbidden={()=>{}} />)
 expect(screen.queryByLabelText('删除项目标识')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'受控处置'}))
 fireEvent.change(screen.getByLabelText('删除项目标识'),{target:{value:'p1'}})
 expect(register.mock.calls.some(([,dirty])=>dirty?.())).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'存储概览'}))
 fireEvent.click(screen.getByRole('button',{name:'受控处置'}))
 expect(screen.getByLabelText('删除项目标识')).toHaveProperty('value','p1')
 act(()=>clearApiSession())
 expect(screen.queryByDisplayValue('p1')).toBeNull()
})
it('aborts a hidden disposal status GET while keeping already submitted POST requests',async()=>{
 fetcher.mockImplementation(async(url:string)=>url.endsWith('/preview')?Response.json(plan):new Promise<Response>(()=>{}))
 const view=render(<StorageDeletion onForbidden={()=>{}} />)
 fireEvent.change(screen.getByLabelText('删除项目标识'),{target:{value:'p1'}})
 fireEvent.change(screen.getByLabelText('删除理由'),{target:{value:'Synthetic fixture'}})
 fireEvent.click(screen.getByRole('button',{name:'预览处置范围'}))
 await screen.findByRole('button',{name:'核对处置状态'})
 fireEvent.click(screen.getByRole('button',{name:'核对处置状态'}))
 const status=fetcher.mock.calls.find(([url])=>url.endsWith('/plan1'))!
 view.rerender(<StorageDeletion active={false} onForbidden={()=>{}} />)
 expect(status[1].signal.aborted).toBe(true)
})
it('retains the frozen deletion identity through a hidden pending execution and unknown receipt',async()=>{
 let rejectExecution!:(cause:Error)=>void
 let attempts=0
 fetcher.mockImplementation(async(url:string)=>{
  if(url.endsWith('/execute')){
   attempts++
   if(attempts===1)return new Promise<Response>((_resolve,reject)=>{rejectExecution=reject})
   return Response.json({...plan,state:'partial_retained',physical_deletion_available:true,blockers:[]})
  }
  return Response.json({...plan,physical_deletion_available:true,blockers:[]})
 })
 const view=render(<StorageDeletion onForbidden={()=>{}} />)
 fireEvent.change(screen.getByLabelText('删除项目标识'),{target:{value:'p1'}})
 fireEvent.change(screen.getByLabelText('删除理由'),{target:{value:'Synthetic fixture'}})
 fireEvent.click(screen.getByRole('button',{name:'预览处置范围'}))
 await screen.findByLabelText('确认仅处置本计划登记合成对象')
 fireEvent.click(screen.getByLabelText('确认仅处置本计划登记合成对象'))
 fireEvent.click(screen.getByRole('button',{name:'执行登记夹具处置'}))
 await waitFor(()=>expect(rejectExecution).toBeTruthy())
 const first=fetcher.mock.calls.find(([url])=>url.endsWith('/execute'))!
 view.rerender(<StorageDeletion active={false} onForbidden={()=>{}} />)
 expect(first[1].signal.aborted).toBe(false)
 await act(async()=>rejectExecution(new TypeError('lost acknowledgement')))
 view.rerender(<StorageDeletion active onForbidden={()=>{}} />)
 await screen.findByText('处置结果未知；只可核对状态或使用原确认重试。')
 fireEvent.click(screen.getByRole('button',{name:'使用原确认重试'}))
 await screen.findByText('部分对象已处置，保留项仍存在')
 const posts=fetcher.mock.calls.filter(([url])=>url.endsWith('/execute'))
 expect(posts).toHaveLength(2)
 expect(posts[1][1].headers['Idempotency-Key']).toBe(posts[0][1].headers['Idempotency-Key'])
 expect(posts[1][1].body).toBe(posts[0][1].body)
})
