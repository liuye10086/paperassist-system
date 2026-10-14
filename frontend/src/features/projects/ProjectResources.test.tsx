import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import ProjectResources from './ProjectResources'
import { setLocale } from '../../shared/i18n'
import { clearApiSession } from '../../shared/api/client'
import { lifecycleResponse } from '../files/lifecycleFixtures'

const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
afterEach(() => {
  cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks()
  vi.useRealTimers(); setLocale('zh-CN')
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
})

const files = Array.from({ length: 12 }, (_, index) => ({ id: `f${index}`, filename: `研究${index}.xlsx`, file_type: 'xlsx',
  size_bytes: 1024, uploaded_at: '2026-10-01T01:00:00Z', parse_status: 'parsed', error: null }))
const workbook = { filename: files[0].filename, sheets: [{ name: '数据', columns: ['值'], row_count: 1,
  column_count: 1, preview_rows: [[5]], warnings: [] }] }
const props = { projectId: 'p1', onSaved: vi.fn(), onSectionChange: vi.fn() }
function api(readFiles: () => Promise<Response>, readPreview = async () => Response.json(workbook)) {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.includes('/structure-versions?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5, latest_version: 0 })
    if (url.includes('/file-batches?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url === '/api/v1/excel/config') return Response.json({ max_upload_bytes: 100000, preview_row_limit: 20 })
    if (url.endsWith('/files')) return readFiles()
    if (url.includes('/files?page=')) {
      const rows = await (await readFiles()).json()
      const page = Number(new URL(url, 'http://localhost').searchParams.get('page'))
      return Response.json({ items: rows.slice((page - 1) * 5, page * 5).map((file: object) => ({ ...file,
        purposes: [], metadata_revision: 1, uploader_recorded: false })), total: rows.length, page, page_size: 5 })
    }
    if (url.endsWith('/preview')) return readPreview()
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

test('analysis shows file loading and failure with a read-only recovery instead of an empty-upload message', async () => {
  let rejectFiles!: (error: Error) => void
  const fetch = api(() => new Promise((_resolve, reject) => { rejectFiles = reject }))
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="analysis" />)
  expect(screen.getByRole('status').textContent).toContain('正在读取文件列表')
  expect(screen.queryByText('请先在当前项目上传一份可预览的 Excel。')).toBeNull()
  await act(async () => { rejectFiles(new TypeError('offline')) })
  expect(screen.getByRole('alert').textContent).toContain('文件列表读取失败')
  expect(screen.queryByText('请先在当前项目上传一份可预览的 Excel。')).toBeNull()
  fetch.mockImplementation(async (url: string) => {
    if (url.endsWith('/files')) return Response.json(files)
    throw new Error(`Unexpected recovery: ${url}`)
  })
  await user.click(screen.getByRole('button', { name: '刷新文件列表' }))
  await waitFor(() => expect(screen.getByLabelText('用于分析的文件').textContent).toContain(files[0].filename))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

const detail = { ...files[0], file_type: 'xlsx', purposes: [], metadata_revision: 1, uploader_recorded: false,
  source: { kind: 'legacy_excel', preview_available: true, preview_row_limit: 20, parser_version: null },
  references: { analysis_setups: 1, analysis_runs: 2, figures: 3, explanations: 4, reports: 5, tasks: 6,
    structure_versions: 0, dataset_versions: 0, legacy_jobs: 7, active_tasks: 8, recovery_candidates: 9 },
  retention: { policy: 'internal_testing_keep', automatic_deletion: false, deletion_available: false } }

function libraryApi(save = async (_init?: RequestInit) => Response.json({ ...detail, purposes: ['raw_data'], metadata_revision: 2 })) {
  let reads = 0
  const fetch = api(async () => Response.json(files))
  const original = fetch.getMockImplementation()!
  fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/details')) { reads++; return Response.json({ ...detail, metadata_revision: reads }) }
    if (url.endsWith('/purposes')) return save(init)
    if (url.endsWith('/analysis-sheets')) return Response.json({ sheets: ['数据'] })
    if (url.endsWith('/analysis-setup')) return Response.json(null)
    if (url.includes('/analysis-profile?')) return Response.json({ sheet_name: '数据', row_count: 1, columns: [], warnings: [] })
    return lifecycleResponse(url, detail.id) ?? original(url, init)
  })
  return fetch
}

test('file pagination preserves preview, the full analysis selection and page across sections', async () => {
  const fetch = libraryApi()
  const user = userEvent.setup()
  const view = render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `预览 ${files[0].filename}` }))
  await screen.findByRole('table')
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByRole('button', { name: `预览 ${files[5].filename}` })
  expect(screen.queryByRole('button', { name: `预览 ${files[0].filename}` })).toBeNull()
  expect(screen.getByRole('table')).toBeTruthy()
  view.rerender(<ProjectResources {...props} section="analysis" />)
  await user.selectOptions(screen.getByLabelText('用于分析的文件'), files[11].id)
  const pageReads = fetch.mock.calls.filter(([url]) => url.includes('/files?page=')).length
  view.rerender(<ProjectResources {...props} section="tasks" />)
  expect(fetch.mock.calls.filter(([url]) => url.includes('/files?page=')).length).toBe(pageReads)
  view.rerender(<ProjectResources {...props} section="files" />)
  await screen.findByRole('button', { name: `预览 ${files[5].filename}` })
  view.rerender(<ProjectResources {...props} section="analysis" />)
  expect((screen.getByLabelText('用于分析的文件') as HTMLSelectElement).value).toBe(files[11].id)
})

