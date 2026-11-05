import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import InsightPlanEditor from './InsightPlanEditor'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
vi.mock('./InsightSources',()=>({default:({onChange}:{onChange:(v:unknown[])=>void})=><button onClick={()=>onChange([{source_kind:'bio_processed_dataset_version',source_id:'s1',sha256:'a'.repeat(64),role:'processed',locator:{kind:'object'}}])}>选用测试来源</button>}))
afterEach(()=>{cleanup();sessionStorage.clear();vi.clearAllMocks()})
it('requires sources before configuration, preserves draft fields and checks before execution',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({items:[],total:0}))
 render(<InsightPlanEditor projectId="p1" kind="comparison" active onSaved={()=>{}} onRun={()=>{}}/> )
 expect(screen.getByRole('button',{name:'配置分析'})).toHaveProperty('disabled',true)
 expect(screen.getByRole('button',{name:'检查与运行'})).toHaveProperty('disabled',true)
 fireEvent.click(screen.getByRole('button',{name:'选用测试来源'}))
 fireEvent.click(screen.getByRole('button',{name:'下一步：配置分析'}))
 fireEvent.change(screen.getByLabelText('参考／基因 ID 版本'),{target:{value:'test-reference'}})
 fireEvent.click(screen.getByRole('button',{name:'选择数据'}))
 fireEvent.click(screen.getByRole('button',{name:'下一步：配置分析'}))
 expect(screen.getByLabelText('参考／基因 ID 版本')).toHaveProperty('value','test-reference')
 fireEvent.click(screen.getByRole('button',{name:'下一步：检查与运行'}))
 expect(screen.getByRole('button',{name:'确认并保存新版本'})).toHaveProperty('disabled',true)
 expect(screen.getByRole('button',{name:'提交已确认版本后台计算'})).toHaveProperty('disabled',true)
 expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})
it('uses an automatic plan name when no optional name was entered and only saves explicitly',async()=>{
 const bodies:unknown[]=[]
 vi.mocked(apiFetch).mockImplementation(async(_url,init)=>{if(init?.method==='POST'){bodies.push(JSON.parse(String(init.body)));return Response.json({id:'v1',plan_id:'p',revision:1})}return Response.json({items:[],total:0})})
 render(<InsightPlanEditor projectId="p1" kind="comparison" active onSaved={()=>{}} onRun={()=>{}}/> )
 fireEvent.click(screen.getByRole('button',{name:'选用测试来源'}));fireEvent.click(screen.getByRole('button',{name:'下一步：配置分析'}))
 fireEvent.change(screen.getByLabelText('参考／基因 ID 版本'),{target:{value:'test-reference'}})
 expect(bodies).toHaveLength(0)
 fireEvent.click(screen.getByRole('button',{name:'保存不可变草稿版本'}))
 await waitFor(()=>expect(bodies).toHaveLength(1))
 expect(bodies[0]).toMatchObject({name:'固定设计差异比较',decision:'draft'})
})
