import {configurationButton,findConfigurationButton,configurationField} from './configurationTestNavigation'
import {testCatalog,testVersion} from './configurationTestFixtures'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OperationsWorkspace from './OperationsWorkspace'
import { setLocale } from '../../shared/i18n'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { eventsFixture, taskFixture, usageFixture, workspaceFixture } from '../tasks/taskFixtures'
const summary = {call_count:1,estimated_micro_usd:123,estimated_unknown_count:1,actual_micro_usd:null,actual_known_micro_usd:7,actual_unknown_count:1,reconciled_count:0,partial_count:0,pending_count:1,not_applicable_count:0,reserved_micro_usd:5,accounted_micro_usd:128,tool_call_count:0,input_tokens:{known:0,unknown_count:1},output_tokens:{known:10,unknown_count:0},total_tokens:{known:0,unknown_count:1}}
const provenance = {openai_live:{...summary,call_count:0},synthetic_fixture:summary,unknown:{...summary,call_count:0}}
const usage = {currency:'USD',period:{kind:'cumulative',timezone:'UTC',from:null,to:null},coverage:{historical_missing_is_zero:false},user_charge_enabled:false,quota:{configured:false},budget_scope:'cumulative_unfiltered',budgets:[],summary,by_provenance:provenance,items:[{id:'call1',user_id:'self',project_id:'p1',task_id:'t1',task_type:'boxplot',model:'fixture-model',status:'completed',provider_provenance:'synthetic_fixture',created_at:'2026-10-23T00:00:00Z',input_tokens:null,output_tokens:10,total_tokens:null,estimated_cost_micro_usd:null,reconciliation:{status:'pending',actual_micro_usd:null},reserved_micro_usd:5,accounted_micro_usd:128}],total:21,page:1,page_size:10,groups:[{key:'fixture-model',summary,by_provenance:provenance}],group_total:51,group_page:1,group_page_size:50}
const account = {id:'other',email:'other@example.test',role:'analyst',review_status:'approved',active:true,admin_revision:3,updated_at:1792700000,allowed_actions:['edit']}
const pending = {user_id:'pending', email:'pending@example.test', display_name:'待审申请人',
  organization:'示例单位', submitted_at:1792700000, review_status:'pending', role:null, admin_revision:3}
