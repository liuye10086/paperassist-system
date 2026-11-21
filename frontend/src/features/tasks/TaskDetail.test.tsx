import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import TaskDetail from './TaskDetail'
import { eventsFixture, legacyTaskFixture, legacyWorkspaceFixture, preparationSourceFixture, preparationTaskFixture, taskFixture, usageFixture, workspaceFixture } from './taskFixtures'
import { setLocale } from '../../shared/i18n'
import { clearApiSession } from '../../shared/api/client'
import { watchProjectAccess } from '../../shared/api/projectAccess'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); setLocale('zh-CN') })
const props = { projectId: 'p1', taskId: 't1', onChanged: vi.fn() }
function api(workspace: unknown = workspaceFixture) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return Response.json({ ...taskFixture, status: 'queued', display_status: 'queued', revision: 4 })
    if (url.includes('/model-usage')) return Response.json(usageFixture)
    if (url.includes('/events')) return Response.json(eventsFixture)
    return Response.json(workspace)
  }); vi.stubGlobal('fetch', fetch); return fetch
}
it('takes a completed report interpretation task back to the report editor', async () => {
  const task={...taskFixture,task_type:'reader_report_narrative',status:'succeeded',display_status:'succeeded',phase:'interpret',reason_code:null,error_code:null,
    input_version:{kind:'reader_report_narrative',workflow_version:'reader_report_narrative_v1',narrative_id:'narrative-1',binding_sha256:'a'.repeat(64),bundle_sha256:'b'.repeat(64)}}
  const fetch=api({...workspaceFixture,task,wait:null,allowed_actions:[],source:{file_id:null,filename:'Spatial report',analysis_run_id:null,is_current:true}})
  render(<TaskDetail {...props} view="result"/>)
  const link=await screen.findByRole('link',{name:'返回分析报告'})
  expect(link.getAttribute('href')).toBe('#project=p1&section=artifacts&view=research-reports')
  expect(screen.getByText('详细解读已保存，可返回分析报告复核解读并生成文件。')).toBeTruthy()
  expect(screen.queryByText('此任务尚无已保存的成果。')).toBeNull()
  expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
})
it('links a native interpretation to its exact context and original task',async()=>{
 const task={...taskFixture,task_type:'reader_report_narrative',status:'succeeded',display_status:'succeeded',phase:'interpret',reason_code:null,error_code:null,
  input_version:{kind:'reader_report_narrative',workflow_version:'reader_report_narrative_v1',narrative_id:'narrative-1',binding_sha256:'a'.repeat(64),bundle_sha256:'b'.repeat(64)}}
 api({...workspaceFixture,task,wait:null,allowed_actions:[],source:{file_id:null,filename:'Spatial report',analysis_run_id:null,is_current:true},
  artifacts:{...workspaceFixture.artifacts,bio_reader_report_context_id:'context1'}})
 render(<TaskDetail {...props} view="result"/>)
 const link=await screen.findByRole('link',{name:'返回分析报告'})
 expect(link.getAttribute('href')).toBe('#project=p1&section=analysis&view=bio-reader-report&reportContext=context1&reportTask=t1')
})
it('links the fixed report from the task workspace without waiting for report details',async()=>{
 const task={...taskFixture,task_type:'research_report',status:'succeeded',display_status:'succeeded',phase:'export',
  reason_code:null,error_code:null,result_research_report_version_id:'report1',
  input_version:{schema_version:1,kind:'research_report',workflow_version:'research_report_v1',source_sha256:'a'.repeat(64),output_language:'en',real_model_calls:false,real_network_calls:false}}
 const workspace={...workspaceFixture,task,wait:null,allowed_actions:[],
  source:{file_id:null,filename:'Fixed report',analysis_run_id:null,is_current:true}}
 const fetch=vi.fn(async(url:string)=>url.endsWith('/research-reports/report1')?new Promise<Response>(()=>{}):Response.json(workspace))
 vi.stubGlobal('fetch',fetch)
 const taskReportReturn={view:'bio-reader-report' as const,fileId:'',reportContextId:'context1',resultVersionId:'ora1',
  entry:{requirementVersionId:'req1',scopeItemId:'customer.delivery.word'},intent:'report' as const}
 render(<TaskDetail {...props} view="result" {...{taskReportReturn}}/>)
 const link=await screen.findByRole('link',{name:'查看固定研究成果'})
 const target=new URLSearchParams(link.getAttribute('href')!.slice(1))
 expect(target.get('artifact')).toBe('report1')
 expect(target.get('reportReturn')).toContain('requirement=req1')
 expect(fetch.mock.calls.some(([url])=>url.includes('/research-reports/'))).toBe(false)
})
it('points a successful journal task to its saved suggestions and labels its events in both languages',async()=>{
 const workspace={task:{...taskFixture,task_type:'journal_recommendation',status:'succeeded',display_status:'succeeded',phase:'plan',reason_code:null,error_code:null,input_version:{kind:'journal_recommendation',recommendation_id:'journal1',workflow_version:'journal_recommendation_v1'}},source:{file_id:null,filename:'Frozen journal research',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}
 const open=vi.fn();vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/events')?{...eventsFixture,items:[{...eventsFixture.items[0],event_type:'succeeded',status:'succeeded',phase:'plan'}]}:workspace)))
 render(<TaskDetail {...props} onOpenJournals={open}/>);await screen.findByText('成果已保存')
 expect.soft(screen.queryByText('此任务尚无已保存的成果。')).toBeNull();expect.soft(screen.getByRole('region',{name:'执行记录'}).textContent).not.toContain('分析计划')
 expect(within(screen.getByRole('region',{name:'此任务的成果'})).getByText('期刊建议已保存，请打开期刊建议查看本批结果与来源。')).toBeTruthy();expect(within(screen.getByRole('region',{name:'执行记录'})).getByText('期刊建议')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'打开期刊建议'}));expect(open).toHaveBeenCalledTimes(1)
 act(()=>setLocale('en'));expect(screen.getByText('Journal suggestions are saved. Open journal suggestions to view this batch and its sources.')).toBeTruthy();expect(within(screen.getByRole('region',{name:'Execution history'})).getByText('Journal suggestions')).toBeTruthy()
})
it('uses server resume permission with the exact wait, input version and one idempotency key', async () => {
  const fetch = api(); render(<TaskDetail {...props} />)
  const button = await screen.findByRole('button', { name: '预算或配置已调整，继续任务' })
  expect(screen.getByText('分析配置 v1')).toBeTruthy()
  expect(screen.getByText('继续此任务；尚未提交的模型调用会按原策略和预算执行，已有调用沿用已保存结果。')).toBeTruthy()
  fireEvent.click(button); fireEvent.click(button)
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
  const [url, init] = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(url).toBe('/api/v1/tasks/t1/resume')
  expect(new Headers(init!.headers).get('Idempotency-Key')).toBeTruthy()
  expect(JSON.parse(String(init!.body))).toEqual({ operation: 'resume', wait_id: 'w1', expected_task_revision: 3, input_version: taskFixture.input_version })
  expect(props.onChanged).toHaveBeenCalled()
})
it('pauses hidden-tab polling without aborting or remounting an ongoing resume operation', async () => {
  vi.useFakeTimers()
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  let completePost!: (value: Response) => void
  const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST' ? new Promise<Response>(resolve => { completePost = resolve })
    : Promise.resolve(Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events')
      ? { ...eventsFixture, items: [], next_cursor: 0 } : workspaceFixture)))
  vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  const posted = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  const beforeHidden = fetch.mock.calls.length
  act(() => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')) })
  await act(async () => { vi.advanceTimersByTime(10_000) })
  expect(fetch).toHaveBeenCalledTimes(beforeHidden)
  expect(posted[1]?.signal?.aborted).toBe(false)
  await act(async () => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect((screen.getByRole('button', { name: '预算或配置已调整，继续任务' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => { completePost(Response.json({ ...taskFixture, revision: 4 })) })
  expect(props.onChanged).toHaveBeenCalled()
})
it('unknown submissions have no resume or paid retry form', async () => {
  api({ ...workspaceFixture, wait: { ...workspaceFixture.wait, kind: 'submission_unknown' }, allowed_actions: [] })
  render(<TaskDetail {...props} />)
  await screen.findByText('提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。')
  expect(screen.queryByRole('button', { name: /继续任务|重试原任务/ })).toBeNull()
  expect(screen.queryByRole('textbox')).toBeNull()
})
it('displays exact historical artifacts while a temporary reload failure preserves them', async () => {
  const workspace = { ...workspaceFixture, source: { ...workspaceFixture.source, is_current: false }, allowed_actions: [], wait: null,
    task: { ...taskFixture, status: 'succeeded', display_status: 'succeeded', result_figure_id: 'fig1' },
    artifacts: { ...workspaceFixture.artifacts, figure: { title: '历史箱线图', caption: '保存的图注', download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/figures/fig1/download' } } }
  let failure = false
  const fetch = vi.fn(async (url: string) => {
    if (url.includes('/model-usage')) return Response.json(usageFixture)
    if (url.includes('/events')) return Response.json(eventsFixture)
    if (failure) throw new TypeError('offline')
    return Response.json(workspace)
  }); vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  const link = await screen.findByRole('link', { name: '下载此任务的 PNG' })
  expect(link.getAttribute('href')).toContain('/r1/figures/fig1/download')
  failure = true; fireEvent.click(screen.getByRole('button', { name: '重新读取任务' }))
  await screen.findByText('任务详情读取失败，请重试。')
  expect(screen.getByText('历史箱线图')).toBeTruthy()
})
it('rejects task data for another project without showing its content', async () => {
  api({ ...workspaceFixture, task: { ...taskFixture, project_id: 'p2' }, source: { ...workspaceFixture.source, filename: '其他项目秘密.xlsx' } })
  render(<TaskDetail {...props} />)
  await screen.findByText('任务详情读取失败，请重试。')
  expect(screen.queryByText('其他项目秘密.xlsx')).toBeNull()
})
it('reads events incrementally and stops requests after unmount', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn(async (url: string) => Response.json(url.includes('/model-usage') ? usageFixture
    : url.includes('/events') ? url.includes('after=0') ? eventsFixture : { ...eventsFixture, items: [], next_cursor: 1 } : workspaceFixture))
  vi.stubGlobal('fetch', fetch); const view = render(<TaskDetail {...props} />)
  await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(5000) })
  expect(fetch.mock.calls.some(([url]) => url.includes('/events?after=1'))).toBe(true)
  view.unmount(); const count = fetch.mock.calls.length
  await act(async () => { vi.advanceTimersByTime(STANDARD_REQUEST_TIMEOUT_MS) })
  expect(fetch.mock.calls).toHaveLength(count)
})
it('reuses the same key after an unconfirmed response and a read of unchanged task state', async () => {
  let posts = 0
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      if (++posts === 1) throw new TypeError('connection lost')
      return Response.json({ ...taskFixture, status: 'queued', display_status: 'queued', revision: 4 })
    }
    return Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events')
      ? { ...eventsFixture, items: [], next_cursor: 0 } : workspaceFixture)
  }); vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '预算或配置已调整，继续任务' }))
  await screen.findByText('恢复请求未确认，请先重新读取任务。')
  await waitFor(() => expect((screen.getByRole('button', { name: '预算或配置已调整，继续任务' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  await waitFor(() => expect(posts).toBe(2))
  const keys = fetch.mock.calls.filter(([, init]) => init?.method === 'POST').map(([, init]) => new Headers(init!.headers).get('Idempotency-Key'))
  expect(keys[0]).toBeTruthy(); expect(keys[0]).toBe(keys[1])
})
it('shows unsupported waits without inventing a form or recovery action', async () => {
  api({ ...workspaceFixture, wait: { ...workspaceFixture.wait, kind: 'unsupported_input' }, allowed_actions: [] })
  render(<TaskDetail {...props} />)
  await screen.findByText('此任务需要的资料或确认暂未提供处理入口，请联系管理员。')
  expect(screen.queryByRole('textbox')).toBeNull(); expect(screen.queryByRole('button', { name: /继续.*任务|重试原任务/ })).toBeNull()
})
it('rejects an external artifact download URL', async () => {
  api({ ...workspaceFixture, task: { ...taskFixture, result_figure_id: 'fig1' },
    artifacts: { ...workspaceFixture.artifacts, figure: { title: 'unsafe', caption: '', download_url: 'https://other.example/private' } } })
  render(<TaskDetail {...props} />)
  await screen.findByText('任务详情读取失败，请重试。')
  expect(screen.queryByRole('link')).toBeNull()
})
it('renders actions and wait instructions in English without translating saved research', async () => {
  setLocale('en'); api(); render(<TaskDetail {...props} />)
  await screen.findByRole('button', { name: 'Budget or configuration updated — continue task' })
  expect(screen.getByText('实验.xlsx')).toBeTruthy()
  expect(screen.queryByText('任务正在等待预算或模型配置，请联系管理员调整后继续。')).toBeNull()
})
it('reuses the exact body and key after a hung resume request reaches its timeout', async () => {
  vi.useFakeTimers()
  let posts = 0
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return ++posts === 1 ? new Promise<Response>(() => {})
      : Promise.resolve(Response.json({ ...taskFixture, revision: 4 }))
    return Promise.resolve(Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events')
      ? { ...eventsFixture, items: [], next_cursor: 0 } : workspaceFixture))
  }); vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  await act(async () => { vi.advanceTimersByTime(STANDARD_REQUEST_TIMEOUT_MS+1) })
  expect(screen.getByText('恢复请求未确认，请先重新读取任务。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  await act(async () => {})
  const calls = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(calls).toHaveLength(2)
  expect(calls[0][1]?.signal?.aborted).toBe(true)
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})
it('reloads conflicts and creates a new key only for the newly reviewed revision', async () => {
  let current = workspaceFixture
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      current = { ...workspaceFixture, task: { ...taskFixture, revision: 4 }, wait: { ...workspaceFixture.wait, id: 'w2', task_revision: 4 } }
      return Response.json({ detail: { code: 'task_revision_conflict' } }, { status: 409 })
    }
    return Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events')
      ? { ...eventsFixture, items: [], next_cursor: 0 } : current)
  }); vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '预算或配置已调整，继续任务' }))
  await screen.findByText('任务状态已更新，请核对重新读取的内容后再操作。')
  await waitFor(() => expect((screen.getByRole('button', { name: '预算或配置已调整，继续任务' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2))
  const calls = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ operation: 'resume', wait_id: 'w2', expected_task_revision: 4, input_version: taskFixture.input_version })
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})
it('does not backfill a stale response when switching away from and back to a task', async () => {
  let completeOld!: (response: Response) => void
  let workspaceReads = 0
  const fetch = vi.fn((url: string) => {
    if (url.includes('/model-usage')) return Promise.resolve(Response.json(usageFixture))
    if (url.includes('/events')) return Promise.resolve(Response.json({ ...eventsFixture, task_id: url.includes('/t2/') ? 't2' : 't1', items: [], next_cursor: 0 }))
    if (++workspaceReads === 1) return new Promise<Response>(resolve => { completeOld = resolve })
    return Promise.resolve(Response.json({ ...workspaceFixture, task: { ...taskFixture, id: url.includes('/t2/') ? 't2' : 't1' },
      source: { ...workspaceFixture.source, filename: url.includes('/t2/') ? '第二任务.xlsx' : '当前配置.xlsx' } }))
  }); vi.stubGlobal('fetch', fetch)
  const view = render(<TaskDetail {...props} />)
  view.rerender(<TaskDetail {...props} taskId="t2" />)
  await screen.findByText('第二任务.xlsx')
  view.rerender(<TaskDetail {...props} />)
  await screen.findByText('当前配置.xlsx')
  await act(async () => { completeOld(Response.json({ ...workspaceFixture, source: { ...workspaceFixture.source, filename: '过期回包.xlsx' } })) })
  expect(screen.queryByText('过期回包.xlsx')).toBeNull()
  expect(screen.queryByText('第二任务.xlsx')).toBeNull()
  expect(screen.getByText('当前配置.xlsx')).toBeTruthy()
})
it('clears a missing task without invalidating its project', async () => {
  const unavailable = vi.fn(); const stop = watchProjectAccess('p1', unavailable)
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ detail: { code: 'task_not_found' } }, { status: 404 })))
  render(<TaskDetail {...props} />)
  await screen.findByText('任务不存在或无权访问，请选择其他任务。')
  expect(unavailable).not.toHaveBeenCalled(); stop()
})
it('clears private task detail, events and usage after session invalidation', async () => {
  api(); render(<TaskDetail {...props} />)
  await screen.findByText('实验.xlsx')
  await screen.findByText('test-model')
  act(() => clearApiSession())
  expect(screen.queryByText('实验.xlsx')).toBeNull()
  expect(screen.queryByText('test-model')).toBeNull()
  expect(screen.queryByRole('region', { name: '执行记录' })).toBeNull()
  expect(screen.queryByRole('button', { name: '预算或配置已调整，继续任务' })).toBeNull()
})
it.each(['zh-CN', 'en'] as const)('shows exact historical figure with honest missing history and usage in %s', async locale => {
  setLocale(locale)
  const fetch = api({ ...legacyWorkspaceFixture, private_receipt: 'RECEIPT_SENTINEL', source_hash: 'HASH_SENTINEL' })
  render(<TaskDetail {...props} taskId={legacyTaskFixture.id} />)
  const link = await screen.findByRole('link', { name: locale === 'en' ? 'Download this task’s PNG' : '下载此任务的 PNG' })
  expect(link.getAttribute('href')).toBe(legacyWorkspaceFixture.artifacts.figure.download_url)
  expect(screen.getByText(locale === 'en' ? 'Historical task' : '历史任务')).toBeTruthy()
  expect(screen.getByText(locale === 'en' ? 'The previous system did not record complete execution steps or model usage for this task.' : '旧系统未记录此任务的完整执行步骤和模型用量。')).toBeTruthy()
  expect(screen.queryByRole('region', { name: locale === 'en' ? 'Execution history' : '执行记录' })).toBeNull()
  expect(screen.queryByRole('region', { name: locale === 'en' ? 'Task usage' : '本次任务用量' })).toBeNull()
  expect(screen.queryByRole('region', { name: locale === 'en' ? 'Task actions' : '任务处理' })).toBeNull()
  for (const hidden of [legacyTaskFixture.id, 'RECEIPT_SENTINEL', 'HASH_SENTINEL', '$0', '仍可恢复', '当前执行次数']) expect(document.body.textContent).not.toContain(hidden)
  fireEvent.click(screen.getByRole('button', { name: locale === 'en' ? 'Reload task' : '重新读取任务' }))
  await waitFor(() => expect(fetch.mock.calls).toHaveLength(2))
  expect(fetch.mock.calls.every(([url, init]) => url.endsWith('/workspace') && !init?.method)).toBe(true)
})
it('keeps the exact historical explanation and reports uncertainty when no artifact can be confirmed', async () => {
  const legacy = { ...legacyWorkspaceFixture, task: { ...legacyTaskFixture, id: 'legacy-explanation:b2xk', task_type: 'explanation',
    phase: 'interpret', result_figure_id: null, result_explanation_id: 'expl-old' },
    artifacts: { figure: null, report: null, explanation: { sections: [{ key: 'summary', title: '原解释', text: '原研究文本' }], limitations: ['原限制'] } } }
  api(legacy)
  const view = render(<TaskDetail {...props} taskId={legacy.task.id} />)
  await screen.findByText('原研究文本')
  expect(screen.getByText('原限制')).toBeTruthy()
  view.unmount()
  api({ ...legacy, artifacts: { figure: null, report: null, explanation: null } })
  render(<TaskDetail {...props} taskId={legacy.task.id} />)
  await screen.findByText('无法确认此历史任务关联的成果。')
  expect(screen.queryByText('此任务尚无已保存的成果。')).toBeNull()
})
it('polls a historical running job until its saved result arrives, then stops detail polling', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn(async () => Response.json(fetch.mock.calls.length === 1 ? { ...legacyWorkspaceFixture,
    task: { ...legacyTaskFixture, status: 'running', display_status: 'computing', result_figure_id: null },
    artifacts: { figure: null, explanation: null, report: null } } : legacyWorkspaceFixture))
  vi.stubGlobal('fetch', fetch)
  const view = render(<TaskDetail {...props} taskId={legacyTaskFixture.id} />)
  await act(async () => {})
  expect(screen.getByText('数据计算中')).toBeTruthy()
  expect(screen.getByText('无法确认此历史任务关联的成果。')).toBeTruthy()
  await act(async () => { vi.advanceTimersByTime(5000) })
  expect(screen.getByText('已完成')).toBeTruthy()
  expect(screen.getByRole('link', { name: '下载此任务的 PNG' })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(2)
  await act(async () => { vi.advanceTimersByTime(20_000) })
  expect(fetch).toHaveBeenCalledTimes(2)
  view.unmount()
})
it.each([{ allowed_actions: ['retry'] }, { wait: workspaceFixture.wait }])('rejects historical workspace action contract violation %j', async invalid => {
  const fetch = api({ ...legacyWorkspaceFixture, ...invalid })
  render(<TaskDetail {...props} taskId={legacyTaskFixture.id} />)
  await screen.findByText('任务详情读取失败，请重试。')
  expect(screen.queryByText('保存的历史图')).toBeNull()
  expect(fetch.mock.calls).toHaveLength(1)
})
it.each(['zh-CN', 'en'] as const)('displays a safe historical error without exposing the original error in %s', async locale => {
  setLocale(locale)
  const fetch = api({ ...legacyWorkspaceFixture, task: { ...legacyTaskFixture, status: 'failed', display_status: 'failed',
    error_code: 'model_provider_unavailable', message: 'PRIVATE_ERROR_SENTINEL' } })
  render(<TaskDetail {...props} taskId={legacyTaskFixture.id} />)
  await screen.findByText(locale === 'en' ? 'The model service was unavailable when the historical task ran.' : '旧任务执行时模型服务不可用。')
  expect(document.body.textContent).not.toContain('PRIVATE_ERROR_SENTINEL')
  expect(fetch.mock.calls).toHaveLength(1)
  expect(screen.queryByRole('button', { name: /重试原任务|Retry original task/ })).toBeNull()
})
it.each([
  ['zh-CN', 'task_failed', '旧任务执行失败。'],
  ['en', 'task_failed', 'The historical task failed.'],
  ['zh-CN', 'explanation_invalid', '旧任务的解释未通过事实核验，未保存内容。'],
  ['en', 'explanation_invalid', 'The historical explanation failed fact verification and was not saved.'],
  ['zh-CN', 'model_submission_unknown', '旧任务的模型提交结果无法确认。'],
  ['en', 'model_submission_unknown', 'The historical model submission outcome could not be confirmed.'],
  ['zh-CN', 'PRIVATE_ERROR_SENTINEL', '旧系统记录了任务异常，具体原因无法确认。'],
  ['en', 'PRIVATE_ERROR_SENTINEL', 'The previous system recorded a task problem; the specific cause could not be confirmed.'],
] as const)('shows a safe readonly historical error for %s / %s', async (locale, error_code, reason) => {
  setLocale(locale)
  const fetch = api({ ...legacyWorkspaceFixture, task: { ...legacyTaskFixture, status: 'failed', display_status: 'failed',
    error_code, message: 'PRIVATE_PROVIDER_SENTINEL' } })
  render(<TaskDetail {...props} taskId={legacyTaskFixture.id} />)
  await screen.findByText(reason)
  expect(screen.getByText(locale === 'en' ? 'This historical task is available for viewing only; resume and retry are unavailable.' : '此历史任务仅供查看，不支持恢复或重试。')).toBeTruthy()
  for (const hidden of ['请检查数据和配置后重试', '请重新生成', 'before retrying', 'Generate it again', 'PRIVATE_PROVIDER_SENTINEL', 'PRIVATE_ERROR_SENTINEL']) {
    expect(document.body.textContent).not.toContain(hidden)
  }
  expect(screen.queryByRole('region', { name: locale === 'en' ? 'Task actions' : '任务处理' })).toBeNull()
  expect(fetch.mock.calls.every(([url, init]) => url.endsWith('/workspace') && !init?.method)).toBe(true)
})
it.each([
  ['zh-CN', 'task_failed', '任务执行失败，请检查数据和配置后重试。'],
  ['en', 'task_failed', 'The task failed. Check the data and configuration before retrying.'],
  ['zh-CN', 'explanation_invalid', '解释未通过事实核验，未发布新解释。请核对冻结的来源与统计结果，联系管理员处理；已有成果保留。'],
  ['en', 'explanation_invalid', 'The explanation failed fact verification; no new explanation was published. Review the frozen source and statistics, then contact the administrator. Existing artifacts are retained.'],
] as const)('shows current unified task guidance for %s / %s', async (locale, error_code, reason) => {
  setLocale(locale)
  api({ ...workspaceFixture, task: { ...taskFixture, error_code } })
  render(<TaskDetail {...props} />)
  await screen.findByText(reason)
  expect(screen.queryByText(locale === 'en' ? 'This historical task is available for viewing only; resume and retry are unavailable.' : '此历史任务仅供查看，不支持恢复或重试。')).toBeNull()
})
it('shows the fixed detailed suite from the actual Word task workspace', async () => {
  const { readerProjection } = await import('../reports/statisticsReaderFixtures')
  const projection = readerProjection('word_report', props.taskId)
  api({ ...workspaceFixture, wait: null, allowed_actions: [], task: { ...taskFixture, task_type: 'word_report',
    phase: 'export', status: 'succeeded', display_status: 'succeeded', result_report_id: 'report-new' },
    artifacts: { figure: null, explanation: null, reader_export: projection.reader_export,
      report: { filename: '固定报告.docx', download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/report/report-new/download', ...projection } } })
  render(<TaskDetail {...props} view="result" />)
  expect(await screen.findByText('Fixed results for this report.')).toBeTruthy()
  expect(screen.getByRole('link', { name: '下载 XLSX 结果表' }).getAttribute('href')).toBe(projection.members[1].download_url)
  expect(screen.getByRole('link', { name: '查看固定研究成果' }).getAttribute('href')).toBe('#project=p1&section=artifacts&view=research-reports&artifact=formal-report')
})

it('rejects a detailed task projection from another fixed report version', async () => {
  const { readerProjection } = await import('../reports/statisticsReaderFixtures')
  const projection = readerProjection('word_report', props.taskId)
  api({ ...workspaceFixture, wait: null, allowed_actions: [], task: { ...taskFixture, task_type: 'word_report',
    phase: 'export', status: 'succeeded', display_status: 'succeeded', result_report_id: 'report-new' },
    artifacts: { figure: null, explanation: null, reader_export: projection.reader_export,
      report: { filename: '固定报告.docx', download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/report/report-new/download',
        ...readerProjection('word_report', props.taskId, 'other-report') } } })
  render(<TaskDetail {...props} view="result" />)
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByRole('link')).toBeNull()
})

it('preserves the saved unified Word download route', async () => {
  api({ ...workspaceFixture, wait: null, allowed_actions: [], task: { ...taskFixture, task_type: 'word_report',
    phase: 'export', status: 'succeeded', display_status: 'succeeded', result_report_id: 'report-old' },
    artifacts: { figure: null, explanation: null, report: { filename: '原报告.docx', download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/report/report-old/download' } } })
  render(<TaskDetail {...props} />)
  const link = await screen.findByRole('link', { name: '下载此任务的 Word' })
  expect(link.getAttribute('href')).toBe('/api/v1/projects/p1/files/f1/analysis-runs/r1/report/report-old/download')
})

it('shows parsing success without analysis versions or model usage and opens project files',async()=>{
 const task={...taskFixture,task_type:'parse_file',phase:'parse',status:'succeeded',display_status:'succeeded',input_version:{kind:'parse_file',parse_id:'parse1',source_sha256:'a'.repeat(64),parser_version:'openpyxl-3.1.5-preview-v1'}}
 const fetch=api({task,source:{file_id:'f1',filename:'data.xlsx',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}})
 const onOpenFiles=vi.fn();render(<TaskDetail {...props} onOpenFiles={onOpenFiles}/>);await screen.findByText('文件已解析，请到项目文件区查看预览。');expect(screen.queryByText(/分析配置 v/)).toBeNull();expect(fetch.mock.calls.some(([url])=>url.includes('model-usage'))).toBe(false);fireEvent.click(screen.getByRole('button',{name:'查看项目文件'}));expect(onOpenFiles).toHaveBeenCalledOnce()
})
it('shows a preparation detail as a local preview without an analysis setup or model usage', async () => {
 const task = preparationTaskFixture
 const source = preparationSourceFixture
 const workspace = { task, source: { file_id: 'f1', filename: 'data.xlsx', analysis_run_id: null, is_current: true, dataset_source: source }, wait: null, allowed_actions: [], artifacts: { figure: null, explanation: null, report: null } }
 const review = { task, source, checkpoint_id: 'checkpoint1', recipe_revision: 1, recipe: { header_row: 1, data_range: 'A2:B3', fields: [] }, preview: null, changes: [], preview_download_url: null, result: null, wait: null }
 const fetch = vi.fn(async (url: string) => Response.json(url.endsWith('/dataset-preparation') ? review : url.includes('/events') ? { ...eventsFixture, items: [], next_cursor: 0 } : workspace))
 vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
 await screen.findByText('本地数据整理')
 expect(screen.getByText('整理预览')).toBeTruthy()
 expect(screen.queryByText(/分析配置 v/)).toBeNull()
 expect(screen.queryByText('当前分析配置')).toBeNull()
 expect(fetch.mock.calls.some(([url]) => url.includes('/model-usage'))).toBe(false)
})
it('opens frozen manuscript writing from task details without an analysis configuration or authorization button',async()=>{
 const input={kind:'manuscript_writing',base_version_id:'v1',base_revision:1,output_language:'en',workflow_version:'manuscript_writing_v1'}
 const task={...taskFixture,task_type:'manuscript_writing',phase:'write',input_version:input,error_code:'manuscript_writing_not_authorized',reason_code:'confirmation_required'}
 api({...workspaceFixture,task,source:{file_id:null,analysis_run_id:null,filename:'Saved draft',is_current:true},wait:{...workspaceFixture.wait,kind:'unsupported_confirmation',input_version:input},allowed_actions:[]})
 render(<TaskDetail {...props}/>);expect(await screen.findByText('已冻结的写作基础版本 1')).toBeTruthy();expect(await screen.findByText('稿件历史读取失败，请重试。')).toBeTruthy();expect(screen.queryByText('分析配置 v0')).toBeNull()
})

it('links a successful format task back to frozen journal results without model usage and labels verify events',async()=>{
 const input={kind:'journal_format_check',check_id:'c1',target_id:'target1',guide_id:'g1',requirements_version:'a'.repeat(64),manuscript_version_id:'v1',check_version:1,workflow_version:'journal_format_check_v1'}
 const task={...taskFixture,task_type:'journal_format_check',status:'succeeded',display_status:'succeeded',phase:'verify',reason_code:null,error_code:null,input_version:input}
 const fetch=vi.fn(async(url:string)=>Response.json(url.includes('/events')?{...eventsFixture,items:[{...eventsFixture.items[0],event_type:'succeeded',status:'succeeded',phase:'verify'}]}:{task,source:{file_id:null,filename:'Old manuscript',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}));vi.stubGlobal('fetch',fetch);const open=vi.fn();render(<TaskDetail {...props} onOpenJournals={open}/>);await screen.findByText('期刊格式检查结果已保存，请打开期刊建议查看固定版本与调整清单。')
 expect(screen.queryByText('此任务尚无已保存的成果。')).toBeNull();expect(await within(screen.getByRole('region',{name:'执行记录'})).findByText('期刊格式检查')).toBeTruthy();expect(fetch.mock.calls.some(([url])=>url.includes('/model-usage'))).toBe(false);fireEvent.click(screen.getByRole('button',{name:'打开期刊建议'}));expect(open).toHaveBeenCalledOnce()
})

it('retries failed format tasks through public recovery with the complete frozen input version',async()=>{
 const input={kind:'journal_format_check',check_id:'old-check',target_id:'old-target',guide_id:'old-guide',requirements_version:'a'.repeat(64),manuscript_version_id:'old-v1',check_version:1,workflow_version:'journal_format_check_v1'}
 const task={...taskFixture,task_type:'journal_format_check',phase:'verify',status:'failed',display_status:'failed',error_code:'task_failed',reason_code:null,input_version:input}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...task,status:'queued',display_status:'queued',revision:4}:url.includes('/events')?{...eventsFixture,items:[],next_cursor:0}:{task,source:{file_id:null,filename:'Old manuscript',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null}}));vi.stubGlobal('fetch',fetch);render(<TaskDetail {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'重试原任务'}));await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));const [url,init]=fetch.mock.calls.find(([,init])=>init?.method==='POST')!;expect(url).toBe('/api/v1/tasks/t1/resume');expect(JSON.parse(String(init!.body))).toEqual({operation:'retry',wait_id:null,expected_task_revision:3,input_version:input});expect(screen.getByText('使用冻结的目标、指南要求与稿件版本重试；不访问外网或调用模型。')).toBeTruthy()
})
it('recovers an independent adaptation task with its exact input and finite local wording',async()=>{
 const input={kind:'journal_adaptation',adaptation_id:'a1',target_id:'target1',check_id:'c1',requirements_version:'a'.repeat(64),manuscript_version_id:'v1',workflow_version:'journal_adaptation_v1'}
 const task={...taskFixture,task_type:'journal_adaptation',phase:'verify',status:'failed',display_status:'failed',error_code:'task_failed',reason_code:null,input_version:input}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...task,status:'queued',display_status:'queued',revision:4}:url.includes('/events')?{...eventsFixture,items:[{...eventsFixture.items[0],phase:'verify'}]}:{task,source:{file_id:null,filename:'Old manuscript',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null}}));vi.stubGlobal('fetch',fetch);render(<TaskDetail {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'重试原任务'}));await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true))
 const [url,init]=fetch.mock.calls.find(([,init])=>init?.method==='POST')!;expect(url).toBe('/api/v1/tasks/t1/resume');expect(JSON.parse(String(init!.body))).toEqual({operation:'retry',wait_id:null,expected_task_revision:3,input_version:input})
 expect(screen.getByText('使用冻结的期刊适配、所选动作与父稿重试；不访问外网或调用模型。')).toBeTruthy();expect(screen.queryByText(/尚未提交的模型调用/)).toBeNull();expect(fetch.mock.calls.some(([url])=>url.includes('/model-usage'))).toBe(false);expect(await within(screen.getByRole('region',{name:'执行记录'})).findByText('期刊指南适配')).toBeTruthy()
})

