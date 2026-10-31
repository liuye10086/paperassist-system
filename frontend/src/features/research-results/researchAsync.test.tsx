import {act,renderHook,waitFor,render,screen,fireEvent,cleanup} from '@testing-library/react'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import {clearApiSession,setApiSession} from '../../shared/api/client'
import {useResearchRead} from './api'
import ResearchCandidateReview from './ResearchCandidateReview'
import ResearchWritingHandoff from './ResearchWritingHandoff'
import {snapshotFixture,manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import ResearchPublished from './ResearchPublished'
import ResearchFindings from './ResearchFindings'
import {queueResearchSource} from '../bio-insights/researchHandoff'
const response=(data:unknown)=>new Response(JSON.stringify(data))
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession()})
it('receives an exact B04 result member into its own draft without losing a prior finding draft',async()=>{
 const finding={id:'version-a',set_id:'set-a',revision:1,parent_id:null,sha256:'a'.repeat(64),content:{title:'Existing A',sources:[],facts:[],methods:[],claims:[],conflicts:[],reviews:[],limitations:[],gaps:[],warnings:[],notes:''}}
 vi.stubGlobal('fetch',vi.fn().mockImplementation((url:string)=>Promise.resolve(response(url.endsWith('/research-findings')?{items:[{id:'set-a',title:'Existing A',revision:1,current_version_id:'version-a'}]}:url.includes('/versions/')?finding:{items:[],total:0,page:1,page_size:25}))))
 const{rerender}=render(<ResearchFindings projectId="p1" active/>);fireEvent.click(await screen.findByRole('button',{name:'Existing A · v1'}));await waitFor(()=>expect((screen.getByLabelText('发现集合标题') as HTMLInputElement).value).toBe('Existing A'));fireEvent.change(screen.getByLabelText('研究备注'),{target:{value:'A draft retained'}})
 rerender(<ResearchFindings projectId="p1" active={false}/>);queueResearchSource('p1',{source_kind:'bio_insight_result_member',source_id:'member-r0',sha256:'b'.repeat(64),locator:{kind:'row',table:'comparison_results',row_key:{row_key:'zero-row'},column:'q_within_contrast'}});rerender(<ResearchFindings projectId="p1" active/>);await waitFor(()=>expect((screen.getByLabelText('发现集合标题') as HTMLInputElement).value).toBe(''));expect(screen.getByText('member-r0',{exact:false})).toBeTruthy();expect(screen.getByText(/zero-row/)).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Existing A · v1'}));await waitFor(()=>expect((screen.getByLabelText('研究备注') as HTMLTextAreaElement).value).toBe('A draft retained'))
})
it('opens a separate processed-source draft after viewing existing findings and preserves the old draft',async()=>{
 const finding={id:'version-a',set_id:'set-a',revision:1,parent_id:null,sha256:'a'.repeat(64),content:{title:'Existing A',sources:[{source_kind:'bio_processed_dataset_version',source_id:'processed-a',locator:{kind:'object'}}],facts:[],methods:[],claims:[],conflicts:[],reviews:[],limitations:[],gaps:[],warnings:[],notes:''}}
 vi.stubGlobal('fetch',vi.fn().mockImplementation((url:string)=>Promise.resolve(response(url.endsWith('/research-findings')?{items:[{id:'set-a',title:'Existing A',revision:1,current_version_id:'version-a'}]}:url.includes('/versions/')?finding:{items:[],total:0,page:1,page_size:25}))))
 const{rerender}=render(<ResearchFindings projectId="p1" active initialProcessedId="processed-a"/>);fireEvent.click(await screen.findByRole('button',{name:'Existing A · v1'}));await waitFor(()=>expect((screen.getByLabelText('发现集合标题') as HTMLInputElement).value).toBe('Existing A'));fireEvent.change(screen.getByLabelText('研究备注'),{target:{value:'Retained A review draft'}})
 rerender(<ResearchFindings projectId="p1" active initialProcessedId="processed-b"/>);expect((screen.getByLabelText('发现集合标题') as HTMLInputElement).value).toBe('');expect(screen.getByText('processed-b',{exact:false})).toBeDefined()
 fireEvent.click(screen.getByRole('button',{name:'Existing A · v1'}));await waitFor(()=>expect((screen.getByLabelText('研究备注') as HTMLTextAreaElement).value).toBe('Retained A review draft'))
})
it('retains published manuscript writing drafts across body tabs and section visibility changes',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockImplementation((url:string)=>Promise.resolve(response(url.endsWith('/manuscripts')?{items:[manuscriptFixture]}:url.endsWith('/writing-requests')?{items:[]}:url.endsWith('/exports')?{items:[],pdf_status:'not_requested'}:manuscriptFixture))))
 const props={projectId:'p1',active:true,manuscriptId:manuscriptFixture.id,revision:manuscriptFixture.current_revision,onView:vi.fn(),onSelect:vi.fn()}
 const{rerender}=render(<ResearchPublished {...props} view="writing"/>);fireEvent.change(await screen.findByLabelText('自由写作要求'),{target:{value:'Keep this exact draft'}})
 rerender(<ResearchPublished {...props} view="body"/>);rerender(<ResearchPublished {...props} view="writing"/>);expect((screen.getByLabelText('自由写作要求') as HTMLTextAreaElement).value).toBe('Keep this exact draft')
 rerender(<ResearchPublished {...props} active={false} view="writing"/>);rerender(<ResearchPublished {...props} view="writing"/>);await waitFor(()=>expect((screen.getByLabelText('自由写作要求') as HTMLTextAreaElement).value).toBe('Keep this exact draft'))
})
it('aborts stale project, delivery, or fixed version reads',async()=>{
 let finish!:(r:Response)=>void
 const fetch=vi.fn().mockImplementationOnce(()=>new Promise<Response>(r=>finish=r)).mockResolvedValueOnce(response({id:'new-delivery'}));vi.stubGlobal('fetch',fetch)
 const{result,rerender}=renderHook(({url})=>useResearchRead<{id:string}>(url,true),{initialProps:{url:'/api/v1/projects/p1/research-results/writing-config?delivery_id=d1'}})
 rerender({url:'/api/v1/projects/p2/research-results/writing-config?delivery_id=d2'})
 await waitFor(()=>expect(result.current.data?.id).toBe('new-delivery'))
 await act(async()=>finish(response({id:'old-delivery'})));expect(result.current.data?.id).toBe('new-delivery');expect(fetch.mock.calls[0][1].signal.aborted).toBe(true)
})
it('requires explicit candidate review before publishing and blocks duplicate clicks',async()=>{
 let finish!:(r:Response)=>void
 const candidate={id:'c',delivery_id:'d',task_id:'task',task:{id:'task',status:'succeeded'},candidate:snapshotFixture,candidate_sha256:'a'.repeat(64),manuscript_id:null,base_version_id:null,expected_revision:0,published_version_id:null}
 const fetch=vi.fn().mockImplementation((_url:string,init:RequestInit)=>init?.method==='POST'?new Promise<Response>(r=>finish=r):Promise.resolve(response(candidate)));vi.stubGlobal('fetch',fetch)
 render(<ResearchCandidateReview projectId="p1" candidateId="c" active onPublished={vi.fn()}/>)
 await screen.findByText('system_fact_draft',{exact:false})
 const button=screen.getByRole('button',{name:'显式发布为正式稿件版本'});expect(button.hasAttribute('disabled')).toBe(true)
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(button);fireEvent.click(button)
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
 await act(async()=>finish(response({manuscript_id:'m',version_id:'v',revision:1,candidate_id:'c'})))
 await screen.findByText('已发布固定稿件版本',{exact:false})
})
it('requires a fresh review after a queued candidate becomes available and after its exact hash changes',async()=>{
 let reads=0
 const candidate={id:'c',delivery_id:'d',task_id:'task',task:{id:'task',status:'succeeded'},candidate:snapshotFixture,candidate_sha256:'a'.repeat(64),manuscript_id:null,base_version_id:null,expected_revision:0,published_version_id:null}
 vi.stubGlobal('fetch',vi.fn().mockImplementation(()=>{reads++;return Promise.resolve(response(reads===1?{...candidate,task:{id:'task',status:'queued'},candidate:null,candidate_sha256:null}:reads===2?candidate:{...candidate,candidate_sha256:'b'.repeat(64)}))}))
 render(<ResearchCandidateReview projectId="p1" candidateId="c" active onPublished={vi.fn()}/>);const checkbox=await screen.findByRole('checkbox');expect(checkbox.hasAttribute('disabled')).toBe(true)
 await waitFor(()=>expect(checkbox.hasAttribute('disabled')).toBe(false),{timeout:5000});expect((checkbox as HTMLInputElement).checked).toBe(false);expect(screen.getByRole('button',{name:'显式发布为正式稿件版本'}).hasAttribute('disabled')).toBe(true)
 fireEvent.click(checkbox);expect((checkbox as HTMLInputElement).checked).toBe(true);fireEvent.click(screen.getByRole('button',{name:'刷新候选'}));await waitFor(()=>expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false));expect(screen.getByRole('button',{name:'显式发布为正式稿件版本'}).hasAttribute('disabled')).toBe(true)
})
it('unknown candidate publication uses GET recovery without another POST',async()=>{
 const candidate={id:'c',delivery_id:'d',task_id:'task',task:{id:'task',status:'succeeded'},candidate:snapshotFixture,candidate_sha256:'a'.repeat(64),manuscript_id:null,base_version_id:null,expected_revision:0,published_version_id:null}
 const fetch=vi.fn().mockImplementation((_url:string,init:RequestInit)=>init?.method==='POST'?Promise.reject(new TypeError('network')):Promise.resolve(response(candidate)));vi.stubGlobal('fetch',fetch)
 render(<ResearchCandidateReview projectId="p1" candidateId="c" active onPublished={vi.fn()}/>)
 await screen.findByText('system_fact_draft',{exact:false});fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'显式发布为正式稿件版本'}));await screen.findByText('发布结果未知，请先回读候选，不重复提交。');fireEvent.click(screen.getByRole('button',{name:'先回读候选核对发布结果'}));await screen.findByText('已回读候选，尚未发布。可以显式重试原发布键。');expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
})
it('isolates delivery drafts and keeps existing choices during explicit merge',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockImplementation((url:string)=>Promise.resolve(response(url.includes('writing-config')?{document_context:{document_kind:'sci'},thesis:null}:url.endsWith('research-findings')?{items:[{id:'root',title:'Result',revision:1,current_version_id:'finding'}]}:{items:[],total:0,page:1,page_size:25}))))
 const{rerender}=render(<ResearchWritingHandoff key="d1" projectId="p1" deliveryId="d1" active onCandidate={vi.fn()}/>)
 fireEvent.click(await screen.findByRole('checkbox',{name:'Result · v1 · finding'}));fireEvent.click(screen.getByRole('button',{name:'显式合入当前交付草稿（保留已有选择）'}));expect(screen.getByText('finding',{exact:true})).toBeDefined()
 fireEvent.change(screen.getByLabelText('人工补充说明'),{target:{value:'delivery one note'}})
 rerender(<ResearchWritingHandoff key="d2" projectId="p1" deliveryId="d2" active onCandidate={vi.fn()}/>);expect((screen.getByLabelText('人工补充说明') as HTMLTextAreaElement).value).toBe('')
 rerender(<ResearchWritingHandoff key="d1" projectId="p1" deliveryId="d1" active onCandidate={vi.fn()}/>);expect((screen.getByLabelText('人工补充说明') as HTMLTextAreaElement).value).toBe('delivery one note');expect(screen.getByText('finding',{exact:true})).toBeDefined()
 act(()=>clearApiSession());expect((screen.getByLabelText('人工补充说明') as HTMLTextAreaElement).value).toBe('')
})