test('upload refreshes the first page without removing a purpose draft', async () => {
  const fetch = libraryApi()
  const original = fetch.getMockImplementation()!
  fetch.mockImplementation(async (url, init) => init?.method === 'POST' && url.endsWith('/files')
    ? Response.json({ file: files[0], preview: workbook }) : original(url, init))
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('原始数据'))
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByRole('button', { name: `预览 ${files[5].filename}` })
  await user.upload(screen.getByLabelText('选择 Excel 文件'), new File(['xlsx'], 'new.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  await screen.findByRole('button', { name: `预览 ${files[0].filename}` })
  expect((screen.getByLabelText('原始数据') as HTMLInputElement).checked).toBe(true)
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/files')).length).toBeGreaterThan(1)
})

test('purpose conflict preserves draft and reread adopts current revision before saving', async () => {
  let conflict = true
  const fetch = libraryApi(async () => conflict
    ? Response.json({ detail: { code: 'file_metadata_conflict' } }, { status: 409 })
    : Response.json({ ...detail, purposes: ['raw_data'], metadata_revision: 3 }))
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('原始数据'))
  await user.click(screen.getByRole('button', { name: '保存用途' }))
  expect((await screen.findByRole('alert')).textContent).toContain('用途已被更新')
  expect((screen.getByLabelText('原始数据') as HTMLInputElement).checked).toBe(true)
  await user.click(screen.getByRole('button', { name: '重新读取文件详情' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '保存用途' }).hasAttribute('disabled')).toBe(false))
  expect((screen.getByLabelText('原始数据') as HTMLInputElement).checked).toBe(true)
  conflict = false
  await user.click(screen.getByRole('button', { name: '保存用途' }))
  await screen.findByText('文件用途已保存。')
  const writes = fetch.mock.calls.filter(([url]) => url.endsWith('/purposes'))
  expect(JSON.parse(writes[1][1]!.body as string)).toEqual({ expected_revision: 2, purposes: ['raw_data'] })
})