const structureTask = { ...taskFixture, task_type: 'extract_dataset', phase: 'parse', status: 'succeeded', display_status: 'succeeded', reason_code: null, error_code: null,
  input_version: { kind: 'excel_structure', structure_id: 's1', source_sha256: 'a'.repeat(64), parser_version: 'openpyxl-3.1.5-structure-v1' } }
const structureWorkspace = { ...workspaceFixture, task: structureTask, source: { ...workspaceFixture.source, analysis_run_id: null }, wait: null, allowed_actions: [],
  artifacts: { figure: null, explanation: null, report: null, dataset: { filename: 'structure.json', download_url: '/api/v1/projects/p1/datasets/s1/download' } } }
it('hides the internal structure JSON download from customers but keeps it for staff', async () => {
  api(structureWorkspace)
  const view = render(<TaskDetail {...props} customerView />)
  await screen.findByText('Excel 结构提取')
  expect(screen.queryByRole('link', { name: '下载完整 JSON' })).toBeNull()
  view.unmount()
  render(<TaskDetail {...props} />)
  expect(await screen.findByRole('link', { name: '下载完整 JSON' })).toBeTruthy()
})
it('embedded task details render without their own heading and leave focus alone', async () => {
  api()
  const outside = document.createElement('button'); document.body.append(outside); outside.focus()
  render(<TaskDetail {...props} embedded />)
  await screen.findByText('实验.xlsx')
  expect(screen.queryByRole('heading', { level: 2, name: '任务详情' })).toBeNull()
  expect(document.activeElement).toBe(outside)
  expect(screen.getByRole('button', { name: '重新读取任务' })).toBeTruthy()
  outside.remove()
})
it('keeps the default heading and focus when not embedded', async () => {
  api()
  render(<TaskDetail {...props} />)
  const heading = await screen.findByRole('heading', { level: 2, name: '任务详情' })
  expect(document.activeElement).toBe(heading)
})
it('passes the customer view to pending actions', async () => {
  api()
  render(<TaskDetail {...props} customerView view="actions" />)
  expect(await screen.findByText('系统正在核对，请稍后刷新或联系客服。')).toBeTruthy()
  expect(screen.queryByText('任务正在等待预算或模型配置，请联系管理员调整后继续。')).toBeNull()
  expect(screen.getByRole('button', { name: '继续原任务' })).toBeTruthy()
})
// B05 task 17: on the customer task page “处理依据” names the customer's own material; staff keep the input wording.
const roundPlanWorkspace = { ...workspaceFixture, wait: null, allowed_actions: [],
  task: { ...taskFixture, task_type: 'review_round_plan', phase: 'verify', status: 'succeeded', display_status: 'succeeded', reason_code: null, error_code: null,
    input_version: { kind: 'review_round_plan', round_id: 'r1', base_version_id: 'v1', workflow_version: 'review_round_plan_v1' } },
  source: { file_id: null, filename: '一审意见', analysis_run_id: null, is_current: true } }
