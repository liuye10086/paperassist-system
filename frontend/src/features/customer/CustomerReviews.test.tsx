import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
    if (url === base + '/sci-current-draft') return Response.json({ draft: null })
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

it('opens the SCI draft from a historical reply bookmark without fetching the old round or reply', async () => {
  const fetch = mockReview('sci')
  window.history.replaceState(null, '', '#project=' + projectId + '&section=reviews&view=response&round=round1&reviewRun=run1&reviewDocument=reply1')
  render(<CustomerWorkspace />)
  await screen.findByRole('button', { name: '补充 SCI 建项资料' })
  expect(screen.getByRole('heading', { name: '文献与初稿', level: 1 })).toBeTruthy()
  expect(screen.queryByRole('navigation', { name: '评审工作视图' })).toBeNull()
  expect(fetch.mock.calls.some(([url]) => url.startsWith(reviews))).toBe(false)
})

it.each([
  address + 'reviews&view=plan&round=round1',
  '#project=' + projectId + '&section=reviews&view=plan&round=round1',
])('shows the original supervisor feedback as read-only from %s', async hash => {
  const fetch = mockReview('thesis')
  window.history.replaceState(null, '', hash + '&item=' + encodeURIComponent(item.id))
  render(<CustomerWorkspace/>)
  expect(await screen.findByText(item.original_text)).toBeTruthy()
  expect(screen.queryByRole('textbox', {name:'修改计划'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'查看这版正文'}))
  const params = new URLSearchParams(location.hash.slice(1))
  expect([params.get('step'), params.get('manuscript'), params.get('revision')]).toEqual(['manuscripts','m1','1'])
  expect(fetch.mock.calls.every(([,init]) => !init?.method || init.method === 'GET')).toBe(true)
})
