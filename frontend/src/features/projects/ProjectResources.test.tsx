import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import ProjectResources from './ProjectResources'

const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
afterEach(() => {
  cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks()
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
})

const files = Array.from({ length: 12 }, (_, index) => ({ id: `f${index}`, filename: `研究${index}.xlsx`,
  size_bytes: 1024, uploaded_at: '2026-10-01T01:00:00Z', parse_status: 'parsed', error: null }))
const workbook = { filename: files[0].filename, sheets: [{ name: '数据', columns: ['值'], row_count: 1,
  column_count: 1, preview_rows: [[5]], warnings: [] }] }
const props = { projectId: 'p1', onSaved: vi.fn(), onSectionChange: vi.fn() }
function api(readFiles: () => Promise<Response>, readPreview = async () => Response.json(workbook)) {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === '/api/v1/excel/config') return Response.json({ max_upload_bytes: 100000, preview_row_limit: 20 })
    if (url.endsWith('/files')) return readFiles()
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