const basis = () => screen.getByText(/^(处理依据|输入版本|Decision basis)$/).parentElement!.querySelector('dd')!.textContent
it.each([
  ['an uploaded file', structureWorkspace, '上传的文件', 'The uploaded file', '本地 Excel 结构提取'],
  ['a review round', roundPlanWorkspace, '本轮意见和送审稿', 'The comments of this round and the manuscript under review', '冻结的意见来源与固定稿件版本'],
  ['a saved analysis setup', { ...workspaceFixture, wait: null, allowed_actions: [] }, '已保存的分析配置', 'Saved analysis settings', '分析配置 v1'],
] as const)('names %s as the customer basis in both languages and keeps the staff wording', async (_name, workspace, zh, en, staff) => {
  api(workspace)
  const view = render(<TaskDetail {...props} customerView allowUsage={false} />)
  await screen.findByText('处理依据')
  expect(basis()).toContain(zh)
  expect(basis()).not.toMatch(/冻结|本地|固定/)
  view.unmount()
  setLocale('en')
  const english = render(<TaskDetail {...props} customerView allowUsage={false} />)
  await screen.findByText('Decision basis')
  expect(basis()).toContain(en)
  english.unmount()
  setLocale('zh-CN')
  render(<TaskDetail {...props} />)
  await screen.findByText('输入版本')
  expect(basis()).toContain(staff)
})
const customerSourceConflictZh = '本次任务使用的资料或版本与记录不一致。请重新读取任务，核对所选资料和版本。如果仍有问题，请联系客服。'
const customerSourceConflictEn = 'The materials or version used for this task do not match its record. Reload the task and check the selected materials and version. If the issue persists, contact support.'

