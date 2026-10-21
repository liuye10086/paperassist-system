import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptReview from './ManuscriptReview'
import {reviewContext,reviewReport,reviewVersion,savedReview} from './reviewFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {setLocale} from '../../shared/i18n'

afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const props={projectId:'p1',manuscriptId:'m1',version:reviewVersion,currentRevision:1,onPublished:vi.fn()}

it.each([false,true])('retains uncertain create identity when GET finds another same-input review (changed sources: %s)',async(changed)=>{
 let listOther=false,retry=false
 const report={...reviewReport,source_changes:changed?[{id:'run1',kind:'analysis_run',reasons:['newer_analysis_run']}]:[]}
 const other={...savedReview,id:'other-tab-B',report,candidate:{...savedReview.candidate,review:{...savedReview.candidate.review!,report},review_provenance:{...savedReview.candidate.review_provenance,review_id:'other-tab-B'}}}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){if(!retry)throw Error('unknown A');return Response.json(savedReview)}
  return Response.json(url.includes('/context?')?reviewContext:{items:listOther?[other]:[]})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptReview {...props}/>);await screen.findByLabelText('问题类别');fireEvent.click(screen.getByRole('button',{name:'生成检查候选'}));await screen.findByRole('button',{name:'使用原请求重试'})
 listOther=true;fireEvent.click(screen.getByRole('button',{name:'回读检查记录'}));await screen.findByRole('button',{name:'查看检查记录 1'});await waitFor(()=>expect(screen.queryByText('正在读取研究资料……')).toBeNull())
 expect(screen.getByRole('button',{name:'使用原请求重试'})).toBeTruthy();expect(screen.getByRole('button',{name:'生成检查候选'}).matches(':disabled')).toBe(true);expect(screen.getByRole('button',{name:'查看检查记录 1'}).matches(':disabled')).toBe(true);expect(screen.queryByRole('region',{name:'资料检查候选预览'})).toBeNull()
 retry=true;fireEvent.click(screen.getByRole('button',{name:'使用原请求重试'}));await screen.findByRole('region',{name:'资料检查候选预览'});expect(screen.queryByRole('button',{name:'使用原请求重试'})).toBeNull()
 const posts=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');expect(posts).toHaveLength(2);expect(posts[0][1]?.body).toBe(posts[1][1]?.body);expect(new Headers(posts[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(posts[1][1]?.headers).get('Idempotency-Key'));expect(screen.getByRole('button',{name:'确认保存检查为新版本'}).matches(':disabled')).toBe(false)
})

