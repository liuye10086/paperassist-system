import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import TaskEvents from './TaskEvents'
import TaskDetail from './TaskDetail'
import { eventsFixture, taskFixture, usageFixture, workspaceFixture } from './taskFixtures'
import { setLocale } from '../../shared/i18n'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); setLocale('zh-CN') })
const props = { taskId: 't1', live: false, refreshKey: 0 }
const event = { ...eventsFixture.items[0], event_type: 'deferred', status: 'queued', error_code: 'model_provider_unavailable',
  error_category: 'temporary', retry_reason: 'temporary_provider_error', retry_count: 1, retry_delay_seconds: 10 }
function api(items: unknown[]) {
  const fetch = vi.fn(async () => Response.json({ ...eventsFixture, items, next_cursor: items.length }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

it.each([[1, 10], [2, 30], [3, 90]])('shows the scheduled automatic retry %i with its %i second delay', async (count, delay) => {
  api([{ ...event, retry_count: count, retry_delay_seconds: delay }]); render(<TaskEvents {...props} />)
  await screen.findByText(`自动重试第 ${count}/3 次，等待 ${delay} 秒后继续。`)
  expect(screen.getByText('模型服务暂时不可用，请稍后重试。')).toBeTruthy()
  expect(screen.queryByText(/model_provider_unavailable|temporary_provider_error/)).toBeNull()
})
it.each([{ error_category: 'temporary', retry_reason: null }, { error_category: null, retry_reason: 'temporary_provider_error' }])(
  'shows manual continuation after an exhausted temporary failure %j', async metadata => {
    api([{ ...event, ...metadata, event_type: 'failed', status: 'failed', retry_count: 3, retry_delay_seconds: null }])
    render(<TaskEvents {...props} />)
    await screen.findByText('自动重试已用尽（3/3 次）。请核对问题后，通过任务处理手动继续原任务。')
    expect(screen.queryByText(/等待 \d+ 秒后继续/)).toBeNull()
  })
it('does not infer temporary exhaustion from a permanent error after earlier retries', async () => {
  api([{ ...event, event_type: 'failed', status: 'failed', error_code: 'model_authentication_failed',
    error_category: 'authentication', retry_reason: null, retry_count: 3, retry_delay_seconds: null }])
  render(<TaskEvents {...props} />)
  await screen.findByText('模型服务身份验证失败，请联系管理员检查凭据。')
  expect(screen.queryByText(/自动重试已用尽/)).toBeNull()
})
it('renders old missing and null metadata and ordinary deferred events without invented errors', async () => {
  api([eventsFixture.items[0], { ...event, seq: 2, error_code: null, error_category: null, retry_reason: null,
    retry_count: null, retry_delay_seconds: null }]); render(<TaskEvents {...props} />)
  await screen.findByText('等待后续处理')
  expect(screen.getAllByRole('listitem')).toHaveLength(2)
  expect(screen.queryByText(/模型服务|自动重试/)).toBeNull()
})
it('does not copy the current task error or retry count into historical events', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.includes('/model-usage') ? usageFixture
    : url.includes('/events') ? eventsFixture : { ...workspaceFixture, task: { ...taskFixture, retry_count: 3,
      error_code: 'model_authentication_failed' } })))
  render(<TaskDetail projectId="p1" taskId="t1" onChanged={vi.fn()} />)
  await screen.findByText('模型服务身份验证失败，请联系管理员检查凭据。')
  const history = screen.getByRole('region', { name: '执行记录' })
  expect(within(history).queryByText(/模型服务|自动重试/)).toBeNull()
})
it('shows a fixed category summary when no error code was saved', async () => {
  api([{ ...event, event_type: 'failed', status: 'failed', error_code: null, error_category: 'permission',
    retry_reason: null, retry_count: null, retry_delay_seconds: null }]); render(<TaskEvents {...props} />)
  await screen.findByText('模型服务权限不足，请联系管理员检查权限。')
})
it.each([
  ['worker_interrupted', '执行中断后已重新排队。', 'Requeued after execution was interrupted.'],
  ['manual_retry', '已手动继续原任务。', 'The original task was manually continued.'],
])('shows a fixed recovery reason for %s in both languages', async (retry_reason, zh, en) => {
  api([{ ...event, event_type: 'requeued', error_code: null, error_category: null,
    retry_reason, retry_count: null, retry_delay_seconds: null }]); render(<TaskEvents {...props} />)
  await screen.findByText(zh)
  act(() => setLocale('en')); expect(screen.getByText(en)).toBeTruthy()
  expect(screen.queryByText(retry_reason)).toBeNull()
})
it('uses a generic task interruption summary for real recovery events with a saved error code', async () => {
  api([{ ...event, event_type: 'requeued', error_code: 'task_worker_interrupted', error_category: 'interrupted',
    retry_reason: 'worker_interrupted', retry_count: 2, retry_delay_seconds: null }]); render(<TaskEvents {...props} />)
  await screen.findByText('任务执行中断，请重新读取状态后重试。')
  expect(screen.queryByText(/报告生成中断|task_worker_interrupted|worker_interrupted/)).toBeNull()
  act(() => setLocale('en'))
  expect(screen.getByText('Task execution was interrupted. Reload its status and retry.')).toBeTruthy()
  expect(screen.queryByText(/Report generation was interrupted|task_worker_interrupted|worker_interrupted/)).toBeNull()
})
it.each(['PRIVATE sk-secret resp-private', '__proto__', '\u001ePA_ERROR:{"code":"PRIVATE"}'])(
  'never displays an untrusted event error %s or response identifier', async error_code => {
    api([{ ...event, event_type: 'failed', status: 'failed', error_code, error_category: 'internal',
      retry_reason: null, retry_count: null, retry_delay_seconds: null, message: 'PRIVATE TRACE', response_id: 'resp-private' }])
    render(<TaskEvents {...props} />)
    await screen.findByText('服务暂时无法完成请求，请稍后重试。')
    expect(screen.queryByText(/PRIVATE|sk-secret|resp-private|__proto__|PA_ERROR/)).toBeNull()
  })