const task = {id:'t1',user_id:'other',user_email:'other@example.test',project_id:'p1',task_type:'boxplot',phase:'compute',status:'failed',revision:3,created_at:'2026-10-23T00:00:00Z',updated_at:'2026-10-23T00:01:00Z',elapsed_ms:null,started_at:null,finished_at:null,current_attempt:1,attempt_count:1,error_code:'task_execution_failed',request_id:null,can_open_workspace:false,allowed_actions:[],workspace_url:null}
const coverage = {started_at:'2026-10-23T00:00:00Z',historical_missing_is_zero:false,policy:'retain_no_auto_delete'}
let role='admin';let active=true;let own=false;let conflict=false;let denied=false
function fixture(url:string,init?:RequestInit):Response {
 if(url==='/api/v1/auth/me')return active?Response.json({user:{id:'self',email:'self@example.test',role}}):Response.json({detail:{code:'authentication_required'}},{status:401})
 if(denied&&url.startsWith('/api/v1/admin/'))return Response.json({detail:{code:'permission_denied'}},{status:403})
 if(url.startsWith('/api/v1/admin/users/'))return conflict?Response.json({detail:{code:'admin_revision_conflict',message:'SECRET'}},{status:409}):Response.json({...account,admin_revision:4})
 if(url.startsWith('/api/v1/admin/users?'))return Response.json({items:[account,{...account,id:'self',email:'self@example.test',role:'admin',allowed_actions:[]}],total:11,page:1,page_size:10})
 if(url.startsWith('/api/v1/admin/registrations?'))return Response.json({items:[pending],total:1,page:1,page_size:10})
 if(url.startsWith('/api/v1/admin/tasks/'))return Response.json({...task,user_id:own?'self':'other',can_open_workspace:own,allowed_actions:own?['retry']:[],workspace_url:own?'/api/v1/tasks/t1/workspace':null})
 if(url.startsWith('/api/v1/admin/tasks?'))return Response.json({items:[{...task,user_id:own?'self':'other'}],total:11,page:1,page_size:10})
 if(url.includes('/usage?'))return Response.json(usage)
 if(url.startsWith('/api/v1/admin/metrics'))return Response.json({coverage,requests:12,errors:2,rate_limited:1,retry_requests:3,resume_requests:4,model_calls:1,tool_calls:0,model_calls_by_provenance:{openai_live:0,synthetic_fixture:1,unknown:0}})
 if(url.startsWith('/api/v1/admin/audit?'))return Response.json({coverage,items:[{id:'audit1',source:'cli',operator:'local-admin',actor_user_id:null,target_user_id:'other',before_role:'user',after_role:'admin',before_active:true,after_active:true,reason:'<script>operator text</script>',effective_at:1792700000,request_id:null}],total:1,page:1,page_size:10})
 if(url.startsWith('/api/v1/admin/logs?'))return Response.json({coverage,items:[{request_id:'a'.repeat(32),task_id:'t1',user_id:'other',route_template:'/api/v1/tasks/{task_id}/retry',method:'POST',status:500,elapsed_ms:10,error_code:'task_execution_failed',created_at:'2026-10-23T00:00:00Z'}],total:1,page:1,page_size:10})
 if(url==='/api/v1/tasks/t1/resume'&&init?.method==='POST')return Response.json({...taskFixture,status:'queued',display_status:'queued',revision:4})
 if(url.endsWith('/workspace'))return Response.json({...workspaceFixture,task:{...taskFixture,status:'failed',display_status:'failed'},wait:null,allowed_actions:['retry']})
 if(url.includes('/events'))return Response.json(eventsFixture)
 if(url.includes('/model-usage'))return Response.json(usageFixture)
 return Response.json({detail:{code:'invalid_request'}},{status:422})
}
let fetchMock:ReturnType<typeof vi.fn>
beforeEach(()=>{role='admin';active=true;own=false;conflict=false;denied=false;setApiSession('csrf','self');fetchMock=vi.fn(async(url:string,init?:RequestInit)=>fixture(url,init));vi.stubGlobal('fetch',fetchMock)})
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN');window.location.hash=''})
function mount(){render(<OperationsWorkspace><p>Project workspace retained</p></OperationsWorkspace>)}
async function admin(page = '账号管理', locale: 'zh-CN' | 'en' = 'zh-CN') {
  fireEvent.click(await screen.findByRole('button', { name: locale === 'en' ? 'Administrator' : '管理员' }))
  if (!screen.queryByRole('button', { name: page })) {
    fireEvent.click(screen.getByRole('button', { name: locale === 'en' ? 'Operations tools' : '运营工具' }))
  }
  fireEvent.click(await screen.findByRole('button', { name: page }))
}
async function accountRow(email = account.email) {
  return within((await screen.findByText(email)).closest('tr')!)
}
it('shows server-confirmed admin and own usage while preserving projects',async()=>{mount();await screen.findByRole('button',{name:'管理员'});expect(screen.getByText('Project workspace retained')).toBeTruthy();await admin();await screen.findByText('other@example.test');fireEvent.click(screen.getByRole('button',{name:'项目工作区'}));expect(screen.getByText('Project workspace retained')).toBeTruthy()})
it('ordinary users only load own usage without user_id',async()=>{role='user';mount();fireEvent.click(await screen.findByRole('button',{name:'本人用量'}));await screen.findByText('fixture-model');expect(screen.queryByRole('button',{name:'管理员'})).toBeNull();expect(screen.queryByLabelText('用户标识')).toBeNull();expect(fetchMock.mock.calls.some(([u])=>u.startsWith('/api/v1/me/usage?')&&!u.includes('user_id'))).toBe(true)})
it('disabled sessions have no operations entries',async()=>{active=false;mount();await waitFor(()=>expect(fetchMock).toHaveBeenCalled());await act(async()=>{});expect(screen.queryByRole('button',{name:'管理员'})).toBeNull();expect(screen.queryByRole('button',{name:'本人用量'})).toBeNull()})
it('saves row role and status from the actions column and links the audit', async () => {
  mount()
  await admin()
  const row = await accountRow()
  expect(screen.queryByRole('columnheader', { name: '变更理由' })).toBeNull()
  expect(row.queryByLabelText('变更理由')).toBeNull()
  fireEvent.change(row.getByLabelText('账号角色'), { target: { value: 'admin' } })
  fireEvent.change(row.getByLabelText('账号状态'), { target: { value: 'false' } })
  const button = row.getByRole('button', { name: '保存账号变更' })
  expect(button.closest('td')).toBe(row.getAllByRole('cell').at(-1))
  fireEvent.click(button)
  fireEvent.click(button)
  const audit = await screen.findByRole('button', { name: '查看操作审计' })
  expect(screen.queryByText('账号已更新，目标会话已撤销。')).toBeNull()
  expect(audit.closest('.admin-account-toolbar')).toBeTruthy()
  const calls = fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH')
  expect(calls).toHaveLength(1)
  expect(JSON.parse(calls[0][1].body)).toEqual({ role: 'admin', active: false, reason: '账号管理更新', expected_revision: 3 })
})
it('reloads on revision conflicts and translates safe code', async () => {
  conflict = true
  mount()
  await admin()
  const row = await accountRow()
  fireEvent.change(row.getByLabelText('账号角色'), { target: { value: 'admin' } })
  fireEvent.click(row.getByRole('button', { name: '保存账号变更' }))
  await screen.findByText('账号已被修改，请读取最新版本后重试。')
  expect(screen.queryByText('SECRET')).toBeNull()
  const refreshed = await accountRow()
  expect(refreshed.getByLabelText('账号角色')).toHaveProperty('value', 'analyst')
  expect(refreshed.getByRole('button', { name: '保存账号变更' })).toHaveProperty('disabled', true)
  expect(fetchMock.mock.calls.filter(([url]) => url.startsWith('/api/v1/admin/users?')).length).toBeGreaterThan(1)
})
it('only reads safe metadata for another owner and displays unknown attempt time',async()=>{mount();await admin('系统任务');fireEvent.click(await screen.findByRole('button',{name:'查看安全详情'}));await screen.findByText('此任务属于其他账号，仅可查看运营信息。');expect(fetchMock.mock.calls.some(([u])=>/\/tasks\/t1\/(workspace|events|model-usage)/.test(u))).toBe(false);expect(screen.queryByRole('link',{name:'在项目中打开'})).toBeNull();expect(screen.getAllByText('未知').length).toBeGreaterThan(0)})
it('opens own TaskDetail and reuses exact retry contract',async()=>{own=true;mount();await admin('系统任务');fireEvent.click(await screen.findByRole('button',{name:'查看安全详情'}));fireEvent.click(await screen.findByRole('button',{name:'打开本人的任务详情'}));fireEvent.click(await screen.findByRole('button',{name:'待处理'}));fireEvent.click(await screen.findByRole('button',{name:'重试原任务'}));await waitFor(()=>expect(fetchMock.mock.calls.some(([u])=>u==='/api/v1/tasks/t1/resume')).toBe(true));expect(JSON.parse(fetchMock.mock.calls.find(([u])=>u==='/api/v1/tasks/t1/resume')![1].body)).toEqual({operation:'retry',wait_id:null,expected_task_revision:3,input_version:taskFixture.input_version});fireEvent.click(screen.getByRole('button',{name:'返回任务安全详情'}));expect(screen.getByRole('link',{name:'在项目中打开'}).getAttribute('href')).toBe('#project=p1&section=tasks&task=t1')})
it('separates provenance and never presents unknown tokens or actual spend as zero',async()=>{role='user';mount();fireEvent.click(await screen.findByRole('button',{name:'本人用量'}));fireEvent.click(screen.getByRole('button',{name:'来源口径'}));await screen.findByRole('region',{name:'已证实真实调用'});for(const source of ['已证实真实调用','合成验收样例','来源未知']){fireEvent.click(screen.getByRole('button',{name:source}));const current=screen.getByRole('region',{name:source});expect(within(current).getByText('未知（尚未完整核对）')).toBeTruthy();expect(within(current).getAllByText('已知 0；未知 1 次').length).toBeGreaterThan(0)}expect(screen.getByText('用户收费未启用')).toBeTruthy();expect(screen.getByText('容量配额未配置')).toBeTruthy();expect(screen.getAllByText(/0.000007/).length).toBeGreaterThan(0)})
it('applies exact model grouping and independent call/group pages',async()=>{mount();await admin('用量统计');await screen.findAllByText('fixture-model');fireEvent.change(screen.getByLabelText('精确模型'),{target:{value:'exact-model'}});fireEvent.change(screen.getByLabelText('聚合维度'),{target:{value:'day'}});fireEvent.click(screen.getByRole('button',{name:'应用筛选'}));await waitFor(()=>expect(fetchMock.mock.calls.some(([u])=>u.includes('model=exact-model')&&u.includes('group_by=day'))).toBe(true));fireEvent.click(screen.getByRole('button',{name:'逐次调用'}));fireEvent.click(screen.getByRole('button',{name:'下一页调用'}));await waitFor(()=>expect(fetchMock.mock.calls.some(([u])=>u.includes('page=2')&&u.includes('group_page=1'))).toBe(true));fireEvent.click(screen.getByRole('button',{name:'聚合明细'}));fireEvent.click(screen.getByRole('button',{name:'下一页聚合'}));await waitFor(()=>expect(fetchMock.mock.calls.some(([u])=>u.includes('page=2')&&u.includes('group_page=2'))).toBe(true))})
it('shows metrics coverage, safe logs and escaped audit reason',async()=>{mount();await admin('运行日志');await screen.findByText('/api/v1/tasks/{task_id}/retry');expect(screen.getAllByText('历史缺失采集不代表零；本次请求可能在下次刷新后出现。').length).toBeGreaterThan(0);fireEvent.click(screen.getByRole('button',{name:'请求指标'}));expect(await screen.findByText('请求数')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'操作审计'}));await screen.findByText('<script>operator text</script>');expect(document.querySelector('script')).toBeNull();expect(screen.getByText('local-admin')).toBeTruthy()})
it('renders English account filters',async()=>{setLocale('en');mount();await admin('Accounts','en');expect(await screen.findByRole('button',{name:'Apply filters'})).toBeTruthy();expect(screen.getByLabelText('Account search')).toBeTruthy()})
it('session change aborts delayed requests and clears private operational state',async()=>{let finish!:(r:Response)=>void;fetchMock.mockImplementation((url:string,init?:RequestInit)=>url.startsWith('/api/v1/admin/users?')?new Promise<Response>(resolve=>{finish=resolve}):Promise.resolve(fixture(url,init)));mount();await admin();await waitFor(()=>expect(finish).toBeTypeOf('function'));act(()=>clearApiSession());await act(async()=>{finish(Response.json({items:[account],total:1,page:1,page_size:10}))});expect(screen.queryByText('other@example.test')).toBeNull();expect(screen.queryByRole('button',{name:'管理员'})).toBeNull()})
it('403 immediately removes privileged data and entry then rereads role',async()=>{mount();await admin();await screen.findByText('other@example.test');denied=true;role='user';fireEvent.click(screen.getByRole('button',{name:'刷新'}));await waitFor(()=>expect(screen.queryByRole('button',{name:'管理员'})).toBeNull());expect(screen.queryByText('other@example.test')).toBeNull();expect(fetchMock.mock.calls.filter(([u])=>u==='/api/v1/auth/me').length).toBeGreaterThan(1)})
it('validates from before to without making invalid request',async()=>{mount();await admin('系统任务');await screen.findByRole('button',{name:'查看安全详情'});fireEvent.change(screen.getByLabelText('起始时间'),{target:{value:'2026-10-23T12:00'}});fireEvent.change(screen.getByLabelText('结束时间'),{target:{value:'2026-10-22T12:00'}});const count=fetchMock.mock.calls.length;fireEvent.click(screen.getByRole('button',{name:'应用筛选'}));await screen.findByText('起始时间必须早于结束时间。');expect(fetchMock.mock.calls.length).toBe(count)})
it('enables save only for changed rows and keeps pending changes visible', async () => {
  let finish!: (response: Response) => void
  fetchMock.mockImplementation((url: string, init?: RequestInit) => init?.method === 'PATCH'
    ? new Promise<Response>(resolve => { finish = resolve })
    : Promise.resolve(fixture(url, init)))
  mount()
  await admin()
  const row = await accountRow()
  const select = row.getByLabelText('账号角色')
  const save = row.getByRole('button', { name: '保存账号变更' })
  expect(save).toHaveProperty('disabled', true)
  fireEvent.change(select, { target: { value: 'admin' } })
  fireEvent.change(select, { target: { value: 'analyst' } })
  expect(save).toHaveProperty('disabled', true)
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
  fireEvent.change(select, { target: { value: 'admin' } })
  fireEvent.click(save)
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  expect(select).toHaveProperty('value', 'admin')
  expect(screen.getByLabelText('账号搜索')).toHaveProperty('disabled', true)
  expect(screen.getByRole('button', { name: '应用筛选' })).toHaveProperty('disabled', true)
  await act(async () => finish(Response.json(account)))
})
it('aborts tab requests before rendering another operational page', async () => {
  let finish!: (response: Response) => void
  let signal: AbortSignal | null = null
  fetchMock.mockImplementation((url: string, init?: RequestInit) => url.startsWith('/api/v1/admin/users?')
    ? new Promise<Response>(resolve => { finish = resolve; signal = init?.signal as AbortSignal })
    : Promise.resolve(fixture(url, init)))
  mount()
  await admin()
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  const accounts = screen.getByRole('region', { name: '账号管理' })
  fireEvent.click(screen.getByRole('button', { name: '运营工具' }))
  fireEvent.click(screen.getByRole('button', { name: '系统任务' }))
  await screen.findByRole('button', { name: '查看安全详情' })
  expect(signal!.aborted).toBe(true)
  await act(async () => finish(Response.json({ items: [account], total: 1, page: 1, page_size: 10 })))
  expect(within(accounts).queryByText(account.email)).toBeNull()
})
it('displays approved account roles and sends the selected filters', async () => {
  mount()
  await admin()
  const analystRow = await accountRow()
  expect(analystRow.getByLabelText('账号角色')).toHaveProperty('value', 'analyst')
  expect(analystRow.getByLabelText('账号状态')).toHaveProperty('value', 'true')
  const ownRow = await accountRow('self@example.test')
  expect(ownRow.queryByRole('combobox')).toBeNull()
  expect(ownRow.getByText('管理员')).toBeTruthy()
  expect(screen.getByLabelText('账号搜索').closest('details')).toBeNull()
  expect(screen.queryByRole('columnheader', {name: '用户标识'})).toBeNull()
  expect(screen.queryByRole('columnheader', {name: '版本'})).toBeNull()
  expect(within(screen.getByRole('region', {name:'账号管理'})).queryByText(pending.email)).toBeNull()
  expect(screen.queryByRole('button', {name: '编辑账号'})).toBeNull()

  fireEvent.change(screen.getByLabelText('账号搜索'), {target: {value: 'other@'}})
  fireEvent.change(screen.getByLabelText('角色'), {target: {value: 'analyst'}})
  fireEvent.change(within(screen.getByLabelText('账号搜索').closest('form')!).getByLabelText('账号状态'), {target: {value: 'true'}})
  fireEvent.click(screen.getByRole('button', {name: '应用筛选'}))
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => {
    const request = new URL(url, 'http://localhost')
    return request.pathname === '/api/v1/admin/users' && request.searchParams.get('q') === 'other@'
      && request.searchParams.get('role') === 'analyst' && request.searchParams.get('active') === 'true'
      && request.searchParams.get('review_status') === 'approved'
  })).toBe(true))
  await screen.findByText('other@example.test')
  fireEvent.click(screen.getByRole('button', {name: '下一页'}))
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.startsWith('/api/v1/admin/users?') && url.includes('page=2'))).toBe(true))
})