test('purpose timeout keeps draft, offers reread and guards duplicate submission synchronously', async () => {
  const fetch = libraryApi(init => new Promise((_resolve, reject) => {
    init!.signal!.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')))
  }))
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('原始数据'))
  vi.useFakeTimers()
  const form = screen.getByRole('button', { name: '保存用途' }).closest('form')!
  fireEvent.submit(form); fireEvent.submit(form)
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/purposes'))).toHaveLength(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.getByRole('alert').textContent).toContain('保存用途超时')
  expect((screen.getByLabelText('原始数据') as HTMLInputElement).checked).toBe(true)
  expect(screen.getByRole('button', { name: '重新读取文件详情' })).toBeTruthy()
})

test('English details show all reference counts and retention without internal metadata', async () => {
  setLocale('en'); const fetch = libraryApi()
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `File details ${files[0].filename}` }))
  await screen.findByRole('group', { name: 'File purposes' })
  const details = within(screen.getByRole('region', { name: 'File details' }))
  expect(screen.getByText('Uploader not recorded')).toBeTruthy()
  expect(screen.getByText('Existing preview: first 20 rows')).toBeTruthy()
  for (const label of ['Analysis setups', 'Analysis runs', 'Figures', 'Explanations', 'Reports', 'Tasks', 'Legacy jobs', 'Active tasks', 'Recovery candidates']) {
    expect(details.getByText(label).nextElementSibling?.textContent).toMatch(/^\d$/)
  }
  const lifecycle = within(details.getByRole('region', { name: 'File retention and deletion requests' }))
  expect(lifecycle.getByText('You may submit a deletion request. Its retained or blocked outcome is recorded immediately; no future automatic deletion is scheduled.')).toBeTruthy()
  expect(lifecycle.getByText('This operation preserves originals, historical versions and backups without deleting or hiding files. Historical artifact availability requires separate verification.')).toBeTruthy()
  expect(lifecycle.getByRole('button', { name: 'Submit deletion request' }).hasAttribute('disabled')).toBe(false)
  expect(await lifecycle.findByText('No deletion requests yet.')).toBeTruthy()
  expect(lifecycle.getByText('0 deletion requests')).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
  const historyReads = fetch.mock.calls.filter(([url]) => url.includes('/lifecycle/deletion-requests'))
  expect(historyReads).toHaveLength(1)
  expect(historyReads[0][0]).toBe('/api/v1/projects/p1/files/f0/lifecycle/deletion-requests?page=1&page_size=10')
  expect(fetch.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
  expect(screen.queryByText(/legacy_excel|metadata_revision|internal_testing_keep|f0/)).toBeNull()
})

test('switching projects isolates late details and clears drafts; logout clears visible data', async () => {
  const fetch = libraryApi()
  const original = fetch.getMockImplementation()!
  let finish!: (response: Response) => void
  fetch.mockImplementation(async (url, init) => url === '/api/v1/projects/p1/files/f0/details'
    ? new Promise(resolve => { finish = resolve }) : original(url, init))
  const user = userEvent.setup()
  const view = render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  view.rerender(<ProjectResources {...props} projectId="p2" section="files" />)
  await act(async () => { finish(Response.json(detail)) })
  expect(screen.queryByLabelText('原始数据')).toBeNull()
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('原始数据'))
  act(() => clearApiSession())
  expect(screen.queryByLabelText('原始数据')).toBeNull()
  expect(screen.queryByRole('button', { name: `预览 ${files[0].filename}` })).toBeNull()
})

test('lost project access clears all file information', async () => {
  const fetch = libraryApi()
  const original = fetch.getMockImplementation()!
  fetch.mockImplementation(async (url, init) => url.endsWith('/details')
    ? Response.json({ detail: { code: 'project_not_found' } }, { status: 404 }) : original(url, init))
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  expect((await screen.findByRole('alert')).textContent).toContain('项目不存在或无权访问')
  expect(screen.queryByRole('button', { name: `预览 ${files[0].filename}` })).toBeNull()
})

