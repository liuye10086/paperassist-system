import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useState } from 'react'
import ProjectTasks from './ProjectTasks'
import TaskDetail from './TaskDetail'
import TaskEvents from './TaskEvents'
import TaskModelUsage from '../model-usage/TaskModelUsage'
import { eventsFixture, pageFixture, taskFixture, usageFixture, workspaceFixture } from './taskFixtures'
import { reviewFixture } from '../analysisPlan/analysisPlanFixtures'
import AnalysisPlanReview from '../analysisPlan/AnalysisPlanReview'
import RequirementReview from '../analysisPlan/RequirementReview'
import { RecommendationResult } from '../analysisPlan/AnalysisRecommendation'
import type { TaskDetailView } from '../projects/reviewViews'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

function taskApi() {
  const fetch = vi.fn(async (url: string) => Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events') ? eventsFixture : url.includes('/projects/') ? pageFixture : workspaceFixture))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

it('shows only the selected detail view and reads events and usage on demand', async () => {
  const fetch = taskApi()
  const change = vi.fn()
  const props = { projectId: 'p1', taskId: 't1', onChanged: vi.fn(), onViewChange: change }
  const view = render(<TaskDetail {...props} view="overview" />)
  await screen.findByText('分析配置 v1')
  expect(screen.queryByRole('button', { name: '预算或配置已调整，继续任务' })).toBeNull()
  expect(screen.queryByRole('region', { name: '此任务的成果' })).toBeNull()
  expect(fetch.mock.calls.every(([url]) => url.endsWith('/workspace'))).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '待处理' }))
  expect(change).toHaveBeenCalledWith('actions')
  view.rerender(<TaskDetail {...props} view="actions" />)
  expect(screen.getByRole('button', { name: '预算或配置已调整，继续任务' })).toBeTruthy()
  expect(screen.queryByText('分析配置 v1')?.closest('[hidden]')).toBeTruthy()
  view.rerender(<TaskDetail {...props} view="events" />)
  await screen.findByRole('region', { name: '执行记录' })
  await act(async () => {})
  expect(fetch.mock.calls.some(([url]) => url.includes('/events'))).toBe(true)
  expect(fetch.mock.calls.some(([url]) => url.includes('/model-usage'))).toBe(false)
  view.rerender(<TaskDetail {...props} view="usage" />)
  await screen.findByText('test-model')
  expect(screen.queryByRole('region', { name: '执行记录' })).toBeNull()
})

it('keeps plan drafts across task switches, list navigation and inactive project views', async () => {
  const plan = { ...reviewFixture.task, origin: 'unified' }
  const workspace = { ...workspaceFixture, task: plan, wait: null, allowed_actions: [], source: { ...workspaceFixture.source, analysis_run_id: null, dataset_source: reviewFixture.source } }
  const fetch = vi.fn(async (url: string) => Response.json(url.endsWith('/analysis-plan') ? reviewFixture : url.endsWith('/t2/workspace') ? { ...workspaceFixture, task: { ...taskFixture, id: 't2' } } : url.includes('/projects/') ? { ...pageFixture, items: [{ task: plan, source: workspace.source }] } : workspace))
  vi.stubGlobal('fetch', fetch)
  function Harness({ active = true }: { active?: boolean }) {
    const [id, select] = useState('t1')
    const [view, setView] = useState<TaskDetailView>('actions')
    return <><button onClick={() => select('t2')}>另一任务</button><button onClick={() => select('t1')}>原任务</button><ProjectTasks projectId="p1" active={active} selectedTaskId={id} onSelectTask={select} detailView={view} onDetailViewChange={setView} /></>
  }
  const view = render(<Harness />)
  await screen.findByText('C5')
  fireEvent.click(screen.getByRole('button', { name: '修改字段重审' }))
  fireEvent.change(screen.getByLabelText('数值列'), { target: { value: 'D' } })
  fireEvent.click(screen.getByRole('button', { name: '另一任务' }))
  await act(async () => {})
  view.rerender(<Harness active={false} />)
  const count = fetch.mock.calls.length
  await act(async () => {})
  expect(fetch).toHaveBeenCalledTimes(count)
  view.rerender(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: '原任务' }))
  expect((screen.getByLabelText('数值列') as HTMLInputElement).value).toBe('D')
  fireEvent.click(screen.getByRole('button', { name: '返回任务列表' }))
  expect(screen.queryByRole('region', { name: '任务详情' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '原任务' }))
  expect((screen.getByLabelText('数值列') as HTMLInputElement).value).toBe('D')
})