describe('permanent account deletion', () => {
  const deletable = { ...account, allowed_actions: ['edit', 'delete'] }
  const showModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
  const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')

  beforeEach(() => {
    // jsdom does not implement dialog top-layer APIs.
    Object.defineProperties(HTMLDialogElement.prototype, {
      showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true } },
      close: { configurable: true, value(this: HTMLDialogElement) { this.open = false } },
    })
  })

  afterEach(() => {
    cleanup()
    if (showModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', showModal)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
    if (close) Object.defineProperty(HTMLDialogElement.prototype, 'close', close)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close')
  })

  it('requires a server-authorized target and returns focus when canceled', async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => url.startsWith('/api/v1/admin/users?')
      ? Response.json({ items: [
        deletable,
        { ...deletable, id: 'self', email: 'self@example.test', role: 'admin' },
        { ...deletable, id: 'admin2', email: 'admin2@example.test', role: 'admin' },
        { ...account, id: 'read-only', email: 'read-only@example.test', allowed_actions: [] },
      ], total: 4, page: 1, page_size: 10 })
      : fixture(url, init))
    mount()
    await admin()
    const trigger = (await accountRow()).getByRole('button', { name: '删除' })
    for (const email of ['self@example.test', 'admin2@example.test', 'read-only@example.test']) {
      expect((await accountRow(email)).queryByRole('button', { name: '删除' })).toBeNull()
    }
    fireEvent.click(trigger)
    const dialog = screen.getByRole('dialog', { name: '永久删除账号' })
    expect(within(dialog).getByText(account.email)).toBeTruthy()
    expect(within(dialog).getByText(/其拥有的本机项目和文件，以及关联的本机记录/)).toBeTruthy()
    expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: '取消' }))
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  })

  it('sends a single revision-checked deletion after confirmation and refreshes the list', async () => {
    let finish!: () => void
    let deleted = false
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') return new Promise<Response>(resolve => {
        finish = () => {
          deleted = true
          resolve(Response.json({ id: account.id, deleted: true }))
        }
      })
      if (url.startsWith('/api/v1/admin/users?')) return Response.json({
        items: deleted ? [] : [deletable], total: deleted ? 0 : 1, page: 1, page_size: 10,
      })
      return fixture(url, init)
    })
    mount()
    await admin()
    fireEvent.click((await accountRow()).getByRole('button', { name: '删除' }))
    const dialog = screen.getByRole('dialog', { name: '永久删除账号' })
    const confirm = within(dialog).getByRole('button', { name: '确认永久删除' })
    fireEvent.click(confirm)
    fireEvent.click(confirm)
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(screen.getByRole('dialog')).toBe(dialog)
    expect(within(dialog).getByRole('button', { name: '取消' })).toHaveProperty('disabled', true)
    const calls = fetchMock.mock.calls.filter(([, init]) => init?.method === 'DELETE')
    expect(calls).toHaveLength(1)
    expect(calls[0][0]).toBe('/api/v1/admin/users/other')
    expect(JSON.parse(calls[0][1].body)).toEqual({ expected_revision: 3 })
    await act(async () => finish())
    await screen.findByText('账号已永久删除。')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByText(account.email)).toBeNull()
    await screen.findByText('没有符合筛选条件的记录。')
  })

  it('allows retry after incomplete cleanup takes the account out of the active filter', async () => {
    let attempts = 0
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        attempts += 1
        if (attempts === 1) return Response.json({
          detail: { code: 'account_delete_incomplete', message: 'SECRET_LOCAL_PATH' },
        }, { status: 503 })
        return Response.json({ id: account.id, deleted: true })
      }
      if (url.startsWith('/api/v1/admin/users?')) {
        const enabledOnly = new URL(url, 'http://localhost').searchParams.get('active') === 'true'
        const items = attempts === 0 ? [deletable]
          : attempts === 1 && !enabledOnly ? [{ ...deletable, active: false, allowed_actions: ['delete'] }] : []
        return Response.json({ items, total: items.length, page: 1, page_size: 10 })
      }
      return fixture(url, init)
    })
    mount()
    await admin()
    const filters = within(screen.getByLabelText('账号搜索').closest('form')!)
    fireEvent.change(filters.getByLabelText('账号状态'), { target: { value: 'true' } })
    fireEvent.click(filters.getByRole('button', { name: '应用筛选' }))
    fireEvent.click((await accountRow()).getByRole('button', { name: '删除' }))
    const dialog = within(screen.getByRole('dialog', { name: '永久删除账号' }))
    fireEvent.click(dialog.getByRole('button', { name: '确认永久删除' }))
    const error = await dialog.findByRole('alert')
    expect(error.textContent).not.toContain('SECRET_LOCAL_PATH')
    expect(screen.queryByText('账号已永久删除。')).toBeNull()
    const retry = dialog.getByRole('button', { name: '确认永久删除' })
    await screen.findByText('没有符合筛选条件的记录。')
    await waitFor(() => expect(retry).toHaveProperty('disabled', false))
    fireEvent.click(retry)
    await screen.findByText('账号已永久删除。')
    expect(attempts).toBe(2)
  })
})

