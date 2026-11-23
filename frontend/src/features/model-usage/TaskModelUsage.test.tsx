import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import TaskModelUsage from './TaskModelUsage'
import { usageFixture } from '../tasks/taskFixtures'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('shows task usage without budget controls and keeps unknown cost pending', async () => {
  const fetch = vi.fn(async (_url: string) => Response.json(usageFixture)); vi.stubGlobal('fetch', fetch)
  render(<TaskModelUsage taskId="t1" />)
  await screen.findByText('任务内部估算')
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/tasks/t1/model-usage?page=1&page_size=10')
  expect(screen.queryByText('用户预算')).toBeNull(); expect(screen.queryByText('项目预算')).toBeNull()
  const row = screen.getByText('test-model').closest('tr')!
  expect(within(row).getByText('待核对')).toBeTruthy()
  expect(within(row).queryByText('USD 0.000000')).toBeNull()
  expect(screen.queryByText('call-private')).toBeNull()
})
