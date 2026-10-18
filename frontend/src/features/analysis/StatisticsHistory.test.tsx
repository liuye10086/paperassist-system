import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import StatisticsResults from './StatisticsResults'
import {correlationResult} from './correlationFixtures'
import {setLocale} from '../../shared/i18n'

afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const props={base:'/api/v1/projects/p1/files/f1',savedRevision:null,fieldsMatch:false,disabled:false,onBusyChange:()=>{}}
const old={...correlationResult,id:'historical-run',analysis_context:{...correlationResult.analysis_context,plan:{...correlationResult.analysis_context.plan,research_request:{...correlationResult.analysis_context.plan.research_request!,output_language:'en'}}}}
const workbench={configurations:[],available_kinds:['scatter','line','bar','violin'],language:'en',fields:[]}

test('confirmed historical runs remain reachable without a current setup and use their own language and exact run',async()=>{
 const fetch=vi.fn(async(url:string)=>{
  if(url.endsWith('/analysis-runs'))return Response.json({items:[correlationResult,old]})
  if(url.includes('/historical-run/figure-workbench'))return Response.json(workbench)
  return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetch)
 render(<StatisticsResults {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'查看历史已确认结果'}))
 fireEvent.change(await screen.findByLabelText('图表与报告所用结果'),{target:{value:'historical-run'}})
 await screen.findByRole('button',{name:'保存配置草稿'})
 expect(fetch.mock.calls.some(([url])=>url.endsWith('/analysis-runs/historical-run/figure-workbench'))).toBe(true)
 expect(fetch.mock.calls.some(([url])=>url.endsWith('/analysis-runs/run3/figure-workbench'))).toBe(false)
 expect(screen.getByText('所选结果的图表、解释与报告保持原来源和语言，不替换集合冻结引用。')).toBeTruthy()
 expect(document.body.textContent).not.toContain('historical-run')
 expect(document.body.textContent).not.toContain(correlationResult.source.source_sha256)
})

test('historical listing rejects a result whose confirmed source does not match its own plan',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...old,source:{...old.source,dataset_version:99}}]})))
 render(<StatisticsResults {...props}/>);fireEvent.click(screen.getByRole('button',{name:'查看历史已确认结果'}))
 await screen.findByRole('alert')
 expect(screen.queryByLabelText('图表与报告所用结果')).toBeNull()
 expect(screen.queryByRole('button',{name:'保存配置草稿'})).toBeNull()
})

test('a delayed historical list cannot become selectable in another project',async()=>{
 let finish!:(response:Response)=>void
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>{finish=resolve})))
 const view=render(<StatisticsResults {...props}/>);fireEvent.click(screen.getByRole('button',{name:'查看历史已确认结果'}))
 view.rerender(<StatisticsResults {...props} base='/api/v1/projects/p2/files/f1'/>);finish(Response.json({items:[old]}))
 await waitFor(()=>expect(screen.queryByLabelText('图表与报告所用结果')).toBeNull())
 expect(screen.queryByRole('button',{name:'保存配置草稿'})).toBeNull()
})

test('history picker and a Chinese result language are labelled in English UI',async()=>{
 setLocale('en')
 const chinese={...correlationResult,analysis_context:{...correlationResult.analysis_context,plan:{...correlationResult.analysis_context.plan,research_request:{...correlationResult.analysis_context.plan.research_request!,output_language:'zh-CN'}}}}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[chinese,old]})))
 render(<StatisticsResults {...props}/>);fireEvent.click(screen.getByRole('button',{name:'View confirmed result history'}))
 const picker=await screen.findByLabelText('Result used for figures and reports')
 expect(picker.textContent).not.toMatch(/[\u4e00-\u9fff]/)
})

test('reloading a missing selected historical run does not substitute the newest run',async()=>{
 let missing=false
 const fetch=vi.fn(async(url:string)=>{
  if(url.endsWith('/analysis-runs'))return Response.json({items:missing?[correlationResult]:[correlationResult,old]})
  if(url.includes('/historical-run/figure-workbench'))return Response.json(workbench)
  return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetch)
 render(<StatisticsResults {...props}/>);fireEvent.click(screen.getByRole('button',{name:'查看历史已确认结果'}))
 fireEvent.change(await screen.findByLabelText('图表与报告所用结果'),{target:{value:'historical-run'}})
 await screen.findByRole('button',{name:'保存配置草稿'})
 missing=true;fireEvent.click(screen.getByRole('button',{name:'重新读取历史已确认结果'}))
 await screen.findByText('所选历史结果当前不可用，请重新读取；不会自动替换为最新结果。')
 expect(screen.queryByRole('button',{name:'保存配置草稿'})).toBeNull()
 expect(fetch.mock.calls.some(([url])=>url.endsWith('/analysis-runs/run3/figure-workbench'))).toBe(false)
})