it('distinguishes equal facts from identically named sources by frozen version and full fact identity',async()=>{
 const source1={...reviewVersion.snapshot.sources[0],content:{overall:{mean:27.555},setup_revision:3}},source2={...source1,id:'run2',file_id:'file2'}
 const version={...reviewVersion,snapshot:{...reviewVersion.snapshot,sources:[source1,source2],results_groups:reviewVersion.snapshot.results_groups.map(g=>({...g,paragraphs:g.paragraphs.map(p=>({...p,source_ids:['run1','run2']}))}))}}
 const context={...reviewContext,facts:[reviewContext.facts[0],{...reviewContext.facts[0],id:'analysis_run:run2:/overall/mean',source_id:'run2'}],relationships:{...reviewContext.relationships,paragraphs:reviewContext.relationships.paragraphs.map(p=>p.id==='result:1'?{...p,source_ids:['run1','run2']}:p)}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/context?')?context:{items:[]})));render(<ManuscriptReview {...props} version={version}/>);await screen.findByLabelText('问题类别');fireEvent.click(screen.getByText('定向段落修正'));fireEvent.click(screen.getByText('段落 2 · 结果'));fireEvent.click(screen.getAllByRole('button',{name:'修正此段'})[1]);fireEvent.click(screen.getByRole('button',{name:'添加数字绑定'}))
 const options=within(screen.getByLabelText('数字对应事实 1')).getAllByRole('option').slice(1)
 expect(options).toHaveLength(2);expect(options[0].textContent).toContain('Measured signal');expect(options[0].textContent).toContain('分析配置版本 3');expect(options[0].textContent).toContain('analysis_run:run1:/overall/mean');expect(options[1].textContent).toContain('analysis_run:run2:/overall/mean');expect(options[0].textContent).not.toBe(options[1].textContent)
 fireEvent.change(screen.getByLabelText('原始来源（显式选择）'),{target:{value:'run2'}})
 const selectedSourceFacts=within(screen.getByLabelText('数字对应事实 1')).getAllByRole('option').slice(1)
 expect(selectedSourceFacts).toHaveLength(1);expect(selectedSourceFacts[0]).toHaveProperty('value','analysis_run:run2:/overall/mean')
})

it('locates an actual panel:<figure>:<index> issue at the correct panel text',async()=>{
 const figure={id:'fig1',number:1,title:'Signal figure',caption:'Signal',sha256:'a'.repeat(64),source_ids:['run1'],panels:[{label:'A',description:'Panel value 5'},{label:'B',description:'Second observation'}]},version={...reviewVersion,snapshot:{...reviewVersion.snapshot,results_groups:reviewVersion.snapshot.results_groups.map(g=>({...g,figures:[figure]}))}}
 const context={...reviewContext,relationships:{...reviewContext.relationships,figures:[{id:'fig1',source_ids:['run1']}]},issues:[{...reviewContext.issues[0],id:'numeric:panel:fig1:0',category:'numeric',location:'panel:fig1:0',message:'Panel number needs checking'}]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/context?')?context:{items:[]})));render(<ManuscriptReview {...props} version={version}/>);await screen.findByLabelText('问题类别');fireEvent.click(screen.getByRole('button',{name:'定位资料'}));expect((document.activeElement as HTMLElement).dataset.reviewLocation).toBe('panel:fig1:0');expect(document.activeElement?.textContent).toContain('Panel value 5')
})

it('shows frozen research-question and NA confirmations without copying them into a new decision draft',async()=>{
 const record={reason:'Checked signed protocol',evidence:'Original record',scientifically_verified:false as const,created_by:'u1',created_at:'2026-10-20T00:00:00Z',base_revision:1,source_versions:[]}
 const decisions=[{...record,target_id:'missing:research_question',status:'supplied' as const,value:'Explicitly confirmed research question'},{...record,target_id:'missing:hypothesis',status:'not_applicable' as const,value:''}]
 const version:ManuscriptVersion={...reviewVersion,snapshot:{...reviewVersion.snapshot,methods:[],issues:[{id:'missing:hypothesis',kind:'missing',field:'hypothesis',message:'Hypothesis originally missing',values:[]}],review:{...savedReview.candidate.review!,decisions}}}
 const context={...reviewContext,relationships:{...reviewContext.relationships,research_question:'',methods:[],paragraphs:reviewContext.relationships.paragraphs.filter(p=>p.id==='result:1')},issues:[{...reviewContext.issues[0],id:'material:missing:hypothesis',location:'missing:hypothesis',message:'Hypothesis originally missing'}]}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...savedReview,input:JSON.parse(String(init.body))}:url.includes('/context?')?context:{items:[]}));vi.stubGlobal('fetch',fetcher);render(<ManuscriptReview {...props} version={version}/>);await screen.findByLabelText('问题类别')
 const summary=screen.getByRole('region',{name:'当前版本已冻结的确认'});expect(within(summary).getByText('Explicitly confirmed research question')).toBeTruthy();expect(within(summary).getByText('不适用')).toBeTruthy();expect(within(screen.getByTestId('review-study-question')).getByText('Explicitly confirmed research question')).toBeTruthy()
 const group=screen.getByRole('group',{name:'研究假设 · 本次新增处理'});expect(within(group).getByText('既有冻结状态')).toBeTruthy();expect(within(group).getByText('不适用',{selector:'span'})).toBeTruthy();expect(within(group).getByLabelText('处理状态')).toHaveProperty('value','');expect(within(group).getByText('本次不新增处理')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'生成检查候选'}));await waitFor(()=>expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));const post=fetcher.mock.calls.find(([,init])=>init?.method==='POST')!;expect(JSON.parse(String(post[1]?.body)).decisions).toEqual([])
})