it('approves the role from the application row and shows the confirmed result in the same list', async () => {
  const path = '/api/v1/admin/users/pending/registration/review'
  let reviewed = false
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === path) {
      reviewed = true
      return Response.json({...account, id:pending.user_id, role:'analyst', admin_revision:4})
    }
    if (url.startsWith('/api/v1/admin/registrations?')) {
      const item = reviewed ? {...pending, role:'analyst', review_status:'approved', admin_revision:4} : pending
      return Response.json({items:[item], total:1, page:1, page_size:10})
    }
    return fixture(url, init)
  })
  mount()
  await admin('审核管理')
  const row = (await screen.findByText(pending.email)).closest('tr')!
  const approve = within(row).getByRole('button', {name: '未审核'})
  const role = within(row).getByRole('combobox')
  expect(role).toHaveProperty('value', 'customer')
  expect(within(role).getAllByRole('option').map(option => option.textContent)).toEqual(['客户', '分析员', '管理员'])
  expect(approve).toHaveProperty('disabled', false)
  fireEvent.change(role, {target: {value:'analyst'}})
  fireEvent.click(approve)
  fireEvent.click(approve)
  await waitFor(() => expect(within(screen.getByText(pending.email).closest('tr')!).getByText('审核通过')).toBeTruthy())
  expect(screen.queryByText('申请已通过，账号已启用。')).toBeNull()
  const confirmed = (await screen.findByText(pending.email)).closest('tr')!
  expect(within(confirmed).getByText('分析员')).toBeTruthy()
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/registration'))).toBe(false)
  expect(fetchMock.mock.calls.some(([url]) => url.includes('review_status=all') && url.includes('page_size=10'))).toBe(true)
  const calls = fetchMock.mock.calls.filter(([url]) => url === path)
  expect(calls).toHaveLength(1)
  expect(JSON.parse(calls[0][1].body)).toEqual({decision:'approve', expected_revision:3, role:'analyst'})
})

