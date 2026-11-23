// The research and thesis legacy task pages use the customer view, with one heading and a way
// back, and keep the task actions the server allows.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setLocale } from '../../shared/i18n'
import { taskFixture, workspaceFixture } from '../tasks/taskFixtures'
import CustomerWorkspace from './CustomerWorkspace'

const taskId = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'

function serve(projectType: 'research' | 'sci' | 'thesis', allowed: string[] = ['retry'], taskWorkspace?: unknown) {
  const projectId = 'legacy-' + projectType
  const base = '/api/v1/projects/' + projectId
  const task = { ...taskFixture, id: taskId, project_id: projectId, task_type: 'extract_dataset', phase: 'parse', status: 'failed',
    display_status: 'failed', reason_code: null, error_code: null,
    input_version: { kind: 'excel_structure', structure_id: 's1', source_sha256: 'a'.repeat(64), parser_version: 'openpyxl-3.1.5-structure-v1' } }
  const workspace = { ...workspaceFixture, task, source: { ...workspaceFixture.source, analysis_run_id: null }, wait: null,
    allowed_actions: allowed,
    verification_failure: { schema_version: 1, status: 'mismatched', recorded_at: '2026-10-14T00:00:00Z',
      differences: [{ path: '$.statistics.coefficient', expected: 0.8, actual: 0.7, reason: 'numeric mismatch' }], manifest: {}, provenance: {} },
    artifacts: { figure: null, explanation: null, report: null, dataset: { filename: 'structure.json', download_url: base + '/datasets/s1/download' } } }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === base) return Response.json({ id: projectId, name: '旧任务项目', project_type: projectType, research_topic: '课题',
      file_count: 0, created_at: task.created_at, updated_at: task.updated_at, default_output_language: 'zh-CN' })
    if (url === `/api/v1/tasks/${taskId}/workspace`) return Response.json(taskWorkspace ?? workspace)
    if (url.includes('/events')) return Response.json({ task_id: taskId, items: [], next_cursor: 0 })
    if (url.startsWith(base + '/files?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url === base + '/sci-current-draft') return Response.json({ draft: null })
    if (url === base + '/sci-settings') return Response.json({ settings: null })
    // A complete requirements record: "返回项目资料" renders the thesis details page, which needs the language.
    if (url === base + '/thesis-requirements') return Response.json({ revision: 1, education_level: '硕士', language: 'zh-CN',
      school: '示例大学', title: '旧任务论文', keywords: [], sections: [], template: null })
    return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
  }))
  return `#customer-project=${projectId}&step=tasks&task=${taskId}`
}

afterEach(() => {
  cleanup()
  setLocale('zh-CN')
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

describe.each([['research', 'upload'], ['thesis', 'materials']] as const)('old task page (%s)', (projectType, filesStep) => {
  it('shows the customer view with one focused heading, the allowed actions and ways out', async () => {
    const address = serve(projectType)
    window.history.replaceState(null, '', address)
    render(<CustomerWorkspace />)
    await screen.findByText('Excel 结构提取', undefined, { timeout: 4000 })
    const headings = screen.getAllByRole('heading', { name: '任务详情' })
    expect(headings).toHaveLength(1)
    expect(headings[0].tagName).toBe('H1')
    await waitFor(() => expect(document.activeElement).toBe(headings[0]))
    expect(screen.queryByRole('link', { name: '下载完整 JSON' })).toBeNull()
    expect(screen.queryByRole('table', { name: '图表数值核对差异' })).toBeNull()
    expect(document.body.textContent).not.toContain('$.statistics')
    fireEvent.click(screen.getByRole('button', { name: '待处理' }))
    expect(await screen.findByRole('button', { name: '重试原任务' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '概况' }))
    fireEvent.click(screen.getByRole('button', { name: '查看项目文件' }))
    await waitFor(() => expect(window.location.hash).toBe(`#customer-project=legacy-${projectType}&step=${filesStep}`))
  })

  it('goes back to the project details, or follows a return token', async () => {
    const address = serve(projectType)
    window.history.replaceState(null, '', address)
    const first = render(<CustomerWorkspace />)
    fireEvent.click(await screen.findByRole('button', { name: '返回项目资料' }))
    await waitFor(() => expect(window.location.hash).toBe(`#customer-project=legacy-${projectType}&step=details`))
    first.unmount()
    const token = new URLSearchParams({ return: `customer-project=legacy-${projectType}&step=progress`, returnLabel: 'progress' }).toString()
    window.history.replaceState(null, '', address + '&' + token)
    render(<CustomerWorkspace />)
    fireEvent.click(await screen.findByRole('link', { name: '返回 任务进度' }))
    await waitFor(() => expect(window.location.hash).toBe(`#customer-project=legacy-${projectType}&step=progress`))
  })
})

it('opens the current SCI draft from an old task link without requesting the legacy task', async () => {
  window.history.replaceState(null, '', serve('sci'))
  render(<CustomerWorkspace />)
  await screen.findByRole('button', { name: '补充 SCI 建项资料' })
  expect(screen.getByRole('heading', { name: '文献与初稿', level: 1 })).toBeTruthy()
  expect(screen.queryByRole('heading', { name: '任务详情' })).toBeNull()
  const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url))
  expect(urls).toContain('/api/v1/projects/legacy-sci/sci-current-draft')
  expect(urls.some(url => url.startsWith('/api/v1/tasks/'))).toBe(false)
})

