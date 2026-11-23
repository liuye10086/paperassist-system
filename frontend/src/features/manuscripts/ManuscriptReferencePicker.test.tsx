import { useState } from 'react'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { setLocale } from '../../shared/i18n'
import type { Reference } from '../literature/literatureApi'
import ManuscriptReferencePicker, { type SelectedReference } from './ManuscriptReferencePicker'

const stamp = '2026-11-22T01:00:00Z'
function candidate(id = 'ref1'): Reference {
  return {
    id, reference_id: 'book1', project_id: 'p1', pmid: '321',
    record: {
      pmid: '321', title: `Study ${id}`, authors: ['Researcher'], year: 2024, journal: 'Sample Journal', doi: null,
      abstract: [{ label: 'Methods', text: 'We assessed 10 samples.' }, { label: 'Results', text: 'Seven samples passed.' }],
      abstract_status: 'available', full_text_status: 'not_acquired', verification_status: 'not_verified',
      doi_resolution_status: 'not_checked', keywords: [], mesh_terms: [], full_text_links: [],
    },
    source: {
      search_id: 'search1', receipt_id: 'receipt1', query: 'sample', effective_query: 'sample',
      source_kind: 'synthetic_fixture', retrieved_at: stamp, ordinal: 1, cached: false,
      source_download_url: '/api/v1/projects/p1/literature/receipts/receipt1/source',
    },
    selection: { status: 'candidate', note: '', revision: 1 }, created_at: stamp, updated_at: stamp,
  }
}
function setup(items: Reference[]) {
  const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    expect(init?.method ?? 'GET').toBe('GET')
    const {pathname, searchParams} = new URL(path, 'http://localhost')
    expect(pathname).toBe('/api/v1/projects/p1/literature/references')
    expect([null, 'shortlisted']).toContain(searchParams.get('selection'))
    const page = Number(searchParams.get('page')), selection = searchParams.get('selection')
    const matching = selection ? items.filter(ref => ref.selection.status === selection) : items
    return Response.json({ project_id: 'p1', items: matching.slice((page - 1) * 10, page * 10), page, page_size: 10, total: matching.length })
  })
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}
function Harness({ active = true, disabled = false, initial = [], onChange = () => {} }: {
  active?: boolean; disabled?: boolean; initial?: SelectedReference[]; onChange?: (next: SelectedReference[]) => void
}) {
  const [selected, setSelected] = useState(initial)
  return <ManuscriptReferencePicker projectId="p1" active={active} disabled={disabled} selected={selected}
    onChange={next => { setSelected(next); onChange(next) }} />
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })

it('uses an unreviewed candidate directly and replaces or removes its original paragraph in one click', async () => {
  const ref = candidate(), fetcher = setup([ref]), change = vi.fn()
  render(<Harness onChange={change} />)
  const group = within(await screen.findByRole('group', { name: 'Study ref1' }))
  expect(screen.getByRole('region', { name: '项目候选文献' }).tabIndex).toBe(0)
  expect(group.getByText(/Sample Journal/)).toBeTruthy()
  expect(group.getByText(/PMID 321/)).toBeTruthy()
  expect(group.getByText(/合成测试资料/)).toBeTruthy()
  for (const { text } of ref.record.abstract) {
    fireEvent.click(group.getByRole('checkbox', { name: new RegExp(text) }))
    expect(change).toHaveBeenLastCalledWith([{ project_reference_id: 'ref1', search_id: 'search1', quote: text }])
    expect(screen.getByText('已选 1 / 20 篇')).toBeTruthy()
  }
  fireEvent.click(group.getByRole('checkbox', { name: /Seven samples/ }))
  expect(change).toHaveBeenLastCalledWith([])
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('loads a page only while active, keeps selections across pages and respects the disabled editor', async () => {
  const fetcher = setup(Array.from({ length: 11 }, (_, i) => candidate(`ref${i + 1}`)))
  const { rerender } = render(<Harness active={false} />)
  expect(fetcher).not.toHaveBeenCalled()
  rerender(<Harness />)
  const group = within(await screen.findByRole('group', { name: 'Study ref1' }))
  fireEvent.click(group.getByRole('checkbox', { name: /We assessed/ }))
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  expect(await screen.findByRole('group', { name: 'Study ref11' })).toBeTruthy()
  expect(screen.getByText('已选 1 / 20 篇')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '上一页' }))
  const restored = within(await screen.findByRole('group', { name: 'Study ref1' }))
  expect(restored.getByRole('checkbox', { name: /We assessed/ })).toHaveProperty('checked', true)
  rerender(<Harness disabled />)
  expect(restored.getByRole('checkbox', { name: /We assessed/ }).matches(':disabled')).toBe(true)
})