test('file library reads only while its workspace is visible', async () => {
  const fetch = libraryApi()
  const view = render(<ProjectResources {...props} section="files" active={false} />)
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/files'))).toBe(true))
  expect(fetch.mock.calls.some(([url]) => url.includes('/files?page='))).toBe(false)
  view.rerender(<ProjectResources {...props} section="files" active />)
  await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` })
  expect(fetch.mock.calls.filter(([url]) => url.includes('/files?page='))).toHaveLength(1)
})

test('keyboard pagination retains a usable focus target after page loading', async () => {
  libraryApi()
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  const next = await screen.findByRole('button', { name: '下一页' })
  next.focus()
  await user.keyboard('{Enter}')
  await screen.findByRole('button', { name: `文件详情 ${files[5].filename}` })
  expect(document.activeElement).toBe(next)
  await user.keyboard('{Shift>}{Tab}{/Shift}{Enter}')
  await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` })
})

test('a network save failure retains choices and does not clear the existing metadata', async () => {
  libraryApi(async () => { throw new TypeError('offline') })
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('修订材料'))
  await user.click(screen.getByRole('button', { name: '保存用途' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('修订材料') as HTMLInputElement).checked).toBe(true)
  expect(screen.getByText('文件引用汇总')).toBeTruthy()
})

test('purpose timeout releases the form even if the pending response ignores abort', async () => {
  libraryApi(async () => new Promise<Response>(() => {}))
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('原始数据'))
  vi.useFakeTimers()
  fireEvent.submit(screen.getByRole('button', { name: '保存用途' }).closest('form')!)
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.getByRole('alert').textContent).toContain('保存用途超时')
  expect(screen.getByRole('button', { name: '重新读取文件详情' }).hasAttribute('disabled')).toBe(false)
  expect((screen.getByLabelText('原始数据') as HTMLInputElement).checked).toBe(true)
})

test('reread shows the latest saved purposes alongside the preserved local draft', async () => {
  const fetch = libraryApi(async () => Response.json({ detail: { code: 'file_metadata_conflict' } }, { status: 409 }))
  const original = fetch.getMockImplementation()!
  let reads = 0
  fetch.mockImplementation(async (url, init) => url.endsWith('/details')
    ? Response.json({ ...detail, metadata_revision: ++reads, purposes: reads > 1 ? ['figure'] : [] }) : original(url, init))
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('原始数据'))
  await user.click(screen.getByRole('button', { name: '保存用途' }))
  await screen.findByRole('alert')
  await user.click(screen.getByRole('button', { name: '重新读取文件详情' }))
  await screen.findByText('已保存用途：图表资料')
  expect((screen.getByLabelText('原始数据') as HTMLInputElement).checked).toBe(true)
  expect((screen.getByLabelText('图表资料') as HTMLInputElement).checked).toBe(false)
})

test('late detail GET cannot roll back successful purpose revision or the next save', async () => {
  let finishSave!: (response: Response) => void
  let finishRead!: (response: Response) => void
  let writes = 0
  const fetch = libraryApi(async () => ++writes === 1 ? new Promise(resolve => { finishSave = resolve })
    : Response.json({ ...detail, metadata_revision: 3, purposes: ['raw_data', 'figure'] }))
  const original = fetch.getMockImplementation()!
  let reads = 0
  fetch.mockImplementation(async (url, init) => url.endsWith('/details')
    ? ++reads === 1 ? Response.json(detail) : new Promise(resolve => { finishRead = resolve }) : original(url, init))
  const user = userEvent.setup()
  const view = render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('原始数据'))
  await user.click(screen.getByRole('button', { name: '保存用途' }))
  view.rerender(<ProjectResources {...props} section="analysis" />)
  view.rerender(<ProjectResources {...props} section="files" />)
  await waitFor(() => expect(reads).toBe(2))
  await act(async () => { finishSave(Response.json({ ...detail, metadata_revision: 2, purposes: ['raw_data'] })) })
  await act(async () => { finishRead(Response.json({ ...detail, references: { ...detail.references, tasks: 99 } })) })
  expect(screen.getByText('已保存用途：原始数据')).toBeTruthy()
  expect(screen.getByText('任务引用').nextElementSibling?.textContent).toBe('99')
  expect((screen.getByLabelText('原始数据') as HTMLInputElement).checked).toBe(true)
  await user.click(screen.getByLabelText('图表资料'))
  await user.click(screen.getByRole('button', { name: '保存用途' }))
  await screen.findByText('文件用途已保存。')
  const requests = fetch.mock.calls.filter(([url]) => url.endsWith('/purposes'))
  expect(JSON.parse(requests[1][1]!.body as string)).toEqual({ expected_revision: 2, purposes: ['raw_data', 'figure'] })
})

