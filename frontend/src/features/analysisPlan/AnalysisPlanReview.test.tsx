import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPlanReview from './AnalysisPlanReview'
import { reviewFixture } from './analysisPlanFixtures'
import { type PreparedDatasetAnalysisSource } from '../analysis/datasetSource'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('rejects a valid task review from another prepared source',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(reviewFixture)))
 render(<AnalysisPlanReview projectId="p1" taskId="t1" expectedSource={{...reviewFixture.source,dataset_id:'other'} as PreparedDatasetAnalysisSource}/>)
 await screen.findByRole('alert')
 expect(screen.queryByRole('button',{name:'确认并发布分析计划'})).toBeNull()
})

test('requires one resolution per warning and sends an immutable approval token', async () => {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => url.endsWith('/analysis-plan/decisions') ? Response.json(reviewFixture.task) : Response.json(reviewFixture))
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<AnalysisPlanReview projectId="p1" taskId="t1" />)
  expect(await screen.findByText('C5')).toBeTruthy()
  const approve = screen.getByRole('button', { name: '确认并发布分析计划' }) as HTMLButtonElement
  expect(approve.disabled).toBe(true)
  await user.selectOptions(screen.getByLabelText('处理：所选字段存在缺失值（C）'), 'exclude_selected_missing')
  expect(approve.disabled).toBe(false)
  await user.click(approve)
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/analysis-plan/decisions'))).toBe(true))
  const body = JSON.parse(fetch.mock.calls.find(([url]) => url.endsWith('/analysis-plan/decisions'))![1]?.body as string)
  expect(body).toMatchObject({ operation: 'approve', checkpoint_id: 'cp1', wait_id: 'w1', plan_revision: 1, resolutions: { 'missing:C': 'exclude_selected_missing' } })
  expect(body).not.toHaveProperty('selection')
})

test('blocks approval for a hard issue while allowing a full selection revision', async () => {
  const blocked = { ...reviewFixture, check: { ...reviewFixture.check, issues: [{ ...reviewFixture.check.issues[0], id: 'type:C', code: 'numeric_type', severity: 'blocking', allowed_resolutions: [] }] } }
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => url.endsWith('/analysis-plan/decisions') ? Response.json(reviewFixture.task) : Response.json(blocked))
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<AnalysisPlanReview projectId="p1" taskId="t1" />)
  const approve = await screen.findByRole('button', { name: '确认并发布分析计划' }) as HTMLButtonElement
  expect(approve.disabled).toBe(true)
  await user.click(screen.getByRole('button', { name: '修改字段重审' }))
  await user.clear(screen.getByLabelText('数值列'))
  await user.type(screen.getByLabelText('数值列'), 'D')
  await user.click(screen.getByRole('button', { name: '修改字段并重新检查' }))
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/analysis-plan/decisions'))).toBe(true))
  const body = JSON.parse(fetch.mock.calls.find(([url]) => url.endsWith('/analysis-plan/decisions'))![1]?.body as string)
  expect(body).toMatchObject({ operation: 'revise', resolutions: {}, selection: { ...reviewFixture.selection, numeric_column: 'D' } })
})

test('explains a publish failure and does not offer approval of the stale plan', async () => {
  const failed = { ...reviewFixture, task: { ...reviewFixture.task, status: 'failed', display_status: 'failed', error_code: 'setup_conflict' }, wait_id: null }
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(failed)))
  render(<AnalysisPlanReview projectId="p1" taskId="t1" />)
  expect(await screen.findByText('分析配置已变化，请读取当前配置并重新执行统计。')).toBeTruthy()
  expect(screen.getByText('请重新读取配置，核对来源后重新生成分析计划。')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '确认并发布分析计划' })).toBeNull()
})

test('shows unavailable valid counts when the numeric check could not finish', async () => {
  const invalid = { ...reviewFixture, check: { ...reviewFixture.check, selection_check: null, issues: [{ ...reviewFixture.check.issues[0], code: 'numeric_precision', severity: 'blocking', allowed_resolutions: [] }] } }
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(invalid)))
  render(<AnalysisPlanReview projectId="p1" taskId="t1" />)
  expect(await screen.findByText('数据范围 C5:D10；完整 6 行；有效 — 行；排除 — 行。')).toBeTruthy()
  expect((screen.getByRole('button', { name: '确认并发布分析计划' }) as HTMLButtonElement).disabled).toBe(true)
})
