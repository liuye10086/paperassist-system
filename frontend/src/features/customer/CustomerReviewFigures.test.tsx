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
    if (url === base + '/paper-materials') return Response.json({
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

it.each([true, false])('keeps SCI originals downloadable without offering placement or image notes (review: %s)', async review => {
  const writes = open(review, {id:'note', file_id:'figure', revision:3, result:'原图注。', target_id:targets[0].id,
    target_label:targets[0].label, target_available:true})
  const row = within((await screen.findByText('综述示意图.png')).closest('li')!)
  expect(row.getByRole('link', {name:'下载 综述示意图.png'}).getAttribute('href')).toBe(base + '/files/figure/download')
  expect(row.queryByRole('button')).toBeNull()
  expect(screen.queryByText(/自动安排/)).toBeNull()
  expect(screen.queryByText('原图注。')).toBeNull()
  expect(writes).toHaveLength(0)
})

it('saves non-image material notes without a figure placement choice', async () => {
  const writes = open(true)
  const row = within((await screen.findByText('笔记.docx')).closest('li')!)
  const add = row.getByRole('button', {name:'添加说明'})
  await waitFor(() => expect(add).toHaveProperty('disabled', false))
  fireEvent.click(add)
  fireEvent.change(row.getByLabelText('文件说明（选填）'), {target:{value:'原始实验笔记。'}})
  expect(row.queryByRole('combobox')).toBeNull()
  fireEvent.click(row.getByRole('button', {name:'保存说明'}))
  expect(await row.findByText('原始实验笔记。')).toBeTruthy()
  expect(writes).toEqual([{file_id:'document', expected_revision:0, target_id:null, result:'原始实验笔记。'}])
})
