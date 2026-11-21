import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { exportFixture, manuscriptFixture } from '../manuscripts/manuscriptFixtures'
import { taskFixture, workspaceFixture } from '../tasks/taskFixtures'
import { setLocale } from '../../shared/i18n'
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
  setLocale('zh-CN')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', window.location.pathname)
})

it('names the parsed Word and PDF source option in the customer review form in both languages', async () => {
  mockReview('sci')
  window.history.replaceState(null, '', address + 'reviews&view=create&reviewManuscript=m1&reviewRevision=1')
  render(<CustomerWorkspace />)
  const method = await screen.findByLabelText('来源方式')
  expect.soft(within(method).getAllByRole('option').map(option => option.textContent)).toContain('已解析的 Word 或 PDF')
  act(() => setLocale('en'))
  expect(within(method).getAllByRole('option').map(option => option.textContent)).toContain('Parsed Word or PDF')
  fireEvent.change(method, { target: { value: 'document' } })
  expect(method).toHaveProperty('value', 'document')
})

it.each([
  ['sci', ['编辑', '审稿人'], 'editor'],
  ['thesis', ['导师', '评阅人', '答辩委员会'], 'defense'],
] as const)('starts a %s review round with an explicitly selected historical Word version', async (projectType, roles, role) => {
  const fetch = mockReview(projectType)
  window.history.replaceState(null, '', address + 'word&view=exports&manuscript=m1&revision=1')
  render(<CustomerWorkspace />)
  expect((await screen.findByRole('link', { name: '下载这份 Word' })).getAttribute('href')).toBe(oldVersion.exports[0].download_url)
  fireEvent.click(screen.getByRole('button', { name: '以此版本处理意见' }))
  await screen.findByRole('heading', { name: '意见与返修', level: 1 })
  // Customer version options use the shared version label (B04 task 13).
  await screen.findByRole('option', { name: '固定旧稿 · 第 1 版' })
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

it('labels a single saved review comment in English', async () => {
  setLocale('en')
  mockReview('sci')
  window.history.replaceState(null, '', address + 'reviews&view=create')
  render(<CustomerWorkspace />)
  fireEvent.change(await screen.findByRole('textbox', { name: 'Source identity' }), { target: { value: 'Reviewer 1' } })
  fireEvent.change(screen.getByRole('textbox', { name: 'Original comments' }), { target: { value: item.original_text } })
  fireEvent.click(screen.getByRole('button', { name: 'Preview and segment' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Save source' }))
  const source = screen.getByRole('button', { name: 'Remove source' }).closest('article')
  expect(source?.querySelector('span')?.textContent?.trim()).toBe('· 1 comment')
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
  fireEvent.click(screen.getByRole('button', { name: '查看本轮任务' }))
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
  fireEvent.click(within(work).getByRole('button', { name: '补充资料后继续' }))
  expect(within(work).getByLabelText('批量选择 Word 文件')).toBeTruthy()
  expect(work.querySelector('details, button[aria-expanded]')).toBeNull()
})

it('keeps the customer supplement view on published material and avoids project computation endpoints', async () => {
  const fetch = mockReview('thesis')
  window.history.replaceState(null, '', address + 'reviews&view=science&round=round1')
  render(<CustomerWorkspace />)
  await screen.findByRole('button', { name: '返回我的项目' })
  await screen.findByRole('heading', { name: '分析材料补充' })
  // B05 task 5: the old button back to the project list is gone; opinions carry their own way to analysis results.
  expect(screen.queryByRole('button', { name: '前往已发布分析交付' })).toBeNull()
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

const token = 'return=' + encodeURIComponent('customer-project=' + projectId + '&step=manuscripts&view=body&manuscript=m1&revision=1') +
  '&returnLabel=paragraph&returnSection=' + encodeURIComponent('讨论') + '&returnParagraph=2'

it('keeps the return token when a review view rebuilds its address', async () => {
  mockReview('sci')
  window.history.replaceState(null, '', address + 'reviews&view=items&round=round1&' + token)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: /意见来源.*意见 1/ }))
  expect(window.location.hash).toBe(address + 'reviews&view=plan&round=round1&item=' + encodeURIComponent(item.id) + '&' + token)
})

it.each(['sci', 'thesis'] as const)('opens the previous round from the returned Word page inside the customer address (%s)', async projectType => {
  const inner = mockReview(projectType, url => url.endsWith('/continuation-context') ? {
    previous_round_id: 'round2', manuscript_id: 'm1', expected_current_revision: 2,
    eligible_inputs: [{ id: 'm1', revision: 2, version_id: 'v2', title: '固定新稿', exports: [] }],
    successful_revisions: [], returns: [],
  } : undefined)
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === reviews + '/rounds/round2') {
      const round = await (await inner(reviews + '/rounds/round1')).json() as Record<string, unknown>
      return Response.json({
        ...round, id: 'round2', round_number: 2, manuscript: { id: 'm1', revision: 2, version_id: 'v2', title: '固定新稿' },
        continuation: { previous_round_id: 'round1', user_return_id: null, input_manuscript: { id: 'm1', revision: 2, version_id: 'v2' } },
        task: { ...task, input_version: { ...task.input_version, round_id: 'round2', base_version_id: 'v2' } },
      })
    }
    return inner(url, init)
  }))
  window.history.replaceState(null, '', address + 'reviews&view=continuation&round=round2&' + token)
  render(<CustomerWorkspace />)
  const panel = await screen.findByRole('region', { name: projectType === 'thesis' ? '导师返回的 Word' : '返回的 Word' })
  expect(panel.querySelector('a[href^="#"]')).toBeNull()
  fireEvent.click(await within(panel).findByRole('button', { name: '查看上一轮' }))
  await waitFor(() => expect(window.location.hash).toBe(address + 'reviews&view=items&round=round1&' + token))
})

