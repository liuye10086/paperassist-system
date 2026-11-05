import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import {manuscriptFixture,snapshotFixture} from '../manuscripts/manuscriptFixtures'
import ResearchWritingHandoff from './ResearchWritingHandoff'
import ResearchCandidateReview from './ResearchCandidateReview'

vi.mock('../manuscripts/ManuscriptPreview',()=>({default:()=> <p>固定材料预览</p>}))
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession();sessionStorage.clear()})
const draftKey='paperassist.research-draft.v1:owner:p1:writing:d1'
const oldDraft={finding_version_ids:['old-finding'],figure_version_ids:[],report_version_ids:[],manual_notes:'保留的备注',output_language:'en',sections:['results'],target:'',thesis:null}
const props={projectId:'p1',deliveryId:'d1',active:true,onCandidate:vi.fn()}
function fixtureFetch(manuscripts:()=>{items:typeof manuscriptFixture[]}=()=>({items:[]})){
 return vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/manuscripts'))return Response.json(manuscripts())
  if(url.includes('writing-config'))return Response.json({document_context:{document_kind:'sci',delivery_id:'d1'},thesis:null})
  if(url.endsWith('/writing-selection'))return Response.json({merge_preview:snapshotFixture,selected_source_ids:[],selection_sha256:'a'.repeat(64)})
  if(url.endsWith('/research-reports/report-v1'))return Response.json({id:'report-v1',revision:1,content:{title:'固定旧报告'},task:{status:'succeeded'}})
  if(url.endsWith('/research-figures/figure-v2'))return Response.json({id:'figure-v2',revision:2,config:{title:'补充图'},task:{status:'succeeded'}})
  if(url.endsWith('/research-findings/set/versions/finding-v1'))return Response.json({id:'finding-v1',set_id:'set',revision:1,content:{title:'旧研究发现'}})
  if(init?.method==='POST')throw new Error('Unexpected generation')
  return Response.json({items:[],total:0,page:1,page_size:25})
 })
}
it('adds a fixed incoming report only after explicit action, keeping and deduplicating the existing delivery draft',async()=>{
 sessionStorage.setItem(draftKey,JSON.stringify(oldDraft))
 const fetcher=fixtureFetch();vi.stubGlobal('fetch',fetcher)
 const onReturnSource=vi.fn(),incomingSource={kind:'research_report_version' as const,id:'report-v1'}
 const first=render(<ResearchWritingHandoff {...props} incomingSource={incomingSource} onReturnSource={onReturnSource}/>)
 await screen.findByText(/固定旧报告.*v1/)
 expect(JSON.parse(sessionStorage.getItem(draftKey)!).report_version_ids).toEqual([])
 fireEvent.click(screen.getByRole('button',{name:'添加此固定成果'}))
 expect(JSON.parse(sessionStorage.getItem(draftKey)!)).toMatchObject({...oldDraft,report_version_ids:['report-v1']})
 fireEvent.click(screen.getByRole('button',{name:'返回来源成果'}));expect(onReturnSource).toHaveBeenCalledTimes(1)
 first.unmount();render(<ResearchWritingHandoff {...props} incomingSource={incomingSource}/>)
 await screen.findByText('此固定成果已在当前交付草稿中。')
 fireEvent.click(screen.getByRole('button',{name:'写作设置'}))
 expect((screen.getByLabelText('人工补充说明') as HTMLTextAreaElement).value).toBe('保留的备注')
 expect(JSON.parse(sessionStorage.getItem(draftKey)!).report_version_ids).toEqual(['report-v1'])
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})
it('resolves an old finding by its exact set and version while requiring more than a figure to preview',async()=>{
 const fetcher=fixtureFetch();vi.stubGlobal('fetch',fetcher)
 const view=render(<ResearchWritingHandoff {...props} incomingSource={{kind:'research_figure_version',id:'figure-v2'}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'添加此固定成果'}))
 expect(screen.getByText('请先选择研究发现或分析报告，研究图作为补充材料。')).toBeTruthy()
 expect((screen.getByRole('button',{name:'预览写作材料'}) as HTMLButtonElement).disabled).toBe(true)
 view.rerender(<ResearchWritingHandoff {...props} incomingSource={{kind:'research_finding_version',id:'finding-v1',setId:'set'}}/>)
 await screen.findByText(/旧研究发现.*v1/)
 fireEvent.click(screen.getByRole('button',{name:'添加此固定成果'}))
 expect(JSON.parse(sessionStorage.getItem(draftKey)!).finding_version_ids).toEqual(['finding-v1'])
 expect((screen.getByRole('button',{name:'预览写作材料'}) as HTMLButtonElement).disabled).toBe(false)
})
it('pins the chosen manuscript base across refreshed revisions until the user explicitly adopts the new base',async()=>{
 sessionStorage.setItem(draftKey,JSON.stringify(oldDraft))
 const v1={...manuscriptFixture.versions[0],snapshot:{...snapshotFixture,research_bridge:{delivery_id:'d1'}}}
 let current={...manuscriptFixture,versions:[v1]}
 const fetcher=fixtureFetch(()=>({items:[current]}));vi.stubGlobal('fetch',fetcher)
 render(<ResearchWritingHandoff {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'写作设置'}))
 await screen.findByRole('option',{name:/Saved draft/})
 fireEvent.change(screen.getByLabelText('要继续编辑的论文'),{target:{value:'m1'}})
 fireEvent.click(screen.getByRole('button',{name:'预览写作材料'}))
 await screen.findByRole('button',{name:'整理结果与方法，等待核对'})
 current={...current,current_revision:2,versions:[v1,{...v1,id:'v2',revision:2}]}
 fireEvent.click(screen.getByRole('button',{name:'刷新材料列表'}))
 fireEvent.click(screen.getByRole('button',{name:'写作设置'}))
 const notice=await screen.findByText('稿件已有更新；当前草稿仍固定原基础版本，请比较后再采用新版。')
 expect(notice).toBeTruthy()
 expect(screen.queryByRole('button',{name:'整理结果与方法，等待核对'})).toBeNull()
 expect(JSON.parse(sessionStorage.getItem(draftKey)!).base).toEqual({id:'v1',revision:1})
 expect((screen.getByRole('button',{name:'预览写作材料'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'采用当前基础版本'}))
 fireEvent.click(screen.getByRole('button',{name:'预览写作材料'}))
 await waitFor(()=>expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/writing-selection'))).toHaveLength(2))
 const payloads=fetcher.mock.calls.filter(([url])=>url.endsWith('/writing-selection')).map(([,init])=>JSON.parse(init!.body as string))
 expect(payloads.map(p=>[p.base_version_id,p.expected_revision])).toEqual([['v1',1],['v2',2]])
 expect(payloads[1].manual_notes).toBe('保留的备注')
})
it('opens the exact previously published candidate version on the first click without publishing again',async()=>{
 const candidate={id:'c1',delivery_id:'d1',task_id:'t1',task:{id:'t1',status:'succeeded'},candidate:snapshotFixture,candidate_sha256:'a'.repeat(64),expected_revision:0,published_version_id:'v1'}
 const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/manuscripts')?{items:[{...manuscriptFixture,current_revision:2,versions:[...manuscriptFixture.versions,{...manuscriptFixture.versions[0],id:'v2',revision:2}]}]}:candidate));vi.stubGlobal('fetch',fetcher)
 const onPublished=vi.fn();render(<ResearchCandidateReview projectId="p1" candidateId="c1" active onPublished={onPublished}/>)
 fireEvent.click(await screen.findByRole('button',{name:'打开正式稿件'}))
 await waitFor(()=>expect(onPublished).toHaveBeenCalledWith('m1',1))
 expect(fetcher.mock.calls.every(([url])=>!url.endsWith('/publish'))).toBe(true)
})

it('keeps writing notes and pending selections mounted across module switches',async()=>{
 const fetcher=fixtureFetch();vi.stubGlobal('fetch',fetcher);render(<ResearchWritingHandoff {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'写作设置'}));fireEvent.change(screen.getByLabelText('人工补充说明'),{target:{value:'未提交的写作说明'}})
 fireEvent.click(screen.getByRole('button',{name:'写作材料'}));fireEvent.click(screen.getByRole('button',{name:'合并预览'}));fireEvent.click(screen.getByRole('button',{name:'写作设置'}));expect(screen.getByLabelText('人工补充说明')).toHaveProperty('value','未提交的写作说明');expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})
