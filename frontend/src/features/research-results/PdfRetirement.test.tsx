import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import ResearchReport from './ResearchReport'
import ResearchFigureComposer from './ResearchFigureComposer'
import FigureSetup from '../bio-insights/FigureSetup'
import {defaultConfig,planIssues} from '../bio-insights/state'
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession();sessionStorage.clear()})
it('omits only the retired PDF option from an existing report draft request',async()=>{
 const draft={title:'Retained title',finding_version_id:'finding1',figure_version_ids:['figure1'],language:'en',root_id:null,expected_revision:0,include_pdf_id:'pdf1'}
 sessionStorage.setItem('paperassist.research-draft.v1:owner:p1:report:new',JSON.stringify(draft))
 const fetch=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{id:'new-report'}:{items:[],total:0,page:1,page_size:20}));vi.stubGlobal('fetch',fetch)
 render(<ResearchReport projectId="p1" active selectedId="" onSelect={vi.fn()}/>);
 expect((screen.getByLabelText('报告标题') as HTMLInputElement).value).toBe('Retained title');expect(screen.getByText(/旧草稿中的 PDF 选项不再支持/)).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'生成固定报告与成果包'}));await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true))
 const request=JSON.parse(String(fetch.mock.calls.find(([,init])=>init?.method==='POST')![1]?.body));const{include_pdf_id:_,...kept}=draft;expect(request).toEqual(kept)
 expect(JSON.parse(sessionStorage.getItem('paperassist.research-draft.v1:owner:p1:report:new')!)).toEqual(draft)
})
it('retains the legacy figure draft while requiring explicit PDF removal',async()=>{
 const draft={expected_revision:0,mode:'reuse',panels:[{source:{source_kind:'original_file',source_id:'image1',locator:{kind:'object'}},member_key:null,label:'A',note:'keep'}],title:'Keep figure',caption:'Keep caption',caption_fact_ids:[],caption_sources:[],language:'zh-CN',figure_language:'original',width_mm:180,dpi:300,columns:2,background:'#ffffff',margin_mm:3,font_size_pt:10,formats:['pdf','png']}
 sessionStorage.setItem('paperassist.research-draft.v1:owner:p1:figure:new',JSON.stringify(draft));vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[],total:0,page:1,page_size:20})))
 render(<ResearchFigureComposer projectId="p1" active selectedId="" onSelect={vi.fn()}/>);expect(screen.queryByLabelText('PDF')).toBeNull();expect(screen.getByRole('button',{name:'生成固定研究图版本'}).hasAttribute('disabled')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'移除 PDF 格式'}));expect(JSON.parse(sessionStorage.getItem('paperassist.research-draft.v1:owner:p1:figure:new')!)).toEqual({...draft,formats:['png']});expect(screen.getByRole('button',{name:'生成固定研究图版本'}).hasAttribute('disabled')).toBe(false)
})
it('keeps bio figure defaults Word-independent and requires explicit adjustment of legacy PDF formats',()=>{
 const config={...defaultConfig('figure'),result_source_id:'r1',formats:['pdf','svg']};const changed=vi.fn();render(<FigureSetup projectId="p1" config={config} onChange={changed} sources={[]}/>);
 expect(defaultConfig('figure').formats).toEqual(['png','tiff','svg']);expect(screen.queryByLabelText('PDF')).toBeNull();expect(planIssues(config).join(' ')).toContain('PDF 图件不再支持');fireEvent.click(screen.getByRole('button',{name:'移除 PDF 格式'}));expect(changed).toHaveBeenCalledWith({...config,formats:['svg']})
})
