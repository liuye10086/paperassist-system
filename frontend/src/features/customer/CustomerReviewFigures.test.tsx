import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import CustomerMaterials from './CustomerMaterials'
import type { PaperMaterialNote } from './paperMaterials'

const base = '/api/v1/projects/p1'
const targets = [
  { id: 'sci:section:introduction', label: '范围与背景' },
  { id: 'sci:review:brain', label: '脑内稳态' },
  { id: 'sci:section:discussion', label: '综合讨论与局限' },
  { id: 'sci:section:conclusion', label: '结论' },
]
const files = [
  { id: 'figure', filename: '综述示意图.png', file_type: 'png', parse_status: 'stored' },
  { id: 'document', filename: '笔记.docx', file_type: 'docx', parse_status: 'parsed' },
]

function open(review: boolean, existing?: PaperMaterialNote) {
  setApiSession('csrf', 'customer-test')
  let note = existing
  const writes: { file_id: string; result: string; target_id: string | null; expected_revision: number }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith(base + '/files?')) return Response.json({ items: files, total: files.length })
    if (url.startsWith(base + '/paper-materials?')) return Response.json({
      items: note ? [note] : [], targets, review_figure_placement: review,
    })
    if (url.startsWith(base + '/paper-materials/') && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      const target = targets.find(target => target.id === body.target_id)
      writes.push(body)
      note = { id: url.split('/').at(-1)!, file_id: body.file_id, result: body.result, revision: body.expected_revision + 1,
        target_id: body.target_id, target_label: target?.label ?? null, target_available: !!target }
      return Response.json(note)
    }
    if (url.includes('/file-batches?')) return Response.json({ items: [], page: 1, page_size: 5, total: 0 })
    return new Response(null, { status: 404 })
  }))
  render(<CustomerMaterials projectId="p1" forWriting="sci" onContinue={vi.fn()} onUnavailable={vi.fn()}
    registerLeaveGuard={() => () => {}} />)
  return writes
}

afterEach(() => { cleanup(); clearApiSession(); vi.unstubAllGlobals() })

it('marks an uploaded review figure for automatic placement and accepts a section without a caption', async () => {
  const writes = open(true)
  const button = await screen.findByRole('button', { name: '设置配图' })
  const row = within(button.closest('li')!)
  expect(row.getByText(/自动安排/)).toBeTruthy()
  expect(writes).toHaveLength(0)
  fireEvent.click(button)
  const select = screen.getByRole('combobox', { name: '入稿章节' })
  expect(select).toHaveProperty('value', '')
  for (const target of targets) expect(within(select).getByRole('option', { name: target.label })).toBeTruthy()
  fireEvent.change(select, { target: { value: targets[1].id } })
  fireEvent.click(screen.getByRole('button', { name: '保存配图设置' }))
  await waitFor(() => expect(row.queryByRole('combobox')).toBeNull())
  await waitFor(() => expect(row.getByText(/脑内稳态/)).toBeTruthy())
  expect(writes).toEqual([{ file_id: 'figure', expected_revision: 0, target_id: targets[1].id, result: '' }])
  const doc = within(screen.getByText('笔记.docx').closest('li')!)
  fireEvent.click(doc.getByRole('button', { name: '添加说明' }))
  expect(doc.getByLabelText('文件说明（选填）')).toBeTruthy()
  expect(doc.queryByRole('combobox')).toBeNull()
})

it('restores automatic placement and clears an existing caption and credit', async () => {
  const writes = open(true, { id: 'note', file_id: 'figure', revision: 3, result: '原图注。出处 A。', target_id: targets[0].id,
    target_label: targets[0].label, target_available: true })
  fireEvent.click(await screen.findByRole('button', { name: '设置配图' }))
  const select = screen.getByRole('combobox', { name: '入稿章节' })
  const caption = screen.getByRole('textbox', { name: '图注与出处（选填）' })
  expect(select).toHaveProperty('value', targets[0].id)
  expect(caption).toHaveProperty('value', '原图注。出处 A。')
  fireEvent.change(select, { target: { value: '' } })
  fireEvent.change(caption, { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配图设置' }))
  await waitFor(() => expect(screen.queryByRole('combobox')).toBeNull())
  expect(writes).toEqual([{ file_id: 'figure', expected_revision: 3, target_id: null, result: '' }])
  await waitFor(() => expect(screen.queryByText('原图注。出处 A。')).toBeNull())
  expect(within(screen.getByText('综述示意图.png').closest('li')!).getByText(/自动安排/)).toBeTruthy()
})

it('explains the fallback for a removed section and allows keeping automatic placement explicitly', async () => {
  const writes = open(true, { id: 'note', file_id: 'figure', revision: 1, result: '', target_id: 'sci:review:removed',
    target_label: '旧主题', target_available: false })
  const button = await screen.findByRole('button', { name: '设置配图' })
  expect(within(button.closest('li')!).getByText(/旧主题.*自动安排/)).toBeTruthy()
  fireEvent.click(button)
  expect(screen.getByRole('combobox', { name: '入稿章节' })).toHaveProperty('value', '')
  fireEvent.click(screen.getByRole('button', { name: '保存配图设置' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0].target_id).toBeNull()
})

it('keeps the existing image description editor in original research projects', async () => {
  open(false)
  const row = within((await screen.findByText('综述示意图.png')).closest('li')!)
  const button = row.getByRole('button', { name: '添加说明' })
  await waitFor(() => expect(button).toHaveProperty('disabled', false))
  fireEvent.click(button)
  expect(row.getByLabelText('文件说明（选填）')).toBeTruthy()
  expect(row.queryByRole('combobox')).toBeNull()
  expect(row.queryByText(/自动安排/)).toBeNull()
})

it('refreshes figure placements when the project file list has not changed', async () => {
  const existing = { id: 'note', file_id: 'figure', revision: 1, result: '', target_id: targets[0].id,
    target_label: targets[0].label, target_available: true }
  open(true, existing)
  const row = within((await screen.findByRole('button', { name: '设置配图' })).closest('li')!)
  expect(row.getByText(/范围与背景/)).toBeTruthy()
  Object.assign(existing, { revision: 2, target_id: targets[2].id, target_label: targets[2].label })
  fireEvent.click(screen.getByRole('button', { name: '刷新资料' }))
  await waitFor(() => expect(row.getByText(/综合讨论与局限/)).toBeTruthy())
})
