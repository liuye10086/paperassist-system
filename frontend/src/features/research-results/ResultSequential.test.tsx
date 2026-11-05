import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {clearApiSession,setApiSession} from '../../shared/api/client'
import ResearchFigureComposer from './ResearchFigureComposer'
import ResearchReport from './ResearchReport'

beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession();sessionStorage.clear()})
it.each(['figure','report'])('opens %s history without presenting a creation form or submitting work',async kind=>{
 const fetch=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[],total:0,page:1,page_size:20}));vi.stubGlobal('fetch',fetch)
 render(kind==='figure'?<ResearchFigureComposer projectId="p1" active selectedId="" onSelect={vi.fn()}/>:<ResearchReport projectId="p1" active selectedId="" onSelect={vi.fn()}/>);
 expect(screen.queryByLabelText(kind==='figure'?'图标题':'报告标题')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:kind==='figure'?'新建研究图':'新建研究报告'}))
 expect(screen.getByRole('button',{name:/确认与生成/})).toHaveProperty('disabled',true)
 expect(screen.queryByRole('button',{name:kind==='figure'?'生成固定研究图版本':'生成固定报告与成果包'})).toBeNull()
 expect(fetch.mock.calls.every(call=>!call[1]||(call[1] as RequestInit).method!=='POST')).toBe(true)
})
it.each(['figure','report'])('automatically restores an interrupted %s request and keeps its editor mounted',async kind=>{
 const key=`paperassist.research-request.v1:owner:p1:${kind}:new`
 sessionStorage.setItem(key,JSON.stringify({key:'original-request',url:`/api/v1/projects/p1/research-${kind==='figure'?'figures':'reports'}`,body:{retained:true}}))
 const fetch=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[],total:0,page:1,page_size:20}));vi.stubGlobal('fetch',fetch)
 render(kind==='figure'?<ResearchFigureComposer projectId="p1" active selectedId="" onSelect={vi.fn()}/>:<ResearchReport projectId="p1" active selectedId="" onSelect={vi.fn()}/>);
 await screen.findByRole('button',{name:'查询原请求结果'})
 await waitFor(()=>expect(screen.getByRole('button',{name:kind==='figure'?'返回图版本列表':'返回报告版本列表'})).toHaveProperty('disabled',true))
 expect(JSON.parse(sessionStorage.getItem(key)!).key).toBe('original-request')
 expect(fetch.mock.calls.every(([,init])=>!init?.method)).toBe(true)
})
it('shows a source verification conflict without claiming the result list is empty',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({detail:{code:'research_source_conflict'}},{status:409})))
 render(<ResearchFigureComposer projectId="p1" active selectedId="" onSelect={vi.fn()}/>);
 expect(await screen.findByRole('alert')).toHaveProperty('textContent','研究来源、数值或版本需要重新核对；原有成果仍保留。')
 expect(screen.queryByText('暂无研究图，可复用已有图像创建。')).toBeNull()
})
it('retains an old-version pending editor across result module switches',async()=>{
 const key='paperassist.research-request.v1:owner:p1:report:old'
 sessionStorage.setItem(key,JSON.stringify({key:'old-request',url:'/api/v1/projects/p1/research-reports/root/versions',body:{retained:true}}))
 const report={id:'old',root_id:'root',revision:2,content:{title:'Saved report',language:'en',finding:{id:'finding',content:{}},figures:[]},task:{status:'succeeded'},members:[]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/research-reports/old')?report:{items:[],total:0,page:1,page_size:20})))
 const props={projectId:'p1',onSelect:vi.fn()};const view=render(<ResearchReport {...props} active selectedId="old"/>);
 await screen.findByRole('button',{name:'查询原请求结果'})
 view.rerender(<ResearchReport {...props} active={false} selectedId=""/>);
 view.rerender(<ResearchReport {...props} active selectedId=""/>);
 expect(screen.getByRole('button',{name:'查询原请求结果'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'返回报告版本列表'})).toHaveProperty('disabled',true)
 expect(JSON.parse(sessionStorage.getItem(key)!).key).toBe('old-request')
})
