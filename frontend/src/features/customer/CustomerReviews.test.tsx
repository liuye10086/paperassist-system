import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { exportFixture, manuscriptFixture } from '../manuscripts/manuscriptFixtures'
import { taskFixture, workspaceFixture } from '../tasks/taskFixtures'
import CustomerWorkspace from './CustomerWorkspace'

const projectId = 'paper-review'
const base = '/api/v1/projects/' + projectId
const reviews = base + '/reviews'
const address = '#customer-project=' + projectId + '&step='
const oldVersion = {
  ...manuscriptFixture.versions[0],
  snapshot: { ...manuscriptFixture.versions[0].snapshot, project_id: projectId },
  exports: [{ ...exportFixture, download_url: base + '/manuscripts/m1/exports/export1/download' }],
}
const latestVersion = { ...oldVersion, id: 'v2', revision: 2, parent_version_id: 'v1', exports: [] }
const manuscript = { ...manuscriptFixture, project_id: projectId, current_revision: 2, versions: [latestVersion, oldVersion] }
const task = {
  ...taskFixture, id: 'review-task', project_id: projectId, task_type: 'review_round_plan',
  phase: 'verify', status: 'succeeded', display_status: 'succeeded', error_code: null, reason_code: null,
  input_version: {
    kind: 'review_round_plan', round_id: 'round1', base_version_id: 'v1', workflow_version: 'review_round_plan_v1',
  },
}
const sourceId = 'f2a6939b-b706-4037-b294-68b106ebd602'
const item = {
  id: sourceId + ':1', source_id: sourceId, number: 1, original_number: '1', original_text: '核对固定方法',
  source_location: null, revision: 1, status: 'pending', uncompleted_reason: '', decision: null,
  category: 'method', locations: [], translation: null, plan: '初始处理计划', evidence_ids: [], needs: [],
  flags: [], conflicting_item_ids: [], proposed_action: 'modify', not_adopt_reason: '',
}

function mockReview(project_type: 'sci' | 'thesis', extra?: (url: string) => unknown) {
  const round = {
    id: 'round1', project_id: projectId, title: '旧稿意见', project_type, round_number: 1, revision: 1,
    synthetic: false, manuscript: { id: 'm1', revision: 1, version_id: 'v1', title: '固定旧稿' },
    sources: [{
      id: sourceId, role: project_type === 'sci' ? 'editor' : 'advisor', label: '意见来源',
      format: 'text', original_text: item.original_text, segments: [], warnings: [],
    }],
    items: [item], materials: [], constraints: { school_confirmation_id: null, journal_target_id: null },
    versions: [], decisions: [], task, wait: null, created_at: task.created_at,
    real_model_calls: false, real_network_calls: false,
  }
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === base) return Response.json({
      id: projectId, name: '合成客户论文', project_type, research_topic: '定向验证', file_count: 0,
      created_at: task.created_at, updated_at: task.updated_at, default_output_language: 'zh-CN',
    })
    if (url === base + '/sci-settings') return Response.json({ settings: null })
    if (url === base + '/manuscripts') return Response.json({ items: [manuscript] })
    if (url === base + '/manuscripts/m1/versions/1/exports') return Response.json({ items: oldVersion.exports })
    if (url === reviews + '/inputs') return Response.json({
      project_type, manuscripts: [{
        id: 'm1', title: manuscript.title, current_revision: 2,
        versions: [
          { id: 'v2', revision: 2, status: 'published', title: '固定新稿' },
          { id: 'v1', revision: 1, status: 'published', title: '固定旧稿' },
        ],
      }], documents: [], journal_targets: [], school_confirmations: [],
    })
    if (url === reviews + '/rounds' && init?.method === 'POST') return Response.json(round, { status: 202 })
    if (url === reviews + '/rounds') return Response.json({ items: [round] })
    if (url === reviews + '/rounds/round1') return Response.json(round)
    if (url === reviews + '/sources/preview') return Response.json({
      original_text: item.original_text, segments: [{ start: 0, end: 6, original_number: '1' }],
      warnings: [], supported: true,
    })
    if (url.endsWith('/review-task/workspace')) return Response.json({
      ...workspaceFixture, task, wait: null, allowed_actions: [],
      source: { file_id: null, analysis_run_id: null, filename: '固定旧稿', is_current: true },
    })
    const fixture = extra?.(url)
    if (fixture !== undefined) return Response.json(fixture)
    if (url.startsWith('/api/v1/projects?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', window.location.pathname)
})