it('stops hidden polling without aborting a submitted action and retains its error guard', async () => {
  vi.useFakeTimers()
  let rejectPost!: (e: Error) => void
  const guards = new Set<() => boolean>()
  const register = (guard: () => boolean) => { guards.add(guard); return () => { guards.delete(guard) } }
  const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST' ? new Promise<Response>((_resolve, reject) => { rejectPost = reject }) : Promise.resolve(Response.json(url.includes('/projects/') ? pageFixture : workspaceFixture)))
  vi.stubGlobal('fetch', fetch)
  vi.spyOn(window, 'alert').mockImplementation(() => {})
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  const props = { projectId: 'p1', selectedTaskId: 't1', onSelectTask: vi.fn(), detailView: 'actions' as const, onDetailViewChange: vi.fn(), registerLeaveGuard: register }
  const view = render(<ProjectTasks {...props} active />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  expect([...guards].every(guard => guard())).toBe(false)
  const post = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  view.rerender(<ProjectTasks {...props} active={false} />)
  const count = fetch.mock.calls.length
  await act(async () => { vi.advanceTimersByTime(10_000) })
  expect(fetch).toHaveBeenCalledTimes(count)
  expect(post[1]?.signal?.aborted).toBe(false)
  await act(async () => { rejectPost(new TypeError('offline')) })
  expect([...guards].every(guard => guard())).toBe(false)
  expect(confirm).toHaveBeenCalled()
  view.rerender(<ProjectTasks {...props} active />)
  expect(screen.getByText('恢复请求未确认，请先重新读取任务。')).toBeTruthy()
})

it('preserves list filters and page while the project tasks view is inactive', async () => {
  const fetch = vi.fn(async (url: string) => Response.json({ ...pageFixture, total: 20, page: Number(new URL(url, 'http://local').searchParams.get('page')) }))
  vi.stubGlobal('fetch', fetch)
  const props = { projectId: 'p1', selectedTaskId: '', onSelectTask: vi.fn(), detailView: 'overview' as const, onDetailViewChange: vi.fn() }
  const view = render(<ProjectTasks {...props} active />)
  await screen.findByText('实验.xlsx')
  fireEvent.change(screen.getByLabelText('任务状态'), { target: { value: 'failed' } })
  await screen.findByText('实验.xlsx')
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByText('共 20 项 · 第 2 / 2 页')
  view.rerender(<ProjectTasks {...props} active={false} />)
  view.rerender(<ProjectTasks {...props} active />)
  expect((screen.getByLabelText('任务状态') as HTMLSelectElement).value).toBe('failed')
  await screen.findByText('共 20 项 · 第 2 / 2 页')
  expect(fetch.mock.calls.at(-1)?.[0]).toContain('page=2&page_size=10&status=failed')
})

it('preserves usage pagination after hiding and reopening the view', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json({ ...usageFixture, total: 20, page: Number(new URL(url, 'http://local').searchParams.get('page')) })))
  const view = render(<TaskModelUsage taskId="t1" active />)
  await screen.findByText('test-model')
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByText('共 20 项 · 第 2 / 2 页')
  view.rerender(<TaskModelUsage taskId="t1" active={false} />)
  view.rerender(<TaskModelUsage taskId="t1" active />)
  expect(within(screen.getByRole('navigation', { name: '任务用量分页' })).getByText('共 20 项 · 第 2 / 2 页')).toBeTruthy()
})

