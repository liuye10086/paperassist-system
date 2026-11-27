// B03 task 7: a file that appears after the page opened counts as the material added for the paragraph.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import CustomerMaterials from './CustomerMaterials'

const base = '/api/v1/projects/customer-project-1'
const file = (id: string, filename: string) =>
  ({ id, filename, file_type: 'docx', parse_status: 'parsed', size_bytes: 10, uploaded_at: '2026-11-19T06:20:00Z', error: null })
let items = [file('file-old', 'methods.docx')]
beforeEach(() => {
  setApiSession('csrf', 'customer-test')
  items = [file('file-old', 'methods.docx')]
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.startsWith(base + '/files?')
    ? Response.json({ items, total: items.length, page: 1, page_size: 5 })
    : Response.json({ items: [], total: 0, page: 1, page_size: 5 })))
})
afterEach(() => { cleanup(); clearApiSession(); vi.unstubAllGlobals() })

it('shows batched and older files once, with the description editor in the uploaded materials section', async () => {
  const methods = file('file-batched', 'methods.docx')
  const legacy = file('file-legacy', 'legacy.docx')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.startsWith(base + '/files?')) {
      const items = url.includes('outside_document_batches=true') ? [legacy] : [methods, legacy]
      return Response.json({ items, total: items.length, page: 1, page_size: 5 })
    }
    if (url.startsWith(base + '/paper-materials')) return Response.json({ items: [], targets: [] })
    return Response.json({ items: [{
      id: 'batch-1', project_id: 'customer-project-1', created_at: methods.uploaded_at, revision: 2,
      items: [{ id: 'item-1', ordinal: 0, filename: methods.filename, file_id: methods.id,
        size_bytes: 10, status: 'parsed', task: null, error: null }],
    }], total: 1, page: 1, page_size: 5 })
  }))
  render(<CustomerMaterials projectId="customer-project-1" onContinue={vi.fn()} onUnavailable={vi.fn()}
    registerLeaveGuard={() => () => {}} forWriting="sci" />)

  const history = within(await screen.findByRole('region', { name: '已上传资料' }))
  const row = within((await history.findByText('methods.docx')).closest('li')!)
  await history.findByText('legacy.docx')
  expect(screen.queryByRole('heading', { name: '已上传批次' })).toBeNull()
  const batch = within(history.getByRole('heading', { name: /^上传批次 ·/ }).closest('article')!)
  expect(batch.queryByText(/已保存原件/)).toBeNull()
  for (const column of ['文件名', '文件性质', '解析状态', '操作']) {
    expect(batch.getByText(column)).toBeTruthy()
  }
  expect(history.getAllByText('文件性质')).toHaveLength(2)
  expect(screen.getAllByText('methods.docx')).toHaveLength(1)
  expect(row.getByText('Word 文档')).toBeTruthy()
  expect(row.getByRole('link', { name: '下载 methods.docx' }).getAttribute('href')).toBe(base + '/files/file-batched/download')
  const edit = row.getByRole('button', { name: '添加说明' })
  await waitFor(() => expect(edit).toHaveProperty('disabled', false))
  fireEvent.click(edit)
  expect(history.getByRole('textbox', { name: '文件说明（选填）' })).toBeTruthy()
})

it('reports an upload only for a file that was not there when the page opened', async () => {
  const onUploaded = vi.fn()
  render(<CustomerMaterials projectId="customer-project-1" onContinue={vi.fn()} onUnavailable={vi.fn()}
    registerLeaveGuard={() => () => {}} forWriting="sci" onUploaded={onUploaded} />)
  await screen.findByText('methods.docx')
  fireEvent.click(screen.getByRole('button', { name: '刷新资料' }))
  await screen.findByText('methods.docx')
  expect(onUploaded).not.toHaveBeenCalled()
  items = [file('file-new', 'figure-notes.docx'), ...items]
  fireEvent.click(screen.getByRole('button', { name: '刷新资料' }))
  await screen.findByText('figure-notes.docx')
  await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1))
})
