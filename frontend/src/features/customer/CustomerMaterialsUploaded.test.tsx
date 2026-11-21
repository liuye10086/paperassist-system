// B03 task 7: a file that appears after the page opened counts as the material added for the paragraph.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