it('never offers resume for an unknown submission even with stale server capabilities', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...workspaceFixture, wait: { ...workspaceFixture.wait, kind: 'submission_unknown' }, allowed_actions: ['resume', 'retry'] })))
  render(<TaskDetail projectId="p1" taskId="t1" view="actions" onViewChange={vi.fn()} onChanged={vi.fn()} />)
  await screen.findByText('提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。')
  expect(screen.queryByRole('button', { name: /继续任务|重试原任务/ })).toBeNull()
})

it('pauses hidden event polling and resumes from the retained cursor', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn(async () => Response.json(eventsFixture))
  vi.stubGlobal('fetch', fetch)
  const props = { taskId: 't1', taskType: 'boxplot' as const, live: true, refreshKey: 0 }
  const view = render(<TaskEvents {...props} active />)
  await act(async () => {})
  view.rerender(<TaskEvents {...props} active={false} />)
  const count = fetch.mock.calls.length
  await act(async () => { vi.advanceTimersByTime(20_000) })
  expect(fetch).toHaveBeenCalledTimes(count)
  view.rerender(<TaskEvents {...props} active />)
  await act(async () => {})
  // The event request helper receives the retained cursor, rather than replaying the first page.
  const calls = vi.mocked(globalThis.fetch).mock.calls
  expect(String(calls.at(-1)?.[0])).toContain('after=1')
  expect(screen.getAllByText('任务已建立')).toHaveLength(1)
})

it.each(['plan', 'requirement', 'recommendation'] as const)('does not read the hidden %s action view before it is visited', async kind => {
  const fetch = vi.fn(async () => Response.json({}))
  vi.stubGlobal('fetch', fetch)
  render(kind === 'plan' ? <AnalysisPlanReview projectId="p1" taskId="t1" active={false} /> : kind === 'requirement' ? <RequirementReview projectId="p1" taskId="t1" active={false} /> : <RecommendationResult projectId="p1" taskId="t1" active={false} />)
  await act(async () => {})
  expect(fetch).not.toHaveBeenCalled()
})

it('keeps the recommendation action read only when an unknown submission has stale resume permission', async () => {
  const input = { ...reviewFixture.input_version, kind: 'analysis_recommendation', workflow_version: 'analysis_recommendation_v1' }
  const task = { ...reviewFixture.task, task_type: 'analysis_recommendation', reason_code: 'submission_unknown', input_version: input }
  const result = { task, source: reviewFixture.source, input_version: input, request: { dataset_id: reviewFixture.source.dataset_id, sheet_name: 'Sheet1', candidate_columns: ['C'], output_language: 'en', research_summary: 'safe' }, external_processing: { version: 1, provider: 'openai', task_type: 'analysis_recommendation', source_digest: 'digest', labels: { 'field:C': 'weight', research_summary: 'safe' }, confirmed_by: 'user', confirmed_at: task.created_at, confirmation_digest: 'd'.repeat(64) }, recommendation: null }
  const workspace = { task, source: { file_id: 'f1', filename: 'synthetic.xlsx', analysis_run_id: null, is_current: true, dataset_source: reviewFixture.source }, wait: { ...workspaceFixture.wait, kind: 'submission_unknown', input_version: input }, allowed_actions: ['resume', 'retry'], artifacts: { figure: null, explanation: null, report: null } }
  const fetch = vi.fn(async (url: string) => Response.json(url.endsWith('/workspace') ? workspace : result))
  vi.stubGlobal('fetch', fetch)
  render(<RecommendationResult projectId="p1" taskId="t1" />)
  await screen.findByText('提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。')
  expect(screen.queryByRole('button', { name: /继续任务|重试原任务/ })).toBeNull()
  expect(fetch.mock.calls).toHaveLength(2)
})