it('keeps the return token when starting a review from a fixed version', async () => {
  mockReview('sci')
  window.history.replaceState(null, '', address + 'word&view=exports&manuscript=m1&revision=1&' + token)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '以此版本处理意见' }))
  await screen.findByRole('heading', { name: '意见与返修', level: 1 })
  expect(window.location.hash).toContain('reviewManuscript=m1&reviewRevision=1&' + token)
})

it('drops the return token when the customer chooses a step', async () => {
  mockReview('sci')
  window.history.replaceState(null, '', address + 'reviews&view=items&round=round1&' + token)
  render(<CustomerWorkspace />)
  await screen.findByRole('button', { name: /意见来源.*意见 1/ })
  fireEvent.click(screen.getByRole('button', { name: '项目资料' }))
  await screen.findByRole('heading', { name: '项目资料', level: 1 })
  expect(window.location.hash).toBe(address + 'details')
})

// B05 task 7: the manuscript opened from a review keeps a return token to the round or the opinion.
const continuationContext = {
  previous_round_id: 'round1', manuscript_id: 'm1', expected_current_revision: 2,
  eligible_inputs: [{ id: 'm1', revision: 1, version_id: 'v1', title: '固定旧稿', exports: [] }],
  successful_revisions: [], returns: [] as unknown[],
}
const registeredReturn = {
  id: 'return1', previous_round_id: 'round1', revision_id: null, synthetic: false, manuscript_id: 'm1', base_version_id: 'v1', base_revision: 1,
  source: { file_id: 'fdoc', document_version_id: 'parse1' }, original_download_url: base + '/files/fdoc/download',
  input_sections: [{ id: 'input1', title: '方法', paragraphs: ['合成改文'], candidate_chapter_ids: ['methods'], match_method: 'title', suggested_chapter_id: 'methods' }],
  target_chapters: [{ id: 'methods', title: '方法' }], mappings: [{ input_section_id: 'input1', chapter_id: 'methods' }],
  differences: [], issues: [], can_adopt: true, preview_sha256: 'c'.repeat(64), output: null, created_at: task.created_at,
}
const manuscriptTrip = (origin: string, extra: Record<string, string>) => address + 'manuscripts&' + new URLSearchParams({
  manuscript: 'm1', revision: '1', view: 'body', return: `customer-project=${projectId}&step=reviews&${origin}`, ...extra,
}).toString()

it.each(['sci', 'thesis'] as const)('opens the submitted manuscript from the returned Word page and comes back to the round (%s)', async projectType => {
  mockReview(projectType, url => url.endsWith('/continuation-context') ? { ...continuationContext, returns: [registeredReturn] }
    : url.endsWith('/returns/return1') ? registeredReturn : url.endsWith('/thesis-requirements') ? { keywords: [] } : undefined)
  window.history.replaceState(null, '', address + 'reviews&view=continuation&round=round1')
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '查看送审稿' }))
  await waitFor(() => expect(window.location.hash).toBe(manuscriptTrip('view=continuation&round=round1',
    { returnLabel: 'review-round', returnRound: '1' })))
  expect(await screen.findByText('正在查看“第 1 轮”所用的稿件')).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: '返回 第 1 轮' }))
  await waitFor(() => expect(window.location.hash).toBe(address + 'reviews&view=continuation&round=round1'))
  const restored = await screen.findByRole('heading', { name: projectType === 'sci' ? '返回的 Word' : '导师返回的 Word' })
  await waitFor(() => expect(document.activeElement).toBe(restored))
})

