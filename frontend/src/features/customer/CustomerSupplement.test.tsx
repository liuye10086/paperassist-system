import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import CustomerMaterials from './CustomerMaterials'
import { customerBase, type Progress } from './customerWorkspaceApi'

const projectId = 'customer-project-1'
const base = '/api/v1/projects/' + projectId
const customer = customerBase(projectId)
const time = '2026-11-18T06:20:00Z'
const file = (id: string, filename: string, uploaded_at = time) =>
  ({ id, filename, file_type: 'xlsx', parse_status: 'parsed', size_bytes: 10, uploaded_at, error: null })
const old = file('file-old', 'sample_data_v2.xlsx')
const added = file('file-new', '对照组分组表.xlsx', '2026-11-18T07:00:00Z')

type Reply = (init?: RequestInit) => Response
function serve({ submit, progressVersion = () => 2, status = 'needs_materials' }: {
  submit?: Reply; progressVersion?: () => number; status?: Progress['status']
} = {}) {
  let items = [old]
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === customer + '/progress') return Response.json({
      status, requirement_version: progressVersion(), submitted_at: time, updated_at: time,
      note: '请补充 6 例对照组的分组表。', feedback: [], submissions: [],
    })
    if (url === customer + '/material-submissions' && init?.method === 'POST') return submit?.(init) ?? Response.json({
      id: 'submission-1', requirement_version: 2, file_ids: ['file-new'], files: [{ id: 'file-new', name: added.filename }],
      note: null, created_at: time,
    }, { status: 201 })
    if (url.startsWith(base + '/files?')) return Response.json({ items, total: items.length, page: 1, page_size: 5 })
    return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
  })
  vi.stubGlobal('fetch', fetch)
  return { fetch, upload: () => { items = [added, old] } }
}

function show(extra: Partial<{ onSubmitted: () => void; onProgress: () => void; onReturn: (href: string) => void }> = {}, token = false) {
  const handlers = { onSubmitted: vi.fn(), onProgress: vi.fn(), onReturn: vi.fn(), ...extra }
  render(<CustomerMaterials projectId={projectId} onContinue={vi.fn()} onUnavailable={vi.fn()} registerLeaveGuard={() => () => {}}
    supplement={{ ...handlers, returnTarget: token ? { href: `#customer-project=${projectId}&step=progress`, label: '任务进度' } : null }} />)
  return handlers
}

async function uploadNewFile(server: ReturnType<typeof serve>) {
  await screen.findByText('sample_data_v2.xlsx')
  server.upload()
  fireEvent.click(screen.getByRole('button', { name: '刷新资料' }))
  return await screen.findByRole('checkbox', { name: added.filename }) as HTMLInputElement
}

beforeEach(() => { setApiSession('csrf', 'customer-test'); sessionStorage.clear() })
afterEach(() => {
  cleanup()
  setLocale('zh-CN')
  clearApiSession()
  vi.unstubAllGlobals()
})

it('quotes the analyst request and shows the return bar only with a token', async () => {
  serve()
  const { onReturn } = show({}, true)
  expect(await screen.findByRole('heading', { name: '补交资料', level: 1 })).toBeTruthy()
  expect(await screen.findByText('请补充 6 例对照组的分组表。')).toBeTruthy()
  expect(screen.getByText('分析员需要你补充：')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '下一步 选择需求' })).toBeNull()
  fireEvent.click(screen.getByRole('link', { name: '返回 任务进度' }))
  expect(onReturn).toHaveBeenCalledWith(`#customer-project=${projectId}&step=progress`)
  cleanup()
  serve()
  show()
  await screen.findByRole('heading', { name: '补交资料', level: 1 })
  expect(screen.queryByRole('link', { name: '返回 任务进度' })).toBeNull()
})

it('selects files uploaded on this page by default and keeps the button disabled without a selection', async () => {
  const server = serve()
  show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  const submit = screen.getByRole('button', { name: '提交补充资料' }) as HTMLButtonElement
  expect(submit.disabled).toBe(true)
  expect(screen.getByText('先选择要补交的文件')).toBeTruthy()
  const box = await uploadNewFile(server)
  expect(box.checked).toBe(true)
  expect(screen.queryByRole('checkbox', { name: old.filename })).toBeNull()
  expect(submit.disabled).toBe(false)
  fireEvent.click(box)
  expect(box.checked).toBe(false)
  expect(submit.disabled).toBe(true)
})

it('submits the selected files once and returns to progress', async () => {
  const server = serve()
  const { onSubmitted } = show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await uploadNewFile(server)
  fireEvent.change(screen.getByRole('textbox', { name: '给分析员的说明（选填）' }), { target: { value: '第 4 例样本编号已更正。' } })
  fireEvent.click(screen.getByRole('button', { name: '提交补充资料' }))
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledOnce())
  const [, init] = server.fetch.mock.calls.find(([url]) => url === customer + '/material-submissions')!
  expect(JSON.parse(String(init?.body))).toEqual({ requirement_version: 2, file_ids: ['file-new'], note: '第 4 例样本编号已更正。' })
  expect(new Headers(init?.headers).get('Idempotency-Key')).toBeTruthy()
})

const draftKey = (version: number) =>
  `paperassist.research-draft.v1:customer-test:${projectId}:customer-supplement-note:${projectId}:${version}`
const noteBox = () => screen.getByRole('textbox', { name: '给分析员的说明（选填）' }) as HTMLTextAreaElement

