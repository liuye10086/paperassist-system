import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import ProjectInfoActions from './ProjectInfoActions'
import type { OverviewView } from './projectNavigation'
import type { Project } from './projectTypes'

vi.mock('./ProjectSummary', () => ({ default: () => <p>进展内容</p> }))
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
const project: Project = { id: 'p1', name: '研究', research_topic: '主题', project_type: 'research', file_count: 0, created_at: '2026-11-04T00:00:00Z', updated_at: '2026-11-04T00:00:00Z' }
const budget = { scope_type: 'user', limit_micro_usd: null, revision: 0, estimated_micro_usd: 0, reserved_micro_usd: 0, available_micro_usd: null, exceeded: false }

function Harness() {
  const [view, setView] = useState<OverviewView>('settings')
  return <ProjectInfoActions project={project} active view={view} onViewChange={setView} onOpenJournals={vi.fn()} onOpenManuscripts={vi.fn()}><p>资料内容</p></ProjectInfoActions>
}

test('loads usage on first visit and retains its page and subview without clearing content on module switches', async () => {
  const fetcher = vi.fn(async (url: string) => {
    const page = Number(new URL(url, 'http://test').searchParams.get('page'))
    return Response.json({ currency: 'USD', period: 'cumulative', enforcement_scope: 'unified_only', user_budget: budget,
      project_budget: { ...budget, scope_type: 'project' }, estimated_micro_usd: 0, reserved_micro_usd: 0, pending_count: 0,
      total: 11, page, page_size: 10, items: [{ id: `call-${page}`, task_type: 'explanation', model: `page-${page}`, status: 'completed',
        provider_status: null, usage_status: 'pending', estimated_cost_micro_usd: null, created_at: '2026-11-04T00:00:00Z', updated_at: '2026-11-04T00:00:00Z' }] })
  })
  vi.stubGlobal('fetch', fetcher)
  const user = userEvent.setup()
  render(<Harness />)
  expect(fetcher).not.toHaveBeenCalled()
  await user.click(screen.getByRole('tab', { name: '项目用量' }))
  await user.click(screen.getByRole('button', { name: '逐次调用' }))
  await screen.findByText('page-1')
  await user.click(screen.getByRole('button', { name: '模型调用下一页' }))
  await screen.findByText('page-2')
  await user.click(screen.getByRole('tab', { name: '项目资料' }))
  await user.click(screen.getByRole('tab', { name: '项目用量' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '逐次调用' }).getAttribute('aria-pressed')).toBe('true'))
  expect(screen.getByText('page-2')).toBeTruthy()
  expect(fetcher).toHaveBeenCalledTimes(2)
})