it.each(['source_conflict', 'task_source_conflict'])('explains %s for the customer and staff across the review task views', async code => {
  const workspace = { ...roundPlanWorkspace, allowed_actions: ['retry'],
    task: { ...roundPlanWorkspace.task, status: 'failed', display_status: 'failed', error_code: code } }
  const failure = { ...eventsFixture.items[0], status: 'failed', event_type: 'failed', error_category: 'source' }
  const events = { ...eventsFixture, items: [{ ...failure, error_code: code }, { ...failure, seq: 2 }], next_cursor: 2 }
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return Response.json({ detail: { code } }, { status: 409 })
    if (url.includes('/events?after=2')) return Response.json({ ...events, items: [] })
    return Response.json(url.includes('/events') ? events : workspace)
  })
  vi.stubGlobal('fetch', fetch)
  const page = render(<TaskDetail {...props} allowUsage={false} customerView />)
  const records = await screen.findByRole('region', { name: '执行记录' })
  await waitFor(() => expect(within(records).getAllByRole('listitem')).toHaveLength(2))
  expect(page.container.querySelector('.task-overview-view .warning-panel')?.textContent).toBe(customerSourceConflictZh)
  expect(within(records).getAllByText(customerSourceConflictZh)).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: '重试原任务' }))
  expect((await screen.findByRole('alert')).textContent).toBe(customerSourceConflictZh)

  act(() => setLocale('en'))
  expect(screen.getAllByText(customerSourceConflictEn)).toHaveLength(4)
  expect(page.container.textContent).not.toMatch(/frozen|冻结/i)
  expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)

  page.unmount()
  const staff = render(<TaskDetail {...props} allowUsage={false} />)
  await screen.findByText(/review the frozen source/i, { selector: '.task-overview-view .warning-panel' })
  await waitFor(() => expect(staff.container.querySelectorAll('.task-event-error')).toHaveLength(2))
  expect(screen.getAllByText(/review the frozen source/i)).toHaveLength(3)
  act(() => setLocale('zh-CN'))
  expect(screen.getAllByText(/核对冻结的来源/)).toHaveLength(3)
})

it('explains a source conflict when the customer reloads a review task workspace', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ detail: { code: 'task_source_conflict' } }, { status: 409 })))
  render(<TaskDetail {...props} customerView view="overview" />)
  expect((await screen.findByRole('alert')).textContent).toBe(customerSourceConflictZh)
  act(() => setLocale('en'))
  expect(screen.getByRole('alert').textContent).toBe(customerSourceConflictEn)
})