test('late page GET cannot roll back saved purposes when the file was on another page', async () => {
  let finishSave!: (response: Response) => void
  let finishPage!: (response: Response) => void
  const fetch = libraryApi(async () => new Promise(resolve => { finishSave = resolve }))
  const original = fetch.getMockImplementation()!
  let firstPageReads = 0
  fetch.mockImplementation(async (url, init) => url.includes('/files?page=1&') && ++firstPageReads > 1
    ? new Promise(resolve => { finishPage = resolve }) : original(url, init))
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` }))
  await user.click(await screen.findByLabelText('原始数据'))
  await user.click(screen.getByRole('button', { name: '保存用途' }))
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByRole('button', { name: `文件详情 ${files[5].filename}` })
  await user.click(screen.getByRole('button', { name: '上一页' }))
  await act(async () => { finishSave(Response.json({ ...detail, metadata_revision: 2, purposes: ['raw_data'] })) })
  await act(async () => { finishPage(Response.json({ items: files.slice(0, 5).map(file => ({ ...file,
    purposes: [], metadata_revision: 1, uploader_recorded: false })), total: files.length, page: 1, page_size: 5 })) })
  const row = (await screen.findByRole('button', { name: `文件详情 ${files[0].filename}` })).closest('li')!
  expect(within(row).getByText('原始数据')).toBeTruthy()
})

test('saved preview gives feedback beside the clicked file and scrolls to the completed preview', async () => {
  let finish!: (response: Response) => void
  api(async () => Response.json(files), () => new Promise(resolve => { finish = resolve }))
  const scroll = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll })
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  const preview = await screen.findByRole('button', { name: `预览 ${files[0].filename}` })
  const row = preview.closest('li')!
  await user.click(preview)
  expect(within(row).getByRole('status').textContent).toContain('正在读取预览')
  await act(async () => { finish(Response.json(workbook)) })
  expect(row.getAttribute('aria-current')).toBe('true')
  expect(within(row).getByRole('status').textContent).toContain('当前预览')
  expect(scroll).toHaveBeenCalledWith({ block: 'start', behavior: 'auto' })
  expect(scroll.mock.instances.at(-1)).toBe(screen.getByRole('table').closest('.preview-panel'))
})

test('preview completion in a hidden section does not move the visible page and remains available on return', async () => {
  let finish!: (response: Response) => void
  api(async () => Response.json(files), () => new Promise(resolve => { finish = resolve }))
  const scroll = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll })
  const user = userEvent.setup()
  const view = render(<ProjectResources {...props} section="files" />)
  await user.click(await screen.findByRole('button', { name: `预览 ${files[0].filename}` }))
  view.rerender(<ProjectResources {...props} section="analysis" />)
  await act(async () => { finish(Response.json(workbook)) })
  expect(scroll).not.toHaveBeenCalled()
  view.rerender(<ProjectResources {...props} section="files" />)
  expect(screen.getByRole('table')).toBeTruthy()
  expect(scroll).not.toHaveBeenCalled()
})

test('saved preview failure gives a short row status, one detailed alert and a working retry', async () => {
  let attempts = 0
  api(async () => Response.json(files), async () => {
    if (++attempts === 1) throw new TypeError('offline')
    return Response.json(workbook)
  })
  const user = userEvent.setup()
  render(<ProjectResources {...props} section="files" />)
  const preview = await screen.findByRole('button', { name: `预览 ${files[0].filename}` })
  const row = preview.closest('li')!
  await user.click(preview)
  expect((await within(row).findByRole('status')).textContent).toBe('读取预览失败。')
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(screen.getByRole('alert').textContent).toContain('无法连接后端')
  expect(row.getAttribute('aria-current')).toBeNull()
  await user.click(preview)
  await screen.findByRole('table')
  expect(within(row).queryByRole('alert')).toBeNull()
  expect(row.getAttribute('aria-current')).toBe('true')
})

test('choosing a new local file clears the current saved preview without scrolling on validation errors', async () => {
  api(async () => Response.json(files))
  const scroll = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll })
  const user = userEvent.setup({ applyAccept: false })
  render(<ProjectResources {...props} section="files" />)
  const preview = await screen.findByRole('button', { name: `预览 ${files[0].filename}` })
  await user.click(preview)
  await screen.findByRole('table')
  expect(scroll).toHaveBeenCalledOnce()
  await user.upload(screen.getByLabelText('选择 Excel 文件'), new File(['bad'], 'invalid.xls'))
  expect((await screen.findByRole('alert')).textContent).toContain('仅支持 .xlsx')
  expect(preview.closest('li')!.getAttribute('aria-current')).toBeNull()
  expect(scroll).toHaveBeenCalledOnce()
})

test('batch completion preserves the opened sheet and purpose draft without opening the new file',async()=>{
 const fetch=libraryApi();const original=fetch.getMockImplementation()!;let snapshot:Record<string,unknown>|null=null
 fetch.mockImplementation(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/preview'))return Response.json({...workbook,sheets:[...workbook.sheets,{...workbook.sheets[0],name:'第二张表',preview_rows:[[42]]}]})
  if(url.endsWith('/file-batches')&&init?.method==='POST'){
   const body=JSON.parse(String(init.body));snapshot={id:'b1',project_id:'p1',created_at:'2026-10-10T00:00:00Z',revision:1,items:body.items.map((i:{client_id:string;filename:string;size_bytes:number},ordinal:number)=>({id:i.client_id,ordinal,filename:i.filename,size_bytes:i.size_bytes,status:'pending',file_id:null,task:null,error:null}))};return Response.json(snapshot)
  }
  if(url.includes('/items/')){const items=(snapshot!.items as Record<string,unknown>[]).map(i=>({...i,status:'parsed',file_id:'new-file'}));snapshot={...snapshot,revision:4,items};return Response.json(items[0])}
  if(url.endsWith('/file-batches/b1'))return Response.json(snapshot)
  if(url.includes('/file-batches?'))return Response.json({items:snapshot?[snapshot]:[],total:snapshot?1:0,page:1,page_size:5})
  return original(url,init)
 });const user=userEvent.setup();render(<ProjectResources {...props} section="files"/>);await user.click(await screen.findByRole('button',{name:`预览 ${files[0].filename}`}));await screen.findByRole('table');await user.selectOptions(screen.getByLabelText('工作表'),'1');await user.click(screen.getByRole('button',{name:`文件详情 ${files[0].filename}`}));await user.click(await screen.findByRole('checkbox',{name:'原始数据'}));await user.upload(screen.getByLabelText('批量选择 Excel / Word / PDF / 图片 文件'),new File(['a'],'new.xlsx'));await user.click(screen.getByRole('button',{name:'开始上传'}));await screen.findByText(/解析完成/);expect((screen.getByLabelText('工作表') as HTMLSelectElement).value).toBe('1');expect(screen.getByRole('table').textContent).toContain('42');expect((screen.getByRole('checkbox',{name:'原始数据'}) as HTMLInputElement).checked).toBe(true);expect(fetch.mock.calls.filter(([url])=>url.endsWith('/preview'))).toHaveLength(1)
})
