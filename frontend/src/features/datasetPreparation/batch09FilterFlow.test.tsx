import {cleanup,fireEvent,render,screen,waitFor,act} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import fixture from './batch09BackendFixture.json'
import {isDerivationVersion,isFilterReview,isFilterImpact} from './populationFilterApi'
import PreparationReview from './PreparationReview'
import {FilterImpacts} from './PopulationFilter'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('reads real backend v3 fixture and verifies all 7 source-row evaluations',()=>{
 const v=fixture.review
 expect(isFilterReview(v,v.task.project_id,v.task.id)).toBe(true)
 expect(isDerivationVersion(fixture.published,fixture.published.file_id)).toBe(true)
 expect(fixture.impacts.items.every(isFilterImpact)).toBe(true)
 expect(fixture.impacts.items.filter(x=>x.classification==='retained').map(x=>x.row)).toEqual([3,5,7])
 expect(isFilterImpact({...fixture.impacts.items[0],classification:'retained'})).toBe(false)
})
it('editing a frozen filter prevents approval until a new exact checkpoint is produced',async()=>{
 const v=fixture.review
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>url.endsWith('/decision')?Response.json({...v.task,status:'queued',revision:v.task.revision+1}):url.includes('/impacts?')?Response.json(fixture.impacts):Response.json(v));vi.stubGlobal('fetch',fetch)
 render(<PreparationReview projectId={v.task.project_id} taskId={v.task.id}/> )
 const approve=await screen.findByRole('button',{name:'确认并发布筛选版本'})
 expect((approve as HTMLButtonElement).disabled).toBe(false)
 await screen.findByRole('table',{name:'全部父版本有效行及条件判断'})
 expect(fetch.mock.calls.find(([u])=>u.includes('/impacts?'))![0]).not.toContain('?checkpoint_id='+v.checkpoint_id+'?')
 fireEvent.click(screen.getByRole('button',{name:'修改规则'}))
 expect(screen.queryByRole('button',{name:'确认并发布筛选版本'})).toBeNull()
 fireEvent.change(screen.getByLabelText('下限（含）'),{target:{value:'19'}})
 fireEvent.click(screen.getByRole('button',{name:'重新生成预览'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([u])=>u.endsWith('/decision'))).toBe(true))
 const call=fetch.mock.calls.find(([u])=>u.endsWith('/decision'))!
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({operation:'revise',checkpoint_id:v.checkpoint_id,wait_id:v.wait!.id,input_version:v.task.input_version,recipe:{conditions:[{column:1,lower:'19'},{column:2,value:'A'}]}})
})
it('paginates the full receipt and ignores the previous response after replacing its immutable URL',async()=>{
 let late!:(r:Response)=>void
 const item=fixture.impacts.items[0]
 const fetch=vi.fn((url:string)=>url.startsWith('/old')?new Promise<Response>(r=>{late=r}):Promise.resolve(Response.json({items:[{...item,row:99,evaluations:item.evaluations.map(e=>({...e,coordinate:e.coordinate.replace(/\d+$/,'99')}))}],total:1,page:1,page_size:20})))
 vi.stubGlobal('fetch',fetch)
 const view=render(<FilterImpacts url="/old" downloadUrl="/old/download"/> )
 view.rerender(<FilterImpacts url="/new" downloadUrl="/new/download"/> )
 await screen.findByText('99')
 await act(async()=>late(Response.json(fixture.impacts)))
 expect(screen.queryByText('A2 · 不匹配；B2 · 满足')).toBeNull()
})