it.each([
  ['sci', ['编辑', '审稿人'], 'editor'],
  ['thesis', ['导师', '评阅人', '答辩委员会'], 'defense'],
] as const)('starts a %s review round with an explicitly selected historical Word version', async (projectType, roles, role) => {
  const fetch = mockReview(projectType)
  window.history.replaceState(null, '', address + 'word&view=exports&manuscript=m1&revision=1')
  render(<CustomerWorkspace />)
  expect((await screen.findByRole('link', { name: '下载 DOCX' })).getAttribute('href')).toBe(oldVersion.exports[0].download_url)
  fireEvent.click(screen.getByRole('button', { name: '以此版本处理意见' }))
  await screen.findByRole('heading', { name: '意见与返修', level: 1 })
  await screen.findByRole('option', { name: '固定旧稿 · 版本 1' })
  expect(window.location.hash).toContain('reviewManuscript=m1&reviewRevision=1')
  expect(screen.getByLabelText('固定稿件版本')).toHaveProperty('value', 'v1')
  const sourceRole = screen.getByLabelText('来源角色')
  expect(within(sourceRole).getAllByRole('option').map(option => option.textContent)).toEqual(roles)
  fireEvent.change(sourceRole, { target: { value: role } })
  fireEvent.change(screen.getByLabelText('轮次标题'), { target: { value: '合成意见' } })
  fireEvent.change(screen.getByLabelText('来源身份'), { target: { value: '固定来源' } })
  fireEvent.change(screen.getByLabelText('意见原文'), { target: { value: item.original_text } })
  fireEvent.click(screen.getByRole('button', { name: '预览并分条' }))
  fireEvent.click(await screen.findByRole('button', { name: '保存来源' }))
  fireEvent.click(screen.getByRole('button', { name: '创建本轮意见计划' }))
  await screen.findByRole('heading', { name: '第 1 轮 · 旧稿意见' })
  expect(window.location.hash).toBe(address + 'reviews&view=items&round=round1')
  const created = fetch.mock.calls.find(([url, init]) => url === reviews + '/rounds' && init?.method === 'POST')?.[1]
  expect(JSON.parse(String(created?.body))).toMatchObject({
    synthetic: false, project_type: projectType, manuscript: { id: 'm1', revision: 1, version_id: 'v1' },
    sources: [{ role, label: '固定来源', text: item.original_text }],
  })
  expect(!!screen.queryByRole('button', { name: '逐条回复' })).toBe(projectType === 'sci')
})

it('opens a server-issued opinion ID and keeps its unfinished plan across its task receipt and browser history', async () => {
  mockReview('sci')
  window.history.replaceState(null, '', address + 'reviews&view=items&round=round1')
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: /意见来源.*意见 1/ }))
  const itemAddress = address + 'reviews&view=plan&round=round1&item=' + encodeURIComponent(item.id)
  expect(window.location.hash).toBe(itemAddress)
  const plan = screen.getByRole('textbox', { name: '修改计划' })
  fireEvent.change(plan, { target: { value: '待核对的草稿' } })
  fireEvent.click(screen.getByRole('button', { name: '查看任务与继续本地计划' }))
  await screen.findByRole('button', { name: '返回返修' })
  expect(window.location.hash).toBe(itemAddress + '&reviewTask=review-task')
  const receipt = screen.getByRole('region', { name: '任务详情' })
  expect(await within(receipt).findByText('意见处理计划')).toBeTruthy()
  expect(receipt.querySelector('details, button[aria-expanded]')).toBeNull()
  expect(receipt.textContent).not.toMatch(/review-task|base_version_id|review_round_plan|SHA256/)
  expect(screen.queryByRole('textbox', { name: '修改计划' })).toBeNull()
  await act(async () => window.history.back())
  await waitFor(() => expect(screen.getByRole('textbox', { name: '修改计划' })).toHaveProperty('value', '待核对的草稿'))
  expect(window.location.hash).toBe(itemAddress)
})

it.each([
  address + 'reviews&view=plan&round=round1',
  '#project=' + projectId + '&section=reviews&view=plan&round=round1',
])('opens the exact opinion plan on a direct review link %s', async location => {
  mockReview('sci')
  window.history.replaceState(null, '', location + '&item=' + encodeURIComponent(item.id))
  render(<CustomerWorkspace />)
  expect(await screen.findByRole('textbox', { name: '修改计划' })).toHaveProperty('value', item.plan)
  expect(screen.getByLabelText('当前处理意见')).toHaveProperty('value', item.id)
})

it('shows customer source text and the Word upload directly in their views', async () => {
  mockReview('sci')
  window.history.replaceState(null, '', address + 'reviews&view=sources&round=round1')
  render(<CustomerWorkspace />)
  const work = await screen.findByRole('region', { name: '意见修改' })
  const sources = await within(work).findByRole('region', { name: '本轮来源原文' })
  expect(within(sources).getByText(item.original_text)).toBeTruthy()
  expect(work.querySelector('details, button[aria-expanded]')).toBeNull()
  fireEvent.click(within(work).getByRole('button', { name: '补料继续' }))
  expect(within(work).getByLabelText('批量选择 DOCX 文件')).toBeTruthy()
  expect(work.querySelector('details, button[aria-expanded]')).toBeNull()
})