it('opens the original manuscript of a selected opinion with a token to the opinion', async () => {
  mockReview('sci')
  const itemAddress = 'view=plan&round=round1&item=' + encodeURIComponent(item.id)
  window.history.replaceState(null, '', address + 'reviews&' + itemAddress)
  render(<CustomerWorkspace />)
  await screen.findByRole('textbox', { name: '修改计划' })
  const open = screen.getByRole('button', { name: '查看原稿' })
  expect(document.querySelector('.review-round-heading a')).toBeNull()
  fireEvent.click(open)
  await waitFor(() => expect(window.location.hash).toBe(manuscriptTrip(itemAddress,
    { returnLabel: 'review-item', returnRound: '1', returnItem: '1' })))
  fireEvent.click(await screen.findByRole('link', { name: '返回 第 1 轮 · 意见 1' }))
  await waitFor(() => expect(window.location.hash).toBe(address + 'reviews&' + itemAddress))
  await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('当前处理意见')))
})

it('restores the returned Word section of the selected opinion only after a manuscript trip', async () => {
  mockReview('sci', url => url.endsWith('/continuation-context') ? continuationContext : undefined)
  const origin = address + 'reviews&view=continuation&round=round1&item=' + encodeURIComponent(item.id)
  window.history.replaceState(null, '', origin)
  render(<CustomerWorkspace />)
  await screen.findByRole('heading', { name: '返回的 Word' })
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: '意见与返修', level: 1 }))
  fireEvent.click(screen.getByRole('button', { name: '查看原稿' }))
  fireEvent.click(await screen.findByRole('link', { name: '返回 第 1 轮 · 意见 1' }))
  const section = await screen.findByRole('heading', { name: '返回的 Word' })
  await waitFor(() => expect(document.activeElement).toBe(section))
  expect(window.location.hash).toBe(origin)
  const refresh = screen.getByRole('button', { name: '刷新意见记录' })
  refresh.focus()
  fireEvent.click(refresh)
  await act(async () => {})
  expect(document.activeElement).toBe(refresh)
})

it('leaves keyboard focus where the customer put it while the returned opinion is loading', async () => {
  const original = mockReview('sci', url => url.endsWith('/continuation-context') ? continuationContext : undefined)
  let delay = false, release: (() => void) | undefined
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    if (delay && url === reviews + '/rounds/round1') {
      return new Promise<Response>(resolve => { release = () => { void original(url, init).then(resolve) } })
    }
    return original(url, init)
  })
  window.history.replaceState(null, '', address + 'reviews&view=continuation&round=round1&item=' + encodeURIComponent(item.id))
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '查看原稿' }))
  const back = await screen.findByRole('link', { name: '返回 第 1 轮 · 意见 1' })
  delay = true
  fireEvent.click(back)
  await waitFor(() => expect(release).toBeDefined())
  const refresh = screen.getByRole('button', { name: '刷新意见记录' })
  refresh.focus()
  await act(async () => { release!() })
  await screen.findByRole('heading', { name: '返回的 Word' })
  expect(document.activeElement).toBe(refresh)
})

it('still asks before leaving an unsaved plan for the original manuscript', async () => {
  mockReview('sci')
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  const itemAddress = address + 'reviews&view=plan&round=round1&item=' + encodeURIComponent(item.id)
  window.history.replaceState(null, '', itemAddress)
  render(<CustomerWorkspace />)
  fireEvent.change(await screen.findByRole('textbox', { name: '修改计划' }), { target: { value: '未保存' } })
  fireEvent.click(screen.getByRole('button', { name: '查看原稿' }))
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(window.location.hash).toBe(itemAddress)
})

it.each([
  ['sci', 'zh-CN', ['修改稿', '修改对照', '逐条回复', '修改后的 Word', '返回的 Word', '分析材料补充', '补充资料后继续']],
  ['thesis', 'zh-CN', ['修改稿', '修改对照', '修改后的 Word', '导师返回的 Word', '分析材料补充', '补充资料后继续']],
  ['sci', 'en', ['Revised manuscript', 'Revised Word file', 'Returned Word file', 'Continue after adding materials']],
] as const)('names the customer review views in customer words (%s, %s)', async (projectType, locale, names) => {
  const { setLocale } = await import('../../shared/i18n')
  setLocale(locale)
  mockReview(projectType)
  window.history.replaceState(null, '', address + 'reviews&view=items&round=round1')
  render(<CustomerWorkspace />)
  const tabs = await screen.findByRole('navigation', { name: locale === 'en' ? 'Review workspace views' : '评审工作视图' })
  const labels = within(tabs).getAllByRole('button').map(button => button.textContent)
  for (const name of names) expect(labels).toContain(name)
  expect(labels.join('|')).not.toMatch(/回传续轮|固定文档|补料继续|有依据改文/)
  setLocale('zh-CN')
})
