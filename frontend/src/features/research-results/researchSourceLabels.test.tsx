import {useState} from 'react'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import ResearchSources from './ResearchSources'
import ResearchWritingHandoff from './ResearchWritingHandoff'
import type {Source} from './contracts'
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession()})
const item=(id:string,title:string,kind='analysis_run')=>({source_id:id,title,source_kind:kind,status:'succeeded',sha256:'a'.repeat(64),created_at:'',version:1})
it('retains project-scoped selected source names across pages and reopening',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json({items:[item(url.includes('page=2')?'source-b':'source-a',url.includes('page=2')?'样本 B':'样本 A')],total:26,page:url.includes('page=2')?2:1,page_size:25})))
 let selected:Source[]=[]
 function Harness({projectId='p1'}:{projectId?:string}){const [value,set]=useState(selected);return <ResearchSources projectId={projectId} active value={value} onChange={next=>{selected=next;set(next)}}/>}
 const first=render(<Harness/>);await screen.findByRole('option',{name:/样本 A/});fireEvent.change(screen.getByLabelText('固定来源版本'),{target:{value:'source-a'}});fireEvent.click(screen.getByRole('button',{name:'加入固定来源'}));fireEvent.click(screen.getByRole('button',{name:'下一页'}));await screen.findByRole('option',{name:/样本 B/});expect(screen.getByText(/样本 A/)).toBeTruthy();expect(document.body.textContent).not.toContain('source-a')
 first.unmount();const reopened=render(<Harness/>);await waitFor(()=>expect(screen.getAllByText(/样本 A/).length).toBeGreaterThan(0));expect(selected[0].source_id).toBe('source-a');vi.mocked(fetch).mockImplementation(()=>new Promise(()=>{}));reopened.rerender(<Harness projectId="p2"/>);expect(screen.queryByText(/样本 A/)).toBeNull();expect(screen.getByText(/已选固定来源 1/)).toBeTruthy()
})
it('retains named writing selections across pages and reopening without exposing ids',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{if(url.includes('source_kind=research_figure_version'))return Response.json({items:[item(url.includes('page=2')?'figure-b':'figure-a',url.includes('page=2')?'研究图 B':'研究图 A','research_figure_version')],total:26,page:url.includes('page=2')?2:1,page_size:25});if(url.includes('writing-config'))return Response.json({document_context:{document_kind:'sci'},thesis:null});return Response.json({items:[],total:0,page:1,page_size:25})}))
 const props={projectId:'p1',deliveryId:'sci',active:true,onCandidate:vi.fn()};const first=render(<ResearchWritingHandoff {...props}/>);fireEvent.click(await screen.findByRole('checkbox',{name:/研究图 A/}));fireEvent.click(screen.getByRole('button',{name:'添加选中的材料'}));fireEvent.click(screen.getAllByRole('button',{name:'下一页'})[0]);await screen.findByRole('checkbox',{name:/研究图 B/});expect(screen.getByText(/研究图 A/)).toBeTruthy();expect(document.body.textContent).not.toContain('figure-a')
 first.unmount();render(<ResearchWritingHandoff {...props}/>);await waitFor(()=>expect(screen.getAllByText(/研究图 A/).length).toBeGreaterThan(0));expect(screen.getByRole('button',{name:'从本交付草稿移除'})).toBeTruthy()
})
