import {useState} from 'react'
import {cleanup,render,screen,fireEvent,within,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import ResearchWorkspace from './ResearchWorkspace'
import {ProjectResultActions} from '../projects/ProjectJourney'
import type {AnalysisNavigation,ArtifactNavigation} from '../projects/analysisViews'
import type {ManuscriptView} from '../projects/manuscriptViews'
import type {ProjectSection} from '../projects/WorkspaceShell'
import {snapshotFixture,manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import {translateForLocale} from '../../shared/i18n'
const fact={id:'fact',source_kind:'bio_processed_dataset_version',source_id:'processed',source_sha256:'a'.repeat(64),locator:{kind:'field',field_path:'summary.n_spots'},raw_value:42,display_value:'42',unit:'spots',observation_level:'spot',comparison:'',verification_status:'verified',origin:'system_computed',limitations:[]}
const source={source_kind:'bio_processed_dataset_version',source_id:'processed',locator:{kind:'object'},sha256:'a'.repeat(64)}
const content={title:'Fixed findings',sources:[source],facts:[fact],methods:[],claims:[],conflicts:[],reviews:[],limitations:['区域富集并非纯细胞结论'],gaps:['donor metadata pending'],warnings:[],notes:''}
const finding={id:'finding',set_id:'set',revision:1,parent_id:null,content,sha256:'b'.repeat(64)}
const snapshot={...snapshotFixture,research_bridge:{delivery_id:'sci',document_kind:'sci'},research_gaps:['donor metadata pending']}
function Harness(){const[section,setSection]=useState<ProjectSection>('analysis'),[analysis,setAnalysis]=useState<AnalysisNavigation>({view:'research-findings',fileId:'',processedId:'processed'}),[artifact,setArtifact]=useState<ArtifactNavigation>({view:'list',artifactId:'',kind:'',page:1}),[view,setView]=useState<ManuscriptView>('research-selection'),[candidate,setCandidate]=useState(''),[selected,setSelected]=useState({id:'',revision:0});return <><ResearchWorkspace projectId="p1" projectType="research" active section={section} analysis={analysis} artifact={artifact} manuscriptView={view} candidateId={candidate} manuscriptId={selected.id} revision={selected.revision} onAnalysis={v=>{setAnalysis(v);setSection('analysis')}} onArtifact={v=>{setArtifact(v);setSection('artifacts')}} onManuscriptView={v=>{setView(v);setSection('manuscripts')}} onCandidate={id=>{setCandidate(id);setView('research-candidates');setSection('manuscripts')}} onPublished={(id,revision)=>{setSelected({id,revision});setView('body');setSection('manuscripts')}} schoolNavigation={{view:'list',templateId:''}} onSchoolNavigate={vi.fn()}/>{section==='artifacts'&&<ProjectResultActions projectType="research" onWriting={()=>{setView('research-selection');setSection('manuscripts')}} onExistingManuscripts={()=>{setView('list');setSection('manuscripts')}} onDeliveries={vi.fn()} onExit={vi.fn()}/>}</>}
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear()});afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession()})
it('connects fixed processed facts to report, delivery preview, candidate review and public manuscript',async()=>{
 let saved=false,reportSaved=false,published=false;const posts:{url:string;body:Record<string,unknown>;key:string|null}[]=[]
 const report={id:'report',root_id:'report',revision:1,parent_id:null,content:{title:'Result package',language:'zh-CN',finding,figures:[],tables:[{key:'markers',expected_rows:9,sha256:'c'.repeat(64)}]},task_id:'report-task',task:{id:'report-task',status:'succeeded'},members:[],manifest:null}
 const candidate=()=>({id:'candidate',delivery_id:'sci',task_id:'candidate-task',task:{id:'candidate-task',status:'succeeded'},candidate:snapshot,candidate_sha256:'d'.repeat(64),manuscript_id:null,base_version_id:null,expected_revision:0,published_version_id:published?'published-version':null})
 const manuscript={...manuscriptFixture,id:'manuscript',title:'Published research',versions:[{...manuscriptFixture.versions[0],id:'published-version',revision:1,snapshot,input:{schema_version:2,kind:'research_results_methods',candidate_id:'candidate',delivery_id:'sci',expected_revision:0,title:'Published research',output_language:'zh-CN',thesis:null}}]}
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  const path=url.split('/projects/p1')[1]??''
  if(init?.method==='POST'){const body=JSON.parse(String(init.body));posts.push({url:path,body,key:new Headers(init.headers).get('Idempotency-Key')});if(path==='/research-results/preview')return Response.json({catalogs:[{source:{...source,title:'Processed'},facts:[fact],methods:[],gaps:[],warnings:[],limitations:[],conflicts:[]}]});if(path==='/research-findings'){saved=true;return Response.json(finding)}if(path==='/research-reports'){reportSaved=true;return Response.json(report)}if(path==='/research-results/writing-selection')return Response.json({merge_preview:snapshot,selected_source_ids:['finding'],selection_sha256:'e'.repeat(64)});if(path==='/research-manuscript-candidates')return Response.json(candidate());if(path.endsWith('/publish')){published=true;return Response.json({manuscript_id:'manuscript',version_id:'published-version',revision:1,candidate_id:'candidate'})}}
  if(path==='/research-intake')return Response.json({deliveries:[{id:'sci',kind:'sci_draft',name:'SCI delivery',active:true}]})
  if(path.startsWith('/research-results/writing-config'))return Response.json({document_context:{document_kind:'sci',delivery_id:'sci'},thesis:null})
  if(path==='/research-findings')return Response.json({items:saved?[{id:'set',title:content.title,revision:1,current_version_id:'finding'}]:[]})
  if(path.includes('/research-findings/set/versions/'))return Response.json(finding)
  if(path==='/research-reports/report')return Response.json(report)
  if(path.startsWith('/research-reports?'))return Response.json({items:reportSaved?[report]:[],total:reportSaved?1:0,page:1,page_size:20})
  if(path.startsWith('/research-manuscript-candidates/'))return Response.json(candidate())
  if(path==='/manuscripts/manuscript')return Response.json(manuscript)
  if(path==='/manuscripts')return Response.json({items:published?[manuscript]:[]})
  return Response.json({items:[],total:0,page:1,page_size:25})
 }))
 render(<Harness/>);const findings=screen.getByRole('heading',{name:'研究发现与人工核对'}).closest('section')!
 fireEvent.change(within(findings).getByLabelText('发现集合标题'),{target:{value:'Fixed findings'}});fireEvent.click(within(findings).getByRole('button',{name:'读取可引用事实与方法'}));await within(findings).findByRole('checkbox',{name:'选择事实 42'});fireEvent.click(within(findings).getByRole('button',{name:'保存研究发现版本'}));await within(findings).findByRole('button',{name:'Fixed findings · v1'})
 expect(posts.find(p=>p.url==='/research-findings')?.body.sources).toMatchObject([{source_kind:'bio_processed_dataset_version',source_id:'processed',locator:{kind:'object'}}]);expect(posts.find(p=>p.url==='/research-findings')?.key).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'分析报告与成果包'}));fireEvent.click(screen.getByRole('button',{name:'新建研究报告'}));const reportPanel=screen.getByRole('heading',{name:'分析报告与成果包'}).closest('section')!;await waitFor(()=>expect(within(reportPanel).getByLabelText('固定发现版本').querySelector('option[value="finding"]')).not.toBeNull());fireEvent.change(within(reportPanel).getByLabelText('报告标题'),{target:{value:'Result package'}});fireEvent.change(within(reportPanel).getByLabelText('固定发现版本'),{target:{value:'finding'}});fireEvent.click(within(reportPanel).getByRole('button',{name:'下一步：确认生成'}));fireEvent.click(within(reportPanel).getByRole('button',{name:'生成固定报告与成果包'}));fireEvent.click(await within(reportPanel).findByRole('button',{name:'来源与方法'}));await within(reportPanel).findByText(/结果表 1.*9/)
 fireEvent.click(screen.getByRole('button',{name:'继续写 SCI 论文'}));fireEvent.change(await screen.findByLabelText('已启用的稿件交付'),{target:{value:'sci'}});fireEvent.click(await screen.findByRole('checkbox',{name:'Fixed findings · v1'}));fireEvent.click(screen.getByRole('button',{name:'添加选中的材料'}));fireEvent.click(screen.getByRole('button',{name:'预览写作材料'}));await screen.findByRole('button',{name:'整理结果与方法，等待核对'});expect(screen.queryByText('e'.repeat(64),{exact:false})).toBeNull();fireEvent.click(screen.getByRole('button',{name:'整理结果与方法，等待核对'}));await screen.findByRole('heading',{name:'结果与方法候选核对'});fireEvent.click(await screen.findByRole('checkbox',{name:/我已核对候选/}));fireEvent.click(screen.getByRole('button',{name:'显式发布为正式稿件版本'}));fireEvent.click(await screen.findByRole('button',{name:'打开正式稿件'}));await screen.findByRole('option',{name:'Published research'})
 expect(posts.find(p=>p.url==='/research-manuscript-candidates')?.body).toMatchObject({delivery_id:'sci',finding_version_ids:['finding'],expected_revision:0,sections:['results','materials_and_methods']});expect(posts.filter(p=>p.url.endsWith('/publish'))).toHaveLength(1)
})
it('uses the existing English localization mechanism for the research workflow',()=>{
 for(const key of ['研究发现与人工核对','固定研究来源','研究单图与组图','分析报告与原始结果包','研究成果写作材料','结果与方法候选核对','显式发布为正式稿件版本','研究发现固定版本','发布结果未知，请先回读候选，不重复提交。'])expect(translateForLocale(key,'en')).not.toMatch(/[\u4e00-\u9fff]/)
})

