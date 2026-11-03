import {StrictMode} from 'react'
import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ResearchIntake from './ResearchIntake'
import {apiFetch} from '../../shared/api/client'
import {emptyRequirement} from './state'
import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();vi.useRealTimers()})
it('fills the provided figure placeholder when an existing image is selected and preserves its notes',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST'){const body=JSON.parse(String(init.body));return Response.json({revision:1,version:{id:'v1',version:1,operation:'save',content:body.content,material_refs:body.material_refs},gaps:[]})}
  if(String(url).endsWith('/research-intake'))return Response.json({revision:0,current_requirement:null,current_design:null,deliveries:[{active:true,kind:'analysis'}],capabilities:{},gaps:[]})
  return Response.json(String(url).endsWith('/files')?[{id:'image1',filename:'已有图.png',file_type:'png'}]:{items:[],total:0})
 })
 render(<ResearchIntake projectId="p1" active view="requirements"/>);await screen.findByText('尚未保存版本')
 fireEvent.click(screen.getByRole('button',{name:'图表与交付'}));fireEvent.change(screen.getByRole('combobox',{name:'已有图表'}),{target:{value:'provided'}})
 fireEvent.change(screen.getByLabelText('材料定位说明'),{target:{value:'图1A，保留定位'}})
 fireEvent.click(screen.getByText('已有图像来源'));fireEvent.click(screen.getByLabelText('已有图.png'))
 expect(screen.getAllByRole('combobox',{name:'来源文件或数据集版本'})).toHaveLength(1)
 expect((screen.getByRole('combobox',{name:'来源文件或数据集版本'}) as HTMLSelectElement).value).toBe('file:image1')
 fireEvent.click(screen.getByRole('button',{name:'保存新版本'}));await screen.findByText('需求已保存。')
 const post=vi.mocked(apiFetch).mock.calls.find(([,init])=>init?.method==='POST')!
 expect(JSON.parse(String(post[1]?.body)).material_refs).toEqual([expect.objectContaining({purpose:'figures',availability:'provided',file_id:'image1',locator:'图1A，保留定位'})])
})
it('guides provided materials to an explicit file without posting incomplete references or losing the draft',async()=>{
 const root={revision:0,current_requirement:null,current_design:null,deliveries:[{active:true,kind:'analysis'}],capabilities:{},gaps:[]},onContinue=vi.fn()
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST'){const body=JSON.parse(String(init.body));return Response.json({revision:1,version:{id:'v1',version:1,operation:'save',content:body.content,material_refs:body.material_refs},gaps:[]})}
  if(String(url).endsWith('/research-intake'))return Response.json(root)
  return Response.json(String(url).endsWith('/files')?[{id:'f1',filename:'示例分组表.xlsx'}]:{items:[],total:0})
 })
 render(<ResearchIntake projectId="p1" active view="requirements" onContinue={onContinue}/>);await screen.findByText('尚未保存版本')
 fireEvent.click(screen.getByRole('button',{name:'图表与交付'}))
 fireEvent.change(screen.getByLabelText('补充说明'),{target:{value:'保留我的需求'}})
 fireEvent.change(screen.getByRole('combobox',{name:'样本信息表'}),{target:{value:'provided'}})
 const source=screen.getByRole('combobox',{name:'来源文件或数据集版本'}) as HTMLSelectElement
 expect(source.value).toBe('');expect((screen.getByRole('combobox',{name:'材料用途'}) as HTMLSelectElement).value).toBe('sample_sheet')
 fireEvent.click(screen.getByRole('button',{name:'保存需求，进入分析'}))
 expect(screen.getByRole('alert').textContent).toContain('选择对应文件或数据集')
 expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
 expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).value).toBe('保留我的需求')
 fireEvent.change(source,{target:{value:'file:f1'}})
 fireEvent.change(screen.getByRole('combobox',{name:'样本信息表'}),{target:{value:'pending'}})
 fireEvent.change(screen.getByRole('combobox',{name:'样本信息表'}),{target:{value:'provided'}})
 expect(screen.getAllByRole('combobox',{name:'来源文件或数据集版本'})).toHaveLength(1)
 expect(source.value).toBe('file:f1')
 fireEvent.click(screen.getByRole('button',{name:'保存需求，进入分析'}));await waitFor(()=>expect(onContinue).toHaveBeenCalledWith(['analysis']))
 const posts=vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST');expect(posts).toHaveLength(1)
 expect(JSON.parse(String(posts[0][1]?.body))).toMatchObject({content:{notes:'保留我的需求'},material_refs:[{purpose:'sample_sheet',availability:'provided',file_id:'f1'}]})
})
it('continues only after the server saves requirements and passes the selected services',async()=>{
 const onContinue=vi.fn(),content={...emptyRequirement(),services:['sci_draft']},version={id:'v1',version:1,operation:'save',content,sha256:'a'.repeat(64),created_at:'2026-11-02T00:00:00Z'}
 let finish!:(response:Response)=>void
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST')return new Promise<Response>(resolve=>{finish=resolve})
  if(String(url).endsWith('/research-intake'))return Response.json({revision:0,current_requirement:{...version},current_design:null,deliveries:[],capabilities:{},gaps:[]})
  return Response.json(String(url).endsWith('/files')?[]:{items:[],total:0})
 })
 render(<ResearchIntake projectId="p1" active view="requirements" onContinue={onContinue}/>);await screen.findByText('已保存')
 fireEvent.click(screen.getByRole('button',{name:'保存需求，进入写作'}));expect(onContinue).not.toHaveBeenCalled()
 await act(async()=>finish(Response.json({revision:1,version,gaps:[]})))
 expect(onContinue).toHaveBeenCalledWith(['sci_draft'])
 expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
})
it('keeps a twenty-second save pending and accepts its confirmed version without another POST',async()=>{
 vi.useFakeTimers();let saved=false,signal!:AbortSignal;const root={project_id:'p1',revision:0,current_requirement:null,current_design:null,deliveries:[],capabilities:{},gaps:[]},version={id:'v1',version:1,operation:'save',content:{...emptyRequirement(),notes:'Slow retained draft'},sha256:'a'.repeat(64),created_at:'2026-10-30T00:00:00Z'}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{if(init?.method==='POST'){signal=init.signal!;return new Promise<Response>((resolve,reject)=>{const timer=window.setTimeout(()=>{saved=true;resolve(Response.json({revision:1,version,gaps:[]}))},20000);signal.addEventListener('abort',()=>{window.clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))},{once:true})})}if(String(url).endsWith('/research-intake'))return Response.json(saved?{...root,revision:1,current_requirement:version}:root);return Response.json(String(url).endsWith('/files')?[]:{items:[],total:0})})
 render(<ResearchIntake projectId="p1" active view="requirements"/>);await act(async()=>{});fireEvent.change(screen.getByLabelText('补充说明'),{target:{value:'Slow retained draft'}});fireEvent.click(screen.getByText('保存新版本'));await act(()=>vi.advanceTimersByTimeAsync(16000));expect(signal.aborted).toBe(false);expect(screen.getByRole('button',{name:'保存新版本'}).hasAttribute('disabled')).toBe(true);expect(screen.queryByText('核对保存结果')).toBeNull();await act(()=>vi.advanceTimersByTimeAsync(4000));expect(screen.getByText('需求已保存。')).toBeDefined();expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).value).toBe('Slow retained draft');expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
})
it('retains the original save body and key after the final bound and explicit recovery read',async()=>{
 vi.useFakeTimers();let posts=0;const root={project_id:'p1',revision:0,current_requirement:null,current_design:null,deliveries:[],capabilities:{},gaps:[]},version={id:'v1',version:1,operation:'save',content:emptyRequirement(),sha256:'a'.repeat(64),created_at:'2026-10-30T00:00:00Z'}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{if(init?.method==='POST')return ++posts===1?new Promise<Response>((_resolve,reject)=>init.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true})):Response.json({revision:1,version,gaps:[]});if(String(url).includes('/requests/'))return Response.json({detail:{code:'not_found'}},{status:404});if(String(url).endsWith('/research-intake'))return Response.json(root);return Response.json(String(url).endsWith('/files')?[]:{items:[],total:0})})
 render(<ResearchIntake projectId="p1" active view="requirements"/>);await act(async()=>{});fireEvent.click(screen.getByText('保存新版本'));await act(()=>vi.advanceTimersByTimeAsync(STANDARD_REQUEST_TIMEOUT_MS));expect(screen.getByRole('button',{name:'核对保存结果'})).toBeDefined();fireEvent.click(screen.getByRole('button',{name:'核对保存结果'}));await act(async()=>{});expect(posts).toBe(1);fireEvent.click(screen.getByRole('button',{name:'按原请求再次核对'}));await act(async()=>{});const calls=vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST');expect(calls).toHaveLength(2);expect(calls[1][1]?.body).toBe(calls[0][1]?.body);expect(new Headers(calls[1][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[0][1]?.headers).get('Idempotency-Key'))
})
it('preserves local draft on conflict and reads a specific immutable historical version',async()=>{
 const root={project_id:'p1',revision:1,current_requirement:null,current_design:null,deliveries:[],capabilities:{},gaps:[]};const version={id:'v1',version:1,operation:'save',content:{...emptyRequirement(),notes:'History'},sha256:'a'.repeat(64),created_at:'2026-10-29T00:00:00Z'}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{const path=String(url);if(init?.method==='POST')return Response.json({detail:{code:'research_intake_revision_conflict'}},{status:409});if(path.endsWith('/research-intake'))return Response.json(root);if(path.endsWith('/files'))return Response.json([]);if(path.endsWith('/requirements/v1'))return Response.json(version);return Response.json({items:[version],total:1})})
 render(<StrictMode><ResearchIntake projectId="p1" active view="requirements"/></StrictMode>);await screen.findByText('尚未保存版本');fireEvent.change(screen.getByLabelText('补充说明'),{target:{value:'My draft'}});fireEvent.click(screen.getByText('保存新版本'));await screen.findByText('服务器已有新版本，草稿已保留。重新读取后核对并合并，再保存。');expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).value).toBe('My draft');fireEvent.click(screen.getByText(/版本 1 ·/));await waitFor(()=>expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).value).toBe('History'));expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).disabled).toBe(true);fireEvent.click(screen.getByText('返回当前草稿'));expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).value).toBe('My draft')
})