it('translates error history, retry scheduling and exhaustion into English', async () => {
  setLocale('en'); api([event, { ...event, seq: 2, event_type: 'failed', status: 'failed', retry_count: 3, retry_delay_seconds: null }])
  render(<TaskEvents {...props} />)
  await screen.findByText('Automatic retry 1/3: continue after 10 seconds.')
  expect(screen.getByText('All automatic retries have been used (3/3). Review the issue, then manually continue the original task under Task actions.')).toBeTruthy()
  expect(screen.getAllByText('The model service is temporarily unavailable. Please try again later.')).toHaveLength(2)
  expect(screen.queryByText(/自动重试|模型服务/)).toBeNull()
})
it('retains error history and its cursor across pagination, hidden-tab pause and manual refresh', async () => {
  vi.useFakeTimers()
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  const fetch = vi.fn(async (url: string) => Response.json(url.includes('after=0')
    ? { ...eventsFixture, items: [event], has_more: true }
    : url.includes('after=1') ? { ...eventsFixture, items: [{ ...event, seq: 2, retry_count: 2, retry_delay_seconds: 30 }], next_cursor: 2 }
      : { ...eventsFixture, items: [], next_cursor: 2 }))
  vi.stubGlobal('fetch', fetch); render(<TaskEvents {...props} />)
  await act(async () => {})
  act(() => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')) })
  await act(async () => { vi.advanceTimersByTime(15000) })
  expect(fetch).toHaveBeenCalledTimes(1)
  await act(async () => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls[1][0]).toContain('after=1&limit=50')
  expect(screen.getByText('自动重试第 1/3 次，等待 10 秒后继续。')).toBeTruthy()
  expect(screen.getByText('自动重试第 2/3 次，等待 30 秒后继续。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '刷新执行记录' }))
  await act(async () => {})
  expect(fetch.mock.calls[2][0]).toContain('after=2&limit=50')
  expect(screen.getAllByRole('listitem')).toHaveLength(2)
  await act(async () => { vi.advanceTimersByTime(15000) })
  expect(fetch).toHaveBeenCalledTimes(3)
})
