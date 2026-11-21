// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import AnalystProgress from './AnalystProgress'
import useAnalystWorkspace from './useAnalystWorkspace'

const url = '/api/v1/projects/p1/analyst-workspace'
const submittedAt = '2026-11-18T07:02:00Z'
const submission = {
  id: 's1', requirement_version: 2, file_ids: ['f1', 'f2'], note: '第 4 例样本编号已更正。', created_at: submittedAt,
  files: [{ id: 'f1', name: '对照组分组表.xlsx' }, { id: 'f2', name: '补充说明.docx' }],
}
let state: { status: string; note: string | null }
let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  state = { status: 'materials_submitted', note: '请补充 6 例对照组的分组表。' }
  setApiSession('csrf', 'analyst')
  fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === url) return Response.json({
      assignment_revision: 2, requirement: { id: 'r2', version: 2 }, status: state.status, note: state.note,
      feedback: [], publications: [], submissions: [submission],
    })
    if (input === url + '/progress' && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      state = { status: body.status, note: body.note }
      return Response.json({ status: body.status })
    }
    return Response.json({ detail: { code: 'invalid_request' } }, { status: 422 })
  })
  vi.stubGlobal('fetch', fetchMock)
  window.localStorage.clear()
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); clearApiSession() })

function Harness() {
  const workspace = useAnalystWorkspace('p1', 2)
  return <AnalystProgress projectId="p1" workspace={workspace}/>
}
const writes = () => fetchMock.mock.calls.filter(([input, init]) => input === url + '/progress' && init?.method === 'PATCH')
  .map(([, init]) => JSON.parse(String(init?.body)))

it('shows the customer resubmission with notes and download links', async () => {
  render(<Harness/>)
  const card = within(await screen.findByRole('region', { name: '处理进度' }))
  expect(await card.findByText('已补交，等待核对')).toBeTruthy()
  const summary = card.getByText(/^客户已补交 2 个文件 · /)
  expect(summary.textContent).toBe(`客户已补交 2 个文件 · ${new Date(submittedAt).toLocaleString('zh-CN')}`)
  expect(card.getByText('客户说明：第 4 例样本编号已更正。')).toBeTruthy()
  expect(card.getByRole('link', { name: '下载 对照组分组表.xlsx' }).getAttribute('href')).toBe('/api/v1/projects/p1/files/f1/download')
  expect(card.getByRole('link', { name: '下载 补充说明.docx' }).getAttribute('href')).toBe('/api/v1/projects/p1/files/f2/download')
  expect(card.queryByLabelText('更新进度')).toBeNull()
  expect(card.getByRole('button', { name: '继续分析' }).className).toContain('button-primary')
})

it('continues the analysis from a resubmission', async () => {
  render(<Harness/>)
  fireEvent.click(await screen.findByRole('button', { name: '继续分析' }))
  await waitFor(() => expect(writes()).toEqual([{ assignment_revision: 2, requirement_version_id: 'r2', status: 'analyzing', note: null }]))
  expect(await screen.findByText('分析中', { selector: 'strong' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '继续分析' })).toBeNull()
})

it('requests more materials again with a note', async () => {
  render(<Harness/>)
  const again = await screen.findByRole('button', { name: '再次请求补充资料' })
  expect(again.hasAttribute('disabled')).toBe(true)
  fireEvent.change(screen.getByLabelText('给客户的说明'), { target: { value: '请补充第 5 例样本。' } })
  fireEvent.click(again)
  await waitFor(() => expect(writes()).toEqual([{ assignment_revision: 2, requirement_version_id: 'r2', status: 'needs_materials', note: '请补充第 5 例样本。' }]))
})