it('localizes the fixed-source, manuscript and Word handoff labels',()=>{
 for(const key of ['用于写作','入口带来的固定成果','待添加的固定成果','此固定成果已在当前交付草稿中。','此来源尚不可用于写作，请返回固定成果核对。','添加后与已有材料合并，保留当前备注和章节选择。','添加此固定成果','返回来源成果','当前基础稿件预览','当前稿件版本','采用当前基础版本','稿件已有更新；当前草稿仍固定原基础版本，请比较后再采用新版。','请先选择研究发现或分析报告，研究图作为补充材料。','当前为 Results / Methods 事实稿版本；需要完整论文可继续完整稿件写作。','当前稿件已按章节组织，请核对正文完整性。','查看此版本的 Word','查看版本 {number} 的 Word','Word 正在生成，请等待任务完成。','事实稿 Word · 版本 {number}','完整稿 Word · 版本 {number}','当前版本尚未生成 Word。','毕业论文 Word · 版本 {number}','进入当前项目交付登记（选择已有成果）'])expect(translateForLocale(key,'en')).not.toMatch(/[\u4e00-\u9fff]/)
})

it('localizes source updates and interrupted manuscript recovery',()=>{
 for(const key of ['尚未检查来源更新。','发现更新版本，当前仍使用已选固定版本。','引用关系不表示成果失效。','引用列表未列全。','查看新版报告','稿件历史读取失败，请重试。','返回稿件写作','Word 提交结果待核对，原请求和固定输入已保留。','用原请求重试 Word','任务状态已推进，请按当前任务状态继续处理。','使用原预览请求重试','相同写作任务正在排队或运行，请查看原任务。'])expect(translateForLocale(key,'en')).not.toMatch(/[\u4e00-\u9fff]/)
})