it('keeps the customer supplement view on published material and avoids project computation endpoints', async () => {
  const fetch = mockReview('thesis')
  window.history.replaceState(null, '', address + 'reviews&view=science&round=round1')
  render(<CustomerWorkspace />)
  await screen.findByRole('button', { name: '返回我的项目' })
  await screen.findByRole('heading', { name: '分析材料补充' })
  expect(screen.getByRole('button', { name: '前往已发布分析交付' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '提交关联的本地统计任务' })).toBeNull()
  expect(fetch.mock.calls.every(([url]) => !/\/tasks\?|\/science$|\/analysis-/.test(url))).toBe(true)
})

it('restores a pinned historical reply document after a new selection and browser Back', async () => {
  const output = { manuscript_id: 'm1', version_id: 'v2', revision: 2, parent_version_id: 'v1', task_id: 'new-word-task' }
  const revision = {
    id: 'old-run', round_id: 'round1', output_status: 'published', input_snapshot: {}, validation: {}, created_at: task.created_at,
    task: { ...task, task_type: 'review_revision', input_version: {
      kind: 'review_revision', revision_id: 'old-run', round_id: 'round1', base_version_id: 'v1', workflow_version: 'review_revision_v1',
    } },
    result: { actual_changes: [], unexecuted: [], public_issues: [], items: [], public_check_version: 3, output, synthetic: false },
  }
  const reply = {
    id: 'old-reply', project_id: projectId, revision_id: 'old-run', round_id: 'round1', kind: 'reply',
    version: 1, language: 'en', confirmed_at: task.created_at, created_at: task.created_at, latest_version: 2,
    snapshot: {
      title: '固定旧回复', project_type: 'sci', synthetic: false, language: 'en', kind: 'reply',
      revision_id: 'old-run', result_sha256: 'a'.repeat(64), output, items: [], location_notice: 'Fixed locations',
    },
  }
  const laterReply = { ...reply, id: 'new-reply', version: 2, snapshot: { ...reply.snapshot, title: '更新回复' } }
  const artifact = {
    id: 'reply-export', project_id: projectId, document_id: reply.id, task_id: 'reply-export-task',
    status: 'succeeded', filename: 'reply.docx', sha256: 'b'.repeat(64), size_bytes: 100,
    download_url: reviews + '/document-exports/reply-export/download',
    task: { ...task, id: 'reply-export-task', task_type: 'review_document_export', phase: 'export',
      input_version: { kind: 'review_document_export', document_id: reply.id, revision_id: revision.id, round_id: 'round1',
        export_id: 'reply-export', document_sha256: reply.snapshot.result_sha256, workflow_version: 'review_document_export_v1' } },
  }
  const fetch = mockReview('sci', url => {
    if (url.endsWith('/revision-context')) return {
      round_id: 'round1', plan_revision: 1, manuscript: { id: 'm1', revision: 1, version_id: 'v1' },
      expected_current_revision: 2, project_type: 'sci', output_language: 'en',
      locations: [], citation_candidates: [], evidence: [], grounded_plans: [], constraints: {},
    }
    if (url.endsWith('/rounds/round1/revisions')) return { items: [revision] }
    if (url.endsWith('/revisions/old-run/documents')) return { items: [laterReply, reply] }
    if (url.endsWith('/documents/old-reply/exports')) return { items: [artifact] }
    if (url.endsWith('/exports')) return { items: [] }
  })
  const oldAddress = '#project=' + projectId + '&section=reviews&view=response&round=round1&reviewRun=old-run&reviewDocument=old-reply'
  window.history.replaceState(null, '', oldAddress)
  render(<CustomerWorkspace />)
  const replyView = await screen.findByRole('region', { name: '独立逐条回复' })
  await within(replyView).findByRole('heading', { name: '固定旧回复' })
  expect((await within(replyView).findByRole('link', { name: '下载 Word' })).getAttribute('href')).toBe(artifact.download_url)
  expect(within(replyView).getByRole('button', { name: '确认回复' })).toBeTruthy()
  expect(replyView.textContent).not.toMatch(/SHA256|版本|old-run/)
  expect(replyView.querySelector('details, button[aria-expanded]')).toBeNull()
  fireEvent.change(screen.getByLabelText('查看已保存文档'), { target: { value: laterReply.id } })
  await screen.findByRole('heading', { name: '更新回复' })
  expect(window.location.hash).toContain('reviewRun=old-run&reviewDocument=new-reply')
  await act(async () => window.history.back())
  await screen.findByRole('heading', { name: '固定旧回复' })
  expect(window.location.hash).toBe(oldAddress)
  expect(fetch.mock.calls.every(([url]) => !url.includes('/pdf-exports'))).toBe(true)
})