it('translates empty and safe error states in English',async()=>{setLocale('en');let error=false;fetchMock.mockImplementation(async(url:string,init?:RequestInit)=>url.startsWith('/api/v1/admin/users?')?error?Response.json({detail:{code:'admin_query_invalid',message:'SECRET'}},{status:422}):Response.json({items:[],total:0,page:1,page_size:10}):fixture(url,init));mount();await admin('Accounts','en');await screen.findByText('No records match these filters.');error=true;fireEvent.click(screen.getByRole('button',{name:'Refresh'}));await screen.findByText('Operational filters are invalid. Check identifiers and the time range.');expect(screen.queryByText('SECRET')).toBeNull()})
it.each(['zh-CN','en'] as const)('renders all call states and uncertain-submission warning in %s',async(locale)=>{
 role='user';setLocale(locale)
 const states=['reserved','submitting','submitted','submission_unknown','completed','failed','released','future_status']
 const labels=locale==='en'?['Reserved, not submitted','Submitting','Submitted; waiting for result','Submission outcome unknown','Completed','Execution failed','Released before submission','Unknown']:['已预留，尚未提交','正在提交','已提交，等待结果','提交结果未知','已完成','执行失败','未提交已释放','未知']
 fetchMock.mockImplementation(async(url:string,init?:RequestInit)=>url.includes('/usage?')?Response.json({...usage,items:states.map(status=>({...usage.items[0],id:`call-${status}`,status})),total:states.length}):fixture(url,init))
 mount();fireEvent.click(await screen.findByRole('button',{name:locale==='en'?'My usage':'本人用量'}))
 fireEvent.click(screen.getByRole('button',{name:locale==='en'?'Individual calls':'逐次调用'}));const calls=await screen.findByRole('region',{name:locale==='en'?'Individual calls':'逐次调用'})
 for(let index=0;index<states.length;index++){
  const row=within(calls).getByText(`call-${states[index]}`).closest('tr')!
  expect(within(row).getAllByRole('cell')[3].textContent).toContain(labels[index])
 }
 expect(within(calls).getByText(locale==='en'?'The external submission outcome is unconfirmed. Check the existing receipt before taking action; do not resend the request.':'外部提交结果尚未确认，请先核对已有回执，不能据此重新发送请求。')).toBeTruthy()
})
it('follows embedded own TaskDetail project links without reacting to unrelated hash events',async()=>{
 own=true
 const input={kind:'journal_adaptation',adaptation_id:'a1',target_id:'target1',check_id:'c1',requirements_version:'a'.repeat(64),manuscript_version_id:'v1',workflow_version:'journal_adaptation_v1'}
 fetchMock.mockImplementation(async(url:string,init?:RequestInit)=>url==='/api/v1/tasks/t1/workspace'?Response.json({...workspaceFixture,task:{...taskFixture,task_type:'journal_adaptation',phase:'verify',status:'succeeded',display_status:'succeeded',reason_code:null,error_code:null,input_version:input},source:{file_id:null,filename:'Owned manuscript',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[]}):fixture(url,init))
 mount();await admin('系统任务')
 fireEvent.change(screen.getByLabelText('用户标识'),{target:{value:'self'}})
 act(()=>window.dispatchEvent(new HashChangeEvent('hashchange')))
 expect(screen.getByRole('button',{name:'管理员'}).getAttribute('aria-pressed')).toBe('true')
 expect((screen.getByLabelText('用户标识') as HTMLInputElement).value).toBe('self')
 fireEvent.click(await screen.findByRole('button',{name:'查看安全详情'}))
 fireEvent.click(await screen.findByRole('button',{name:'打开本人的任务详情'}))
 const link=await screen.findByRole('link',{name:'打开期刊建议'})
 expect(link.getAttribute('href')).toBe('#project=p1&section=journals&adaptation=a1')
 fireEvent.click(link)
 expect(screen.getByRole('button',{name:'项目工作区'}).getAttribute('aria-pressed')).toBe('true')
 expect(screen.queryByRole('region',{name:'任务详情'})).toBeNull()
})
it.each(['zh-CN','en'] as const)('distinguishes audit creation, normal changes and partial missing state in %s',async(locale)=>{
 setLocale(locale)
 const base={source:'cli',operator:'local-admin',actor_user_id:null,target_user_id:'other',after_role:'admin',after_active:false,effective_at:1792700000,request_id:null}
 const items=[
  {...base,id:'created',reason:'create-event',before_role:null,before_active:null},
  {...base,id:'modified',reason:'modify-event',before_role:'user',before_active:true},
  {...base,id:'partial-role',reason:'partial-role-event',before_role:null,before_active:true},
  {...base,id:'partial-active',reason:'partial-active-event',before_role:'admin',before_active:null},
 ]
 fetchMock.mockImplementation(async(url:string,init?:RequestInit)=>url.startsWith('/api/v1/admin/audit?')?Response.json({coverage,items,total:items.length,page:1,page_size:10}):fixture(url,init))
 mount();await admin(locale==='en'?'Operational logs':'运行日志',locale)
 fireEvent.click(await screen.findByRole('button',{name:locale==='en'?'Account audit':'操作审计'}))
 const expected=locale==='en'?['Did not exist before creation','User / Enabled','Unknown / Enabled','Administrator / Unknown']:['创建前不存在','普通用户 / 启用','未知 / 启用','管理员 / 未知']
 for(let index=0;index<items.length;index++){
  const row=(await screen.findByText(items[index].reason)).closest('tr')!
  const cells=within(row).getAllByRole('cell')
  expect(cells[3].textContent).toBe(expected[index])
  expect(cells[4].textContent).toBe(locale==='en'?'Administrator / Disabled':'管理员 / 停用')
 }
})

it('mounts configuration only for an administrator and removes it immediately after configuration 403',async()=>{
 fetchMock.mockImplementation(async(url:string,init?:RequestInit)=>{if(url.startsWith('/api/v1/admin/configurations')){if(denied)return Response.json({detail:{code:'forbidden'}},{status:403});if(url.endsWith('/current'))return Response.json({revision:1,version:testVersion()});if(url.endsWith('/catalog'))return Response.json(testCatalog);if(url==='/api/v1/admin/configurations/v1')return Response.json(testVersion());if(url.endsWith('/events'))return Response.json({items:[]});return Response.json({items:[testVersion()]})}return fixture(url,init)})
 mount();await admin('配置治理');await findConfigurationButton('复制为草稿');denied=true;role='user';fireEvent.click(configurationButton('离线验证'));await waitFor(()=>expect(screen.queryByRole('button',{name:'管理员'})).toBeNull());expect(screen.queryByRole('button',{name:'配置治理'})).toBeNull();expect(screen.queryByLabelText('配置变更理由')).toBeNull()
})

it.each(['用量统计','运行日志','项目工作区','本人用量'])('retains the local configuration draft and reason while navigating to %s',async destination=>{
 fetchMock.mockImplementation(async(url:string,init?:RequestInit)=>{if(url.startsWith('/api/v1/admin/configurations')){if(url.endsWith('/current'))return Response.json({revision:1,version:testVersion()});if(url.endsWith('/catalog'))return Response.json(testCatalog);if(url==='/api/v1/admin/configurations/v1')return Response.json(testVersion());if(url.endsWith('/copy'))return Response.json(testVersion('draft'));if(url.endsWith('/events'))return Response.json({items:[]});return Response.json({items:[testVersion()]})}return fixture(url,init)})
 mount();await admin('配置治理');fireEvent.click(await findConfigurationButton('复制为草稿'));await screen.findByText('草稿已建立。');fireEvent.click(configurationButton('基础参数'));fireEvent.change(screen.getByLabelText('最大行数（行）'),{target:{value:'90000'}});fireEvent.change(configurationField('配置变更理由'),{target:{value:'Keep this local draft'}});fireEvent.click(screen.getByRole('button',{name:destination}));if(destination==='项目工作区'||destination==='本人用量')fireEvent.click(screen.getByRole('button',{name:'管理员'}));fireEvent.click(screen.getByRole('button',{name:'配置治理'}));expect(await screen.findByLabelText('最大行数（行）')).toHaveProperty('value','90000');expect(screen.getByLabelText('配置变更理由')).toHaveProperty('value','Keep this local draft');act(()=>clearApiSession());expect(screen.queryByLabelText('最大行数（行）')).toBeNull();expect(screen.queryByLabelText('配置变更理由')).toBeNull()
})