it('keeps only the actions the server allows', async () => {
  window.history.replaceState(null, '', serve('research', ['retry']))
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '待处理' }))
  expect(await screen.findByRole('button', { name: '重试原任务' }, { timeout: 4000 })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '取消任务' })).toBeNull()
  expect(screen.queryByRole('button', { name: '继续原任务' })).toBeNull()
})

it('has English for the way back', async () => {
  setLocale('en')
  window.history.replaceState(null, '', serve('thesis'))
  render(<CustomerWorkspace />)
  expect(await screen.findByRole('button', { name: 'Back to project details' })).toBeTruthy()
})

const wordTasks = {
  manuscript_docx: { kind: 'manuscript', manuscript_version_id: 'v3', output_language: 'en', workflow_version: 'manuscript_fact_draft_v1' },
  layout_docx: { kind: 'layout_docx', export_id: 'layout1', source_kind: 'report', source_id: 'report1', source_sha256: 'a'.repeat(64), workflow_version: 'layout_docx_v1' },
  review_document_export: { kind: 'review_document_export', document_id: 'd1', revision_id: 'rev1', round_id: 'r1', export_id: 'e1', document_sha256: 'a'.repeat(64), workflow_version: 'review_document_export_v1' },
}

it.each([
  ['manuscript_docx', '稿件 Word 导出', 'Manuscript Word export'],
  ['layout_docx', '导出排版后的 Word', 'Formatted Word export'],
  ['review_document_export', '意见成果 Word 导出', 'Review document Word export'],
] as const)('uses a bilingual customer Word title for the %s task', async (kind, chinese, english) => {
  const projectId = 'legacy-thesis'
  const task = { ...taskFixture, id: taskId, project_id: projectId, task_type: kind, phase: 'export', status: 'failed',
    display_status: 'failed', reason_code: null, error_code: 'insufficient_disk_space', input_version: wordTasks[kind] }
  const workspace = { ...workspaceFixture, task, wait: null, allowed_actions: [], source: { file_id: null, filename: '稿件.docx', analysis_run_id: null, is_current: true },
    artifacts: { figure: null, explanation: null, report: null, manuscript: kind === 'manuscript_docx' ? { id: 'm1', revision: 3, version_id: 'v3', download_url: null } : null } }
  window.history.replaceState(null, '', serve('thesis', [], workspace))
  const page = render(<CustomerWorkspace />)
  const heading = await screen.findByRole('heading', { level: 3 })
  expect.soft(heading.textContent).toBe(chinese)
  if (kind === 'manuscript_docx') {
    const link = await screen.findByRole('link', { name: '查看此版本的 Word' })
    expect.soft(link.getAttribute('href')).toBe('#customer-project=legacy-thesis&step=word&manuscript=m1&revision=3&view=exports')
  }
  page.unmount()
  setLocale('en')
  render(<CustomerWorkspace />)
  expect((await screen.findByRole('heading', { level: 3 })).textContent).toBe(english)
})