it('allows replacing or clearing an existing selection at the limit and blocks adding the 21st reference', async () => {
  setup([candidate(), candidate('extra')])
  const initial = Array.from({ length: 20 }, (_, i) => ({
    project_reference_id: `ref${i + 1}`, search_id: 'search1', quote: 'We assessed 10 samples.',
  }))
  render(<Harness initial={initial} />)
  const first = within(await screen.findByRole('group', { name: 'Study ref1' }))
  const extra = within(screen.getByRole('group', { name: 'Study extra' }))
  expect(extra.getByRole('checkbox', { name: /Seven samples/ }).matches(':disabled')).toBe(true)
  fireEvent.click(first.getByRole('checkbox', { name: /Seven samples/ }))
  expect(first.getByRole('checkbox', { name: /Seven samples/ })).toHaveProperty('checked', true)
  fireEvent.click(first.getByRole('checkbox', { name: /Seven samples/ }))
  expect(extra.getByRole('checkbox', { name: /Seven samples/ }).matches(':disabled')).toBe(false)
})

it('filters all saved candidates to the project shortlist, resets the page and keeps choices from both views', async () => {
  const all = Array.from({ length: 40 }, (_, i) => candidate(`ref${i + 1}`))
  all[35].selection.status = 'shortlisted'
  const fetcher = setup(all), change = vi.fn()
  render(<Harness onChange={change} />)
  const initial = within(await screen.findByRole('group', { name: 'Study ref1' }))
  fireEvent.click(initial.getByRole('checkbox', { name: /We assessed/ }))
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  expect(await screen.findByRole('group', { name: 'Study ref11' })).toBeTruthy()
  const filter = screen.getByRole('combobox', { name: '筛选候选状态' })
  fireEvent.change(filter, { target: { value: 'shortlisted' } })
  const shortlisted = within(await screen.findByRole('group', { name: 'Study ref36' }))
  expect(shortlisted.getByText('已入选')).toBeTruthy()
  expect(screen.getByText('已选 1 / 20 篇')).toBeTruthy()
  expect(screen.queryByRole('group', { name: 'Study ref1' })).toBeNull()
  fireEvent.click(shortlisted.getByRole('checkbox', { name: /Seven samples/ }))
  fireEvent.change(filter, { target: { value: '' } })
  const restored = within(await screen.findByRole('group', { name: 'Study ref1' }))
  expect(restored.getByRole('checkbox', { name: /We assessed/ })).toHaveProperty('checked', true)
  expect(screen.getByText('已选 2 / 20 篇')).toBeTruthy()
  expect(change).toHaveBeenCalledTimes(2)
  expect(fetcher.mock.calls.map(([url]) => url.split('?')[1])).toEqual(['page=1', 'page=2', 'page=1&selection=shortlisted', 'page=1'])
})

it('distinguishes an empty shortlist from an empty project', async () => {
  setLocale('en')
  setup([candidate()])
  render(<Harness />)
  await screen.findByRole('group', { name: 'Study ref1' })
  fireEvent.change(screen.getByRole('combobox', { name: 'Filter selection status' }), { target: { value: 'shortlisted' } })
  expect(await screen.findByText('No references have been shortlisted in this project.')).toBeTruthy()
  fireEvent.change(screen.getByRole('combobox', { name: 'Filter selection status' }), { target: { value: '' } })
  expect(await screen.findByRole('group', { name: 'Study ref1' })).toBeTruthy()
})

it('offers the literature search directly from the picker when the owner provides navigation', async () => {
  setup([])
  const onFindLiterature = vi.fn()
  const props = {projectId: 'p1', active: true, disabled: false, selected: [], onChange: vi.fn(), onFindLiterature}
  const view = render(<ManuscriptReferencePicker {...props} />)
  fireEvent.click(await screen.findByRole('button', {name: '查找文献'}))
  expect(onFindLiterature).toHaveBeenCalledOnce()
  view.rerender(<ManuscriptReferencePicker {...props} disabled />)
  expect(screen.getByRole('button', {name: '查找文献'}).matches(':disabled')).toBe(true)
})

