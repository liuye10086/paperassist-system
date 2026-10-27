import {configurationButton,findConfigurationButton,configurationField} from './configurationTestNavigation'
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import ConfigurationsPanel from './ConfigurationsPanel'
import {categories,testCatalog,testValidation,testVersion} from './configurationTestFixtures'
import {clearApiSession,setApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
let revision=1,active='v1',pass=true,conflict=false,unknown=false
let versions:ReturnType<typeof testVersion>[],keys:string[]
let mock:ReturnType<typeof vi.fn>
const forbidden=vi.fn()
beforeEach(()=>{setApiSession('csrf','admin');revision=1;active='v1';pass=true;conflict=false;unknown=false;keys=[];versions=[testVersion()];forbidden.mockClear();mock=vi.fn(async(url:string,init?:RequestInit)=>{
 const base='/api/v1/admin/configurations',path=url.slice(base.length),body=init?.body?JSON.parse(init.body as string):{}
 if(path==='/current'){const value=versions.find(v=>v.id===active);return Response.json({revision,version:value?Object.fromEntries(Object.entries(value).filter(([key])=>key!=='validations')):null})}
 if(path==='/catalog')return Response.json(testCatalog)
 if(path==='/events')return Response.json({items:[{id:'e1',operation:'activate',reason:'Synthetic baseline',before_version_id:null,after_version_id:'v1',revision:1,created_at:'2026-10-25T00:00:00Z'}]})
 if(path==='')return Response.json({items:versions})
 if(path.startsWith('/bindings/'))return Response.json({status:'legacy_unbound',version_id:null,sha256:null})
 const id=path.split('/')[1]
 if(path.endsWith('/copy')){const value=testVersion('v2');versions.push(value);return Response.json(value)}
 if(path.endsWith('/save')){const value={...testVersion('v3'),bundle:body.bundle};versions.push(value);return Response.json(value)}
 if(path.includes('/diff'))return Response.json({version_id:id,against:'v1',changes:[{path:'basic.max_rows',before:100000,after:90000}]})
 if(path.endsWith('/validate'))return Response.json(testValidation(id,pass?'passed':'failed'))
 if(path.endsWith('/activate')||path.endsWith('/rollback')){keys.push(body.request_key);if(unknown){unknown=false;throw new TypeError('network')}if(conflict){conflict=false;revision=2;return Response.json({detail:{code:'configuration_revision_conflict',message:'SECRET'}},{status:409})}revision++;active=id;return Response.json({revision,version_id:id,sha256:'b'.repeat(64),operation:path.endsWith('/rollback')?'rollback':'activate'})}
 return Response.json(versions.find(v=>v.id===id))
 });vi.stubGlobal('fetch',mock)})
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
async function copy(){render(<ConfigurationsPanel onForbidden={forbidden}/>);fireEvent.click(await findConfigurationButton('复制为草稿'));await screen.findByText('草稿已建立。')}
async function validate(){fireEvent.click(configurationButton('离线验证'));await screen.findByText('离线验证通过')}
it('saves validates and activates desired concurrency2 without claiming an automatic worker restart',async()=>{
 const previous=mock.getMockImplementation()!
 mock.mockImplementation(async(url:string,init?:RequestInit)=>url.endsWith('/catalog')?Response.json({...testCatalog,field_readonly:{...testCatalog.field_readonly,'basic.worker_concurrency':false},field_effects:{...testCatalog.field_effects,'basic.worker_concurrency':'worker_restart'},restart_required:{'basic.worker_concurrency':true},effective_ranges:{...testCatalog.effective_ranges,'basic.worker_concurrency':{minimum:1,maximum:2,unit:'processes'}}}):previous(url,init))
 await copy();fireEvent.click(configurationButton('基础参数'));fireEvent.change(configurationField('Worker 期望并发数'),{target:{value:'2'}})
 fireEvent.click(configurationButton('保存为新修订'));await screen.findByText('草稿已保存为新修订。')
 expect(screen.getByLabelText('Worker 期望并发数')).toHaveProperty('value','2')
 await validate();fireEvent.change(configurationField('配置变更理由'),{target:{value:'Approve desired concurrency two'}})
 fireEvent.click(configurationButton('启用此修订'));await screen.findByText('配置已切换，仅影响以后新操作。')
 expect(JSON.parse(mock.mock.calls.find(([url])=>url.endsWith('/save'))![1].body).bundle.basic.worker_concurrency).toBe(2)
 expect(mock.mock.calls.filter(([url])=>url.endsWith('/activate'))).toHaveLength(1)
 expect(screen.getByText('Worker 启用记录只确认期望配置；实际启动值与待重启状态请到运行状态核对。')).toBeTruthy()
 expect(mock.mock.calls.some(([url])=>/restart|runtime\/.+\//.test(url))).toBe(false)
})
it('edits a structured field, saves a child revision, compares and activates with the visible revision once',async()=>{
 await copy();fireEvent.click(configurationButton('基础参数'));fireEvent.change(configurationField('最大行数（行）'),{target:{value:'90000'}})
 expect((configurationButton('启用此修订') as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(configurationButton('保存为新修订'));await screen.findByText('草稿已保存为新修订。')
 fireEvent.click(configurationButton('查看配置差异'));await screen.findByText('100000')
 await validate();fireEvent.change(configurationField('配置变更理由'),{target:{value:'Synthetic configuration review'}})
 const button=configurationButton('启用此修订');fireEvent.click(button);fireEvent.click(button)
 await screen.findByText('配置已切换，仅影响以后新操作。');expect(keys).toHaveLength(1)
 const saved=mock.mock.calls.find(([url])=>url.endsWith('/save'))!;expect(JSON.parse(saved[1].body).bundle.basic.max_rows).toBe(90000)
 expect(JSON.parse(mock.mock.calls.find(([url])=>url.endsWith('/activate'))![1].body)).toMatchObject({expected_revision:1,reason:'Synthetic configuration review'})
})
it('shows readable failed validation and prevents stale validation after editing',async()=>{
 await copy();pass=false;fireEvent.click(configurationButton('离线验证'));await screen.findByText('最大行数超过部署上限。');pass=true;await validate()
 fireEvent.click(configurationButton('基础参数'));fireEvent.change(configurationField('最大行数（行）'),{target:{value:'80000'}})
 expect((configurationButton('启用此修订') as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByText('有未保存的修改')).toBeTruthy();expect(screen.getAllByText('真实连通未测试').length).toBeGreaterThan(0)
})
it('keeps a switch request key when the network result is unknown and reloads revision on conflict',async()=>{
 await copy();await validate();fireEvent.change(configurationField('配置变更理由'),{target:{value:'Synthetic reason'}});unknown=true
 fireEvent.click(configurationButton('启用此修订'));await screen.findByText('操作结果尚未确认，请先读取当前配置与事件。')
 fireEvent.click(configurationButton('重试原配置操作'));await screen.findByText('配置已切换，仅影响以后新操作。');expect(keys[0]).toBe(keys[1])
})
it('renders all seven domains, fixed safeguards, safe binding and supports English',async()=>{
 await copy()
 for(const name of ['模型、工具与价格','有限说明与工作流','NCBI','基础参数','期刊规则','学校模板规则','审稿与评审规则'])expect(screen.getByRole('button',{name})).toBeTruthy()
 fireEvent.click(configurationButton('审稿与评审规则'));expect(screen.getAllByLabelText(/字面关键词/)).toHaveLength(categories.length)
 fireEvent.change(configurationField('绑定对象标识'),{target:{value:'old-task'}});fireEvent.click(configurationButton('查询安全绑定'));await screen.findByText('历史对象缺少配置绑定依据')
 expect(document.querySelector('input[type=password]')).toBeNull();act(()=>setLocale('en'));expect(configurationButton('School template rules')).toBeTruthy();expect(screen.getByText('Real connectivity not tested')).toBeTruthy()
})
it('clears privileged work on 403 and ignores a response consumed after a session change',async()=>{
 await copy();mock.mockImplementation(async()=>Response.json({detail:{code:'forbidden'}},{status:403}));fireEvent.click(configurationButton('离线验证'));await waitFor(()=>expect(forbidden).toHaveBeenCalled())
 act(()=>clearApiSession());expect(screen.queryByLabelText('配置变更理由')).toBeNull()
})
it('keeps the reason on revision conflict, reloads current and requires a new reviewed intent',async()=>{
 await copy();await validate();fireEvent.change(configurationField('配置变更理由'),{target:{value:'Reviewed concurrent change'}});conflict=true
 fireEvent.click(configurationButton('启用此修订'));await screen.findByText('当前配置已被修改，请重新读取并核对后再启用。');expect(screen.queryByText('SECRET')).toBeNull();expect(screen.getByLabelText('配置变更理由')).toHaveProperty('value','Reviewed concurrent change')
 await waitFor(()=>expect((configurationButton('启用此修订') as HTMLButtonElement).disabled).toBe(false));fireEvent.click(configurationButton('启用此修订'));await screen.findByText('配置已切换，仅影响以后新操作。');expect(keys[0]).not.toBe(keys[1]);const calls=mock.mock.calls.filter(([url])=>url.endsWith('/activate'));expect(JSON.parse(calls[1][1].body).expected_revision).toBe(2)
})
it('rolls back only a previously active version using a newly validated revision',async()=>{
 versions.push(testVersion('v2'));active='v2';revision=2;render(<ConfigurationsPanel onForbidden={forbidden}/>);fireEvent.click(await findConfigurationButton('选择配置版本 1'));await waitFor(()=>expect(screen.getByRole('button',{name:'所选版本'}).getAttribute('aria-pressed')).toBe('true'));await waitFor(()=>expect((configurationButton('离线验证') as HTMLButtonElement).disabled).toBe(false));await validate();fireEvent.change(configurationField('配置变更理由'),{target:{value:'Restore synthetic baseline'}});fireEvent.click(configurationButton('回退到此版本'));await screen.findByText('配置已切换，仅影响以后新操作。');const call=mock.mock.calls.find(([url])=>url.endsWith('/rollback'))!;expect(JSON.parse(call[1].body)).toMatchObject({expected_revision:2,reason:'Restore synthetic baseline'})
})
it('marks a lost draft-save response as unconfirmed and requires reading history before another write',async()=>{
 await copy();fireEvent.click(configurationButton('基础参数'));fireEvent.change(configurationField('最大行数（行）'),{target:{value:'90000'}});const previous=mock.getMockImplementation()!;mock.mockImplementation(async(url:string,init?:RequestInit)=>url.endsWith('/save')?Promise.reject(new TypeError('network')):previous(url,init));fireEvent.click(configurationButton('保存为新修订'));await screen.findByText('草稿保存结果尚未确认，请读取历史版本核对，避免重复创建。');expect((configurationButton('保存为新修订') as HTMLButtonElement).disabled).toBe(true);fireEvent.click(configurationButton('读取当前配置与事件'));await waitFor(()=>expect((configurationButton('保存为新修订') as HTMLButtonElement).disabled).toBe(false));expect(screen.getByLabelText('最大行数（行）')).toHaveProperty('value','90000')
})
it('unlocks a definitively rejected switch so its reason can be corrected and submitted as a new intent',async()=>{
 await copy();await validate();const previous=mock.getMockImplementation()!;let reject=true;mock.mockImplementation(async(url:string,init?:RequestInit)=>{if(url.endsWith('/activate')&&reject){reject=false;return Response.json({detail:{code:'configuration_invalid',message:'SECRET'}},{status:422})}return previous(url,init)})
 fireEvent.change(configurationField('配置变更理由'),{target:{value:'Review https://example.invalid/source'}});fireEvent.click(configurationButton('启用此修订'));await screen.findByText('配置包含无效字段、超出范围的值或不允许保存的内容，请核对表单。');expect(screen.getByLabelText('配置变更理由')).toHaveProperty('disabled',false);expect(screen.queryByRole('button',{name:'重试原配置操作'})).toBeNull()
 fireEvent.change(configurationField('配置变更理由'),{target:{value:'Corrected synthetic review reason'}});fireEvent.click(configurationButton('启用此修订'));await screen.findByText('配置已切换，仅影响以后新操作。');const calls=mock.mock.calls.filter(([url])=>url.endsWith('/activate'));expect(JSON.parse(calls[1][1].body).request_key).not.toBe(JSON.parse(calls[0][1].body).request_key);expect(screen.queryByText('SECRET')).toBeNull()
})

it('loads existing validation from the initial current version detail and keeps dirty edits on a normal refresh',async()=>{
 const previous=mock.getMockImplementation()!;mock.mockImplementation(async(url:string,init?:RequestInit)=>url==='/api/v1/admin/configurations/v1'?Response.json({...testVersion(),validations:[testValidation('v1')]}):previous(url,init));render(<ConfigurationsPanel onForbidden={forbidden}/>);await screen.findByText('离线验证通过');expect(mock.mock.calls.some(([url])=>url==='/api/v1/admin/configurations/v1')).toBe(true);expect(mock.mock.calls.some(([url])=>url.endsWith('/validate'))).toBe(false);expect(screen.queryByText('尚未离线验证')).toBeNull();fireEvent.click(configurationButton('复制为草稿'));await screen.findByText('草稿已建立。');fireEvent.click(configurationButton('基础参数'));fireEvent.change(configurationField('最大行数（行）'),{target:{value:'85000'}});fireEvent.click(configurationButton('读取当前配置与事件'));await waitFor(()=>expect(mock.mock.calls.filter(([url])=>url.endsWith('/current')).length).toBeGreaterThan(2));expect(screen.getByLabelText('最大行数（行）')).toHaveProperty('value','85000');expect(screen.getByText('有未保存的修改')).toBeTruthy()
})
it('clears the initial configuration when the version detail denies administrator access',async()=>{
 const previous=mock.getMockImplementation()!;mock.mockImplementation(async(url:string,init?:RequestInit)=>url==='/api/v1/admin/configurations/v1'?Response.json({detail:{code:'forbidden'}},{status:403}):previous(url,init));render(<ConfigurationsPanel onForbidden={forbidden}/>);await waitFor(()=>expect(forbidden).toHaveBeenCalledOnce());expect(screen.queryByLabelText('配置变更理由')).toBeNull();expect(screen.queryByText('当前有效')).toBeNull()
})
it('aborts and ignores initial version detail after the session changes',async()=>{
 let finish!:(r:Response)=>void;let signal:AbortSignal|undefined;const previous=mock.getMockImplementation()!;mock.mockImplementation((url:string,init?:RequestInit)=>url==='/api/v1/admin/configurations/v1'?new Promise<Response>(resolve=>{finish=resolve;signal=init?.signal as AbortSignal}):previous(url,init));render(<ConfigurationsPanel onForbidden={forbidden}/>);await waitFor(()=>expect(finish).toBeTypeOf('function'));act(()=>clearApiSession());expect(signal?.aborted).toBe(true);await act(async()=>finish(Response.json({...testVersion(),validations:[testValidation('v1')]})));expect(screen.queryByText('离线验证通过')).toBeNull();expect(screen.queryByLabelText('配置变更理由')).toBeNull()
})
it('keeps the no-current-version empty state without requesting a nonexistent detail',async()=>{
 active='';render(<ConfigurationsPanel onForbidden={forbidden}/>);await screen.findByText('尚无有效配置');expect(configurationButton('从已安装设置创建基线草稿')).toBeTruthy();expect(mock.mock.calls.some(([url])=>url==='/api/v1/admin/configurations/v1')).toBe(false)
})
it('layers configuration evidence and keeps domain controls, drafts and reason while changing views',async()=>{
 render(<ConfigurationsPanel onForbidden={forbidden}/>);await findConfigurationButton('读取当前配置与事件')
 const nav=screen.getByRole('navigation',{name:'配置治理视图'})
 expect(screen.queryByRole('button',{name:'保存为新修订'})).toBeNull()
 fireEvent.click(within(nav).getByRole('button',{name:'所选版本'}));fireEvent.click(await findConfigurationButton('复制为草稿'));await screen.findByText('草稿已建立。')
 fireEvent.change(configurationField('配置业务'),{target:{value:'plot'}})
 fireEvent.click(configurationButton('基础参数'));fireEvent.change(configurationField('最大行数（行）'),{target:{value:'85000'}})
 fireEvent.click(configurationButton('模型、工具与价格'));expect(screen.getByLabelText('配置业务')).toHaveProperty('value','plot')
 fireEvent.click(within(nav).getByRole('button',{name:'启用与回退'}));fireEvent.change(configurationField('配置变更理由'),{target:{value:'Retained reviewed reason'}})
 fireEvent.click(within(nav).getByRole('button',{name:'版本列表'}));fireEvent.click(configurationButton('选择配置版本 1'));await screen.findByText('先保存或放弃本地修改，再选择其他版本。')
 fireEvent.click(within(nav).getByRole('button',{name:'所选版本'}));fireEvent.click(configurationButton('基础参数'));expect(screen.getByLabelText('最大行数（行）')).toHaveProperty('value','85000')
 fireEvent.click(within(nav).getByRole('button',{name:'启用与回退'}));expect(screen.getByLabelText('配置变更理由')).toHaveProperty('value','Retained reviewed reason')
})
it('pauses hidden reads and reactivates without overwriting a dirty version or unregistering its leave guard',async()=>{
 let isDirty:(()=>boolean)|undefined;const register: RegisterLeaveGuard=(_guard,dirty)=>{isDirty=dirty;return()=>{isDirty=undefined}}
 const view=render(<ConfigurationsPanel onForbidden={forbidden} active={false} registerLeaveGuard={register}/>);expect(mock).not.toHaveBeenCalled()
 view.rerender(<ConfigurationsPanel onForbidden={forbidden} active registerLeaveGuard={register}/>);fireEvent.click(await findConfigurationButton('复制为草稿'));await screen.findByText('草稿已建立。')
 fireEvent.click(configurationButton('基础参数'));fireEvent.change(configurationField('最大行数（行）'),{target:{value:'82000'}});expect(isDirty?.()).toBe(true)
 view.rerender(<ConfigurationsPanel onForbidden={forbidden} active={false} registerLeaveGuard={register}/>);const reads=mock.mock.calls.length;fireEvent.click(configurationButton('读取当前配置与事件'));expect(mock).toHaveBeenCalledTimes(reads)
 view.rerender(<ConfigurationsPanel onForbidden={forbidden} active registerLeaveGuard={register}/>);await waitFor(()=>expect(mock.mock.calls.length).toBeGreaterThan(reads));expect(screen.getByLabelText('最大行数（行）')).toHaveProperty('value','82000');expect(isDirty?.()).toBe(true)
})
it('keeps the original uncertain switch intent across layered panes and registers pending work',async()=>{
 let guard:(()=>boolean)|undefined;const register: RegisterLeaveGuard=(value)=>{guard=value;return()=>{guard=undefined}}
 render(<ConfigurationsPanel onForbidden={forbidden} registerLeaveGuard={register}/>);const nav=screen.getByRole('navigation',{name:'配置治理视图'})
 fireEvent.click(within(nav).getByRole('button',{name:'所选版本'}));fireEvent.click(await findConfigurationButton('复制为草稿'));await screen.findByText('草稿已建立。')
 fireEvent.click(within(nav).getByRole('button',{name:'对比与验证'}));await validate();fireEvent.click(within(nav).getByRole('button',{name:'启用与回退'}));fireEvent.change(configurationField('配置变更理由'),{target:{value:'Reviewed retained operation'}});unknown=true
 fireEvent.click(configurationButton('启用此修订'));await screen.findByText('操作结果尚未确认，请先读取当前配置与事件。');const alert=vi.spyOn(window,'alert').mockImplementation(()=>{});expect(guard?.()).toBe(false);alert.mockRestore()
 fireEvent.click(within(nav).getByRole('button',{name:'操作事件'}));fireEvent.click(within(nav).getByRole('button',{name:'启用与回退'}));fireEvent.click(configurationButton('重试原配置操作'));await screen.findByText('配置已切换，仅影响以后新操作。');expect(keys[0]).toBe(keys[1])
})
it('cancels a version-detail GET when hidden and ignores its late response without losing the selected version',async()=>{
 versions.push(testVersion('v2'));let finish!:(response:Response)=>void;let detailSignal:AbortSignal|undefined;const previous=mock.getMockImplementation()!
 mock.mockImplementation((url:string,init?:RequestInit)=>url==='/api/v1/admin/configurations/v2'?new Promise<Response>(resolve=>{finish=resolve;detailSignal=init?.signal as AbortSignal}):previous(url,init))
 const view=render(<ConfigurationsPanel onForbidden={forbidden} active/>);fireEvent.click(await findConfigurationButton('选择配置版本 2'));await waitFor(()=>expect(finish).toBeTypeOf('function'))
 view.rerender(<ConfigurationsPanel onForbidden={forbidden} active={false}/>);expect(detailSignal?.aborted).toBe(true)
 await act(async()=>finish(Response.json(testVersion('v2'))));view.rerender(<ConfigurationsPanel onForbidden={forbidden} active/>);await waitFor(()=>expect(configurationButton('复制为草稿')).toHaveProperty('disabled',false))
 expect(configurationButton('保存为新修订')).toHaveProperty('disabled',true);expect(screen.queryByText('已保存修订')).toBeNull()
})
it('keeps a submitted save alive while hidden and accepts its result before resuming reads',async()=>{
 let finish!:(response:Response)=>void;let saveSignal:AbortSignal|undefined;const previous=mock.getMockImplementation()!
 mock.mockImplementation((url:string,init?:RequestInit)=>url.endsWith('/save')?new Promise<Response>(resolve=>{finish=resolve;saveSignal=init?.signal as AbortSignal}):previous(url,init))
 const view=render(<ConfigurationsPanel onForbidden={forbidden} active/>);fireEvent.click(await findConfigurationButton('复制为草稿'));await screen.findByText('草稿已建立。');fireEvent.click(configurationButton('基础参数'));fireEvent.change(configurationField('最大行数（行）'),{target:{value:'83000'}});fireEvent.click(configurationButton('保存为新修订'));await waitFor(()=>expect(finish).toBeTypeOf('function'))
 view.rerender(<ConfigurationsPanel onForbidden={forbidden} active={false}/>);expect(saveSignal?.aborted).toBe(false);const readCount=mock.mock.calls.length
 const saved=testVersion('v3');saved.bundle.basic.max_rows=83000;await act(async()=>finish(Response.json(saved)));expect(mock).toHaveBeenCalledTimes(readCount)
 view.rerender(<ConfigurationsPanel onForbidden={forbidden} active/>);await screen.findByText('草稿已保存为新修订。');expect(screen.getByLabelText('最大行数（行）')).toHaveProperty('value','83000');expect(screen.queryByText('有未保存的修改')).toBeNull()
})
it('clears retained layered controls, reasons and binding evidence after a session change',async()=>{
 render(<ConfigurationsPanel onForbidden={forbidden}/>);const nav=screen.getByRole('navigation',{name:'配置治理视图'});fireEvent.click(within(nav).getByRole('button',{name:'所选版本'}));fireEvent.click(await findConfigurationButton('复制为草稿'));await screen.findByText('草稿已建立。');fireEvent.click(within(nav).getByRole('button',{name:'启用与回退'}));fireEvent.change(configurationField('配置变更理由'),{target:{value:'Privileged retained reason'}});fireEvent.click(within(nav).getByRole('button',{name:'运行绑定'}));fireEvent.change(configurationField('绑定对象标识'),{target:{value:'private-task'}});fireEvent.click(configurationButton('查询安全绑定'));await screen.findByText('历史对象缺少配置绑定依据')
 act(()=>clearApiSession());expect(screen.queryByLabelText('配置治理')).toBeNull();expect(screen.queryByDisplayValue('Privileged retained reason')).toBeNull();expect(screen.queryByDisplayValue('private-task')).toBeNull();expect(screen.getByText('管理员权限已变化，请核对账号权限。')).toBeTruthy()
})
it('cancels pane-specific diff reads while retaining comparison criteria and completed evidence',async()=>{
 let finish!:(response:Response)=>void;let diffSignal:AbortSignal|undefined;const previous=mock.getMockImplementation()!
 mock.mockImplementation((url:string,init?:RequestInit)=>url.includes('/diff')?new Promise<Response>(resolve=>{finish=resolve;diffSignal=init?.signal as AbortSignal}):previous(url,init))
 render(<ConfigurationsPanel onForbidden={forbidden}/>);const nav=screen.getByRole('navigation',{name:'配置治理视图'});fireEvent.click(within(nav).getByRole('button',{name:'所选版本'}));fireEvent.click(await findConfigurationButton('复制为草稿'));await screen.findByText('草稿已建立。');fireEvent.click(within(nav).getByRole('button',{name:'对比与验证'}));fireEvent.change(configurationField('对比依据'),{target:{value:'parent'}});fireEvent.click(configurationButton('查看配置差异'));await waitFor(()=>expect(finish).toBeTypeOf('function'))
 fireEvent.click(within(nav).getByRole('button',{name:'所选版本'}));expect(diffSignal?.aborted).toBe(true);await act(async()=>finish(Response.json({version_id:'v2',against:'v1',changes:[{path:'basic.max_rows',before:100000,after:11111}]})))
 fireEvent.click(within(nav).getByRole('button',{name:'对比与验证'}));expect(screen.getByLabelText('对比依据')).toHaveProperty('value','parent');expect(screen.queryByText('11111')).toBeNull();expect(configurationButton('查看配置差异')).toHaveProperty('disabled',false)
})
it('keeps the limited history coverage visible in the events pane',async()=>{
 render(<ConfigurationsPanel onForbidden={forbidden}/>);await findConfigurationButton('读取当前配置与事件');fireEvent.click(within(screen.getByRole('navigation',{name:'配置治理视图'})).getByRole('button',{name:'操作事件'}))
 const events=screen.getByRole('heading',{name:'配置操作事件'}).closest('section')!;expect(within(events).getByText('最近返回的100条版本与事件；不表示完整历史。')).toBeTruthy()
})
