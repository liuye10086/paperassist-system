import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {useState} from 'react'
import ResearchSourceChanges from '../research-results/ResearchSourceChanges'
import ResearchCandidateReview from '../research-results/ResearchCandidateReview'
import ResearchPublished from '../research-results/ResearchPublished'
import ResearchWorkspace from '../research-results/ResearchWorkspace'
import {parseNavigation,serializeNavigation} from './projectNavigation'
import {manuscriptFixture,snapshotFixture,exportFixture} from '../manuscripts/manuscriptFixtures'
import {setApiSession} from '../../shared/api/client'
import type {ManuscriptView} from './manuscriptViews'

const project='p1',base=`/api/v1/projects/${project}`
const source={source_kind:'research_report_version' as const,source_id:'report-v1',locator:{kind:'object' as const}}
const version1={...manuscriptFixture.versions[0],snapshot:snapshotFixture,exports:[]}
const version2={...version1,id:'v2',revision:2,parent_version_id:'v1'}
const manuscript={...manuscriptFixture,current_revision:2,versions:[version1,version2]}
const candidate={id:'c1',delivery_id:'sci-delivery',task:{id:'task-candidate',status:'succeeded'},task_id:'task-candidate',candidate:snapshotFixture,candidate_sha256:'a'.repeat(64),manuscript_id:'m1',base_version_id:'v1',expected_revision:1,published_version_id:'v1'}
function Flow({initial='source'}:{initial?:'source'|'candidate'|'published'}){
 const [stage,setStage]=useState(initial),[id,setId]=useState(initial==='published'?'m1':''),[revision,setRevision]=useState(initial==='published'?1:0),[view,setView]=useState<ManuscriptView>(initial==='published'?'exports':'body')
 return <>{stage==='source'&&<><ResearchSourceChanges projectId={project} sources={[source]}/><button onClick={()=>setStage('candidate')}>打开已有候选 c1</button></>}{stage==='candidate'&&<ResearchCandidateReview projectId={project} candidateId="c1" active onPublished={(m,r)=>{setId(m);setRevision(r);setView('body');setStage('published')}}/>}{stage==='published'&&<ResearchPublished projectId={project} active manuscriptId={id} revision={revision} view={view} onView={setView} onSelect={(m,r,v)=>{setId(m);setRevision(r);setView(v??'body')}}/>}</>
}
const finding={id:'finding-v1',set_id:'set',revision:1,content:{title:'固定发现',sources:[],facts:[],methods:[],claims:[],conflicts:[],reviews:[],limitations:[],gaps:[],warnings:[],notes:''}}
const report={id:'report-v1',root_id:'report',revision:1,task:{id:'task-report',status:'succeeded'},task_id:'task-report',content:{title:'固定分析报告',language:'zh-CN',finding,figures:[],tables:[]},members:[],manifest:null}
const startHash='#project=p1&section=artifacts&view=research-reports&artifact=report-v1'
function WorkspaceFlow({initial=startHash}:{initial?:string}){
 const [route,setRoute]=useState(()=>parseNavigation(initial)!)
 function nav(patch:Partial<typeof route>){setRoute(old=>{const next={...old,...patch};window.history.replaceState(null,'',`/${serializeNavigation(next)}`);return next})}
 return <ResearchWorkspace projectId="p1" projectType="research" active section={route.section} analysis={route.analysisNavigation} artifact={route.artifactNavigation} manuscriptView={route.manuscriptView} manuscriptId={route.manuscriptLink.id} revision={route.manuscriptLink.revision} candidateId={route.researchCandidateId} writingSource={route.writingSource} writingDeliveryId={route.writingDeliveryId} onWritingSource={writingSource=>nav({section:'manuscripts',manuscriptView:'research-selection',writingSource})} onWritingDelivery={writingDeliveryId=>nav({writingDeliveryId})} onAnalysis={analysisNavigation=>nav({section:'analysis',analysisNavigation})} onArtifact={artifactNavigation=>nav({section:'artifacts',artifactNavigation})} onManuscriptView={manuscriptView=>nav({section:'manuscripts',manuscriptView})} onCandidate={researchCandidateId=>nav({section:'manuscripts',manuscriptView:'research-candidates',researchCandidateId})} onPublished={(id,revision,view='body')=>nav({section:'manuscripts',manuscriptView:view,manuscriptLink:{id,revision}})} schoolNavigation={{view:'list',templateId:''}} onSchoolNavigate={()=>{}}/>
}
afterEach(()=>{cleanup();sessionStorage.clear();vi.unstubAllGlobals()})
it('carries a fixed report into the selected delivery and restores its material draft',async()=>{
 setApiSession('flow-fixture','flow-owner')
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>{
  const path=url.split('?')[0]
  if(path===`${base}/research-results/writing-selection`)return Response.json({merge_preview:snapshotFixture,selected_source_ids:['report-v1'],selection_sha256:'b'.repeat(64)})
  if(path===`${base}/research-intake`)return Response.json({deliveries:[{id:'sci-delivery',kind:'sci_draft',active:true}]})
  if(path===`${base}/research-results/writing-config`)return Response.json({document_context:{document_kind:'sci',delivery_id:'sci-delivery'},thesis:null})
  if(path===`${base}/research-reports/report-v1`)return Response.json(report)
  if(path===`${base}/research-reports`)return Response.json({items:[report],total:1,page:1,page_size:20})
  if(path===`${base}/manuscripts`)return Response.json({items:[manuscript]})
  if(path===`/api/v1/tasks/task-report/progress`)return Response.json({project_id:'p1',task_id:'task-report',task_type:'research_report',status:'succeeded',progress:null})
  return Response.json({items:[],total:0,page:1,page_size:25})
 });vi.stubGlobal('fetch',fetcher)
 const first=render(<WorkspaceFlow/>);fireEvent.click(await screen.findByRole('button',{name:'用于写作'}));fireEvent.change(await screen.findByLabelText('已启用的稿件交付'),{target:{value:'sci-delivery'}})
 fireEvent.click(await screen.findByRole('button',{name:'添加此固定成果'}));fireEvent.change(screen.getByLabelText('人工补充说明'),{target:{value:'固定报告的保留备注'}});expect(screen.getByText('此固定成果已在当前交付草稿中。')).toBeTruthy()
 const hash=window.location.hash;first.unmount();render(<WorkspaceFlow initial={hash}/>);expect((await screen.findByLabelText('人工补充说明') as HTMLTextAreaElement).value).toBe('固定报告的保留备注');expect(await screen.findByText('此固定成果已在当前交付草稿中。')).toBeTruthy()
 await waitFor(()=>expect((screen.getByRole('button',{name:'预览写作材料'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'预览写作材料'}));await screen.findByRole('button',{name:'整理结果与方法，等待核对'})
 const writes=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');expect(writes).toHaveLength(1);expect(writes[0][0]).toBe(`${base}/research-results/writing-selection`);const body=JSON.parse(String(writes[0][1]?.body));expect(body.delivery_id).toBe('sci-delivery');expect(body.report_version_ids).toEqual(['report-v1']);expect(body.manual_notes).toBe('固定报告的保留备注');expect(body.finding_version_ids).toEqual([])
})
it('keeps the fixed report and published v1 through a lost Word response and reload',async()=>{
 setApiSession('flow-fixture','flow-owner');let exports=0
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===`${base}/research-results/source-changes`)return Response.json({items:[{source_kind:source.source_kind,source_id:source.source_id,sha256:'x',fixed_source_unchanged:true,newer_version_id:'report-v2',newer_revision:2,affected:[],affected_truncated:false,automatic_replacement:false}]})
  if(url===`${base}/research-manuscript-candidates/c1`)return Response.json(candidate)
  if(url===`${base}/manuscripts/m1`)return Response.json(manuscript)
  if(url===`${base}/manuscripts`)return Response.json({items:[manuscript]})
  if(url===`${base}/manuscripts/m1/versions/1/exports`&&init?.method==='POST'){exports++;if(exports===1)throw new TypeError('lost response');return Response.json(exportFixture)}
  if(url===`${base}/manuscripts/m1/versions/1/exports`)return Response.json({items:exports>1?[exportFixture]:[]})
  return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetcher)
 const first=render(<Flow/>);fireEvent.click(screen.getByRole('button',{name:'检查固定来源更新与影响'}));expect(await screen.findByText(/发现更新版本，当前仍使用已选固定版本/)).toBeTruthy()
 const check=fetcher.mock.calls.find(([url])=>url.endsWith('/source-changes'))!;expect(JSON.parse(String(check[1]?.body)).sources).toEqual([{...source,schema_version:1}])
 fireEvent.click(screen.getByRole('button',{name:'打开已有候选 c1'}));await screen.findByText(/已发布固定稿件版本/);fireEvent.click(screen.getByRole('button',{name:'打开正式稿件'}));expect(await screen.findByText(/固定稿件版本：.*版本 1/)).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'查看此版本的 Word'}));fireEvent.click(await screen.findByRole('button',{name:'生成 DOCX'}));await screen.findByText('Word 提交结果待核对，原请求和固定输入已保留。');first.unmount()
 render(<Flow initial="published"/>);await screen.findByText('Word 提交结果待核对，原请求和固定输入已保留。');expect(exports).toBe(1);fireEvent.click(screen.getByRole('button',{name:'刷新 DOCX 状态'}));expect(exports).toBe(1);fireEvent.click(screen.getByRole('button',{name:'用原请求重试 Word'}));await screen.findByRole('link',{name:'下载 DOCX'})
 const writes=fetcher.mock.calls.filter(([url,init])=>url.includes('/versions/')&&init?.method==='POST');expect(writes).toHaveLength(2);expect(writes.map(([url])=>url)).toEqual([`${base}/manuscripts/m1/versions/1/exports`,`${base}/manuscripts/m1/versions/1/exports`]);expect(writes[0][1]?.body).toBe(writes[1][1]?.body);const key=new Headers(writes[0][1]?.headers).get('Idempotency-Key');expect(key).toBeTruthy();expect(key).toBe(new Headers(writes[1][1]?.headers).get('Idempotency-Key'));expect(fetcher.mock.calls.filter(([url])=>url===`${base}/research-manuscript-candidates/c1`)).toHaveLength(2);expect(fetcher.mock.calls.filter(([url,init])=>url.includes('/publish')&&init?.method==='POST')).toHaveLength(0);await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url===`${base}/manuscripts/m1`)).toBe(true))
})