function expectClosedSubmission() {
  expect(screen.queryByRole('button', { name: /^(提交补充资料|Submit additional materials)$/ })).toBeNull()
  expect(screen.queryByText(/^(先选择要补交的文件|Select the files to submit first)$/)).toBeNull()
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect(screen.queryByLabelText(/批量选择 Excel|Select Excel .*batch upload/)).toBeNull()
  expect(screen.getByRole('link', { name: /sample_data_v2\.xlsx/ })).toBeTruthy()
}

it('keeps the note as a draft across remounts', async () => {
  serve()
  show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await waitFor(() => expect(noteBox().disabled).toBe(false))
  fireEvent.change(noteBox(), { target: { value: '第 4 例样本编号已更正。' } })
  expect(JSON.parse(sessionStorage.getItem(draftKey(2))!)).toBe('第 4 例样本编号已更正。')
  cleanup()
  serve()
  show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await waitFor(() => expect(noteBox().value).toBe('第 4 例样本编号已更正。'))
})

it('clears the note draft after a successful submission', async () => {
  const server = serve()
  const { onSubmitted } = show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await uploadNewFile(server)
  fireEvent.change(noteBox(), { target: { value: '第 4 例样本编号已更正。' } })
  expect(JSON.parse(sessionStorage.getItem(draftKey(2))!)).toBe('第 4 例样本编号已更正。')
  fireEvent.click(screen.getByRole('button', { name: '提交补充资料' }))
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledOnce())
  expect(JSON.parse(sessionStorage.getItem(draftKey(2)) ?? '""')).toBe('')
  cleanup()
  serve()
  show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await waitFor(() => expect(noteBox().disabled).toBe(false))
  expect(noteBox().value).toBe('')
})

it('does not carry a note into a newer requirement version', async () => {
  sessionStorage.setItem(draftKey(2), JSON.stringify('第 2 版的说明'))
  serve({ progressVersion: () => 3 })
  show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await waitFor(() => expect(noteBox().disabled).toBe(false))
  expect(noteBox().value).toBe('')
  fireEvent.change(noteBox(), { target: { value: '第 3 版的说明' } })
  expect(JSON.parse(sessionStorage.getItem(draftKey(3))!)).toBe('第 3 版的说明')
  expect(JSON.parse(sessionStorage.getItem(draftKey(2))!)).toBe('第 2 版的说明')
})

it('explains an updated requirement in place and offers progress', async () => {
  let version = 2
  const server = serve({
    progressVersion: () => version,
    submit: () => { version = 3; return Response.json({ detail: { code: 'research_revision_conflict' } }, { status: 409 }) },
  })
  const { onProgress, onSubmitted } = show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await uploadNewFile(server)
  fireEvent.click(screen.getByRole('button', { name: '提交补充资料' }))
  const alert = await screen.findByText('需求已更新为第 3 版，这次补交请求已失效，已上传的文件仍保留在项目中。')
  expect(alert.closest('[role="alert"]')).toBeTruthy()
  expectClosedSubmission()
  expect(onSubmitted).not.toHaveBeenCalled()
  fireEvent.click(within(alert.closest('.customer-supplement-error') as HTMLElement).getByRole('button', { name: '查看任务进度' }))
  expect(onProgress).toHaveBeenCalledOnce()
})

it('explains that the analyst no longer waits for materials', async () => {
  const server = serve({ submit: () => Response.json({ detail: { code: 'materials_not_requested' } }, { status: 409 }) })
  show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await uploadNewFile(server)
  fireEvent.click(screen.getByRole('button', { name: '提交补充资料' }))
  expect(await screen.findByText('分析员已不再等待补充资料，无需再提交。')).toBeTruthy()
  expect(screen.getByRole('button', { name: '查看任务进度' })).toBeTruthy()
  expectClosedSubmission()
  expect(screen.queryByText(/materials_not_requested/)).toBeNull()
})

it('only offers progress for a reopened supplement request that is no longer active', async () => {
  setLocale('en')
  const server = serve({ status: 'materials_submitted' })
  const { onProgress } = show()
  await screen.findByText('The analyst is not currently requesting additional materials.')
  expectClosedSubmission()
  fireEvent.click(screen.getByRole('button', { name: 'View project progress' }))
  expect(onProgress).toHaveBeenCalledOnce()
  expect(server.fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  cleanup()
  render(<CustomerMaterials projectId={projectId} onContinue={vi.fn()} onUnavailable={vi.fn()} registerLeaveGuard={() => () => {}} />)
  const ordinaryUpload = await screen.findByLabelText('Select Excel / Word / PDF / image files for batch upload')
  fireEvent.change(ordinaryUpload, { target: { files: [new File(['sample'], 'normal-upload.xlsx')] } })
  expect(await screen.findByText(/normal-upload\.xlsx/)).toBeTruthy()
})

it('translates an invalid file selection', async () => {
  const server = serve({ submit: () => Response.json({ detail: { code: 'material_file_invalid' } }, { status: 422 }) })
  show()
  await screen.findByText('请补充 6 例对照组的分组表。')
  await uploadNewFile(server)
  fireEvent.click(screen.getByRole('button', { name: '提交补充资料' }))
  expect(await screen.findByText('请选择本项目已上传完成的资料文件。')).toBeTruthy()
})

it('uses English wording on the supplement page', async () => {
  setLocale('en')
  serve()
  show()
  expect(await screen.findByRole('heading', { name: 'Upload additional materials', level: 1 })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Submit additional materials' })).toBeTruthy()
})