it('shows why unavailable abstracts and manually excluded papers cannot be selected', async () => {
  const missing = candidate('missing'), excluded = candidate('excluded')
  missing.record.abstract = []
  missing.record.abstract_status = 'not_returned'
  excluded.selection.status = 'excluded'
  setLocale('en')
  setup([missing, excluded])
  render(<Harness />)
  const empty = within(await screen.findByRole('group', { name: 'Study missing' }))
  expect(empty.getByText('Abstract not returned')).toBeTruthy()
  expect(empty.queryByRole('checkbox')).toBeNull()
  const skip = within(screen.getByRole('group', { name: 'Study excluded' }))
  expect(skip.getByText('Excluded manually')).toBeTruthy()
  expect(skip.queryAllByRole('checkbox').some(input => !input.matches(':disabled'))).toBe(false)
})

it('offers a single choice for duplicate passages in a stored abstract', async () => {
  const ref = candidate()
  ref.record.abstract = [{ label: 'Summary', text: 'Same passage.' }, { label: 'Finding', text: 'Same passage.' }]
  setup([ref])
  render(<Harness />)
  const group = within(await screen.findByRole('group', { name: 'Study ref1' }))
  expect(group.getAllByRole('checkbox', { name: /Same passage/ })).toHaveLength(1)
})

it('shows the full long paragraph and accepts only a user-selected contiguous excerpt of up to 6000 characters', async () => {
  const ref = candidate()
  const long = 'a'.repeat(6000) + ' distinctive ending'
  ref.record.abstract = [{ label: null, text: long }, { label: null, text: 'β🧬'.repeat(2600) }]
  setup([ref])
  const onChange = vi.fn()
  render(<Harness onChange={onChange} />)
  const group = within(await screen.findByRole('group', { name: 'Study ref1' }))
  expect(group.getByText(long)).toBeTruthy()
  const input = group.getByRole('textbox', { name: '摘录此段连续原文' })
  const choose = group.getByRole('checkbox', { name: '选用此摘录' })
  expect(choose.matches(':disabled')).toBe(true)
  fireEvent.change(input, { target: { value: 'invented excerpt' } })
  expect(choose.matches(':disabled')).toBe(true)
  fireEvent.change(input, { target: { value: long } })
  expect(choose.matches(':disabled')).toBe(true)
  fireEvent.change(input, { target: { value: 'distinctive ending' } })
  fireEvent.click(choose)
  expect(onChange).toHaveBeenLastCalledWith([{ project_reference_id: ref.id, search_id: ref.source.search_id, quote: 'distinctive ending' }])
  fireEvent.click(group.getByRole('checkbox', { name: /β🧬/ }))
  expect(onChange).toHaveBeenLastCalledWith([{ project_reference_id: ref.id, search_id: ref.source.search_id, quote: 'β🧬'.repeat(2600) }])
})

it('preserves a previously saved search snapshot and lets users remove it when the latest abstract has changed', async () => {
  setup([candidate()])
  const old = { project_reference_id: 'ref1', search_id: 'older', quote: 'An earlier stored abstract.' }
  const change = vi.fn()
  render(<Harness initial={[old]} onChange={change} />)
  const group = within(await screen.findByRole('group', { name: 'Study ref1' }))
  expect(group.getByText(old.quote)).toBeTruthy()
  expect(group.getAllByRole('checkbox').some(input => (input as HTMLInputElement).checked)).toBe(false)
  fireEvent.click(group.getByRole('button', { name: '移除此摘录' }))
  expect(change).toHaveBeenLastCalledWith([])
})

it('distinguishes a failed page request from an empty library and retries only the failed read', async () => {
  setLocale('en')
  const fetcher = setup([])
  fetcher.mockResolvedValueOnce(Response.json({}, { status: 500 }))
  render(<Harness />)
  expect(await screen.findByRole('alert')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByText('This project has no saved candidate references yet.')).toBeTruthy()
  expect(fetcher).toHaveBeenCalledTimes(2)
})
