import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import ProjectList, { type ProjectListQuery } from './ProjectList'
import type { Project } from './projectTypes'

afterEach(cleanup)

const project: Project = { id: 'p1', name: '药学项目', project_type: 'sci', research_topic: '分组比较', file_count: 3,
  created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-30T11:00:00Z' }
const initialQuery: ProjectListQuery = { page: 1, pageSize: 10, q: '', type: '' }

function setup(options: { items?: Project[]; total?: number; query?: ProjectListQuery; loading?: boolean; error?: string } = {}) {
  const onQueryChange = vi.fn()
  const onOpen = vi.fn()
  const onRetry = vi.fn()
  const onCreate = vi.fn()
  function ControlledList() {
    const [query, setQuery] = useState(options.query ?? initialQuery)
    const [draft, setDraft] = useState(query.q)
    return <ProjectList items={options.items ?? [project]} total={options.total ?? 21} query={query}
      searchDraft={draft} onSearchDraftChange={setDraft} loading={options.loading ?? false} error={options.error ?? ''}
      onQueryChange={next => { onQueryChange(next); setQuery(next) }} onOpen={onOpen} onRetry={onRetry} onCreate={onCreate} />
  }
  render(<ControlledList />)
  return { user: userEvent.setup(), onQueryChange, onOpen, onRetry, onCreate }
}

test('shows the five project fields and a named open action', async () => {
  const { user, onOpen } = setup()
  const table = screen.getByRole('table', { name: '项目列表' })
  for (const name of ['项目名称', '项目类型', '创建时间', '最近更新时间', '文件数']) {
    expect(within(table).getByRole('columnheader', { name })).toBeTruthy()
  }
  expect(within(table).getByRole('cell', { name: '药学项目' })).toBeTruthy()
  expect(within(table).getByRole('cell', { name: 'SCI 科研论文' })).toBeTruthy()
  expect(within(table).getByRole('cell', { name: '3' })).toBeTruthy()
  expect(within(table).getByRole('cell', { name: new Date(project.created_at).toLocaleString('zh-CN') })).toBeTruthy()
  expect(within(table).getByRole('cell', { name: new Date(project.updated_at).toLocaleString('zh-CN') })).toBeTruthy()
  await user.click(screen.getByRole('button', { name: '打开项目 药学项目' }))
  expect(onOpen).toHaveBeenCalledWith('p1')
})

test('shows ten items per page by default with three page-size choices and totals', async () => {
  const { user, onQueryChange } = setup()
  const sizes = screen.getByLabelText('每页项目数') as HTMLSelectElement
  expect(sizes.value).toBe('10')
  expect(within(sizes).getAllByRole('option').map(option => (option as HTMLOptionElement).value)).toEqual(['10', '20', '50'])
  expect(screen.getByText('共 21 个项目 · 第 1 / 3 页')).toBeTruthy()
  expect((screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement).disabled).toBe(true)
  await user.click(screen.getByRole('button', { name: '下一页' }))
  expect(onQueryChange).toHaveBeenLastCalledWith({ ...initialQuery, page: 2 })
  await user.click(screen.getByRole('button', { name: '上一页' }))
  expect(onQueryChange).toHaveBeenLastCalledWith(initialQuery)
})

test('disables next-page navigation on the final page', () => {
  setup({ query: { ...initialQuery, page: 3 } })
  expect((screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement).disabled).toBe(true)
})

for (const submit of ['button', 'enter']) {
  test(`submits the search draft using ${submit} and returns to page one`, async () => {
    const { user, onQueryChange } = setup({ query: { ...initialQuery, page: 2, type: 'sci' } })
    await user.type(screen.getByLabelText('搜索项目名称'), '  药学  ')
    expect(onQueryChange).not.toHaveBeenCalled()
    if (submit === 'button') await user.click(screen.getByRole('button', { name: '搜索项目' }))
    else await user.type(screen.getByLabelText('搜索项目名称'), '{Enter}')
    expect(onQueryChange).toHaveBeenCalledOnce()
    expect(onQueryChange).toHaveBeenCalledWith({ ...initialQuery, q: '药学', type: 'sci' })
  })
}

test('changes the type immediately and preserves submitted search while returning to page one', async () => {
  const { user, onQueryChange } = setup({ query: { ...initialQuery, page: 3, q: '药学' } })
  await user.selectOptions(screen.getByLabelText('筛选项目类型'), 'thesis')
  expect(onQueryChange).toHaveBeenCalledWith({ ...initialQuery, q: '药学', type: 'thesis' })
})

test('changes page size and returns to page one while preserving filters', async () => {
  const query: ProjectListQuery = { page: 2, pageSize: 10, q: '药学', type: 'sci' }
  const { user, onQueryChange } = setup({ query })
  await user.selectOptions(screen.getByLabelText('每页项目数'), '50')
  expect(onQueryChange).toHaveBeenCalledWith({ ...query, page: 1, pageSize: 50 })
})

test('clears both filters and the draft while preserving page size', async () => {
  const { user, onQueryChange } = setup({ query: { page: 2, pageSize: 20, q: '药学', type: 'sci' } })
  await user.type(screen.getByLabelText('搜索项目名称'), '未提交')
  await user.click(screen.getByRole('button', { name: '清除筛选' }))
  expect(onQueryChange).toHaveBeenCalledWith({ ...initialQuery, pageSize: 20 })
  expect((screen.getByLabelText('搜索项目名称') as HTMLInputElement).value).toBe('')
})

test('offers creation for an empty project list', async () => {
  const { user, onCreate } = setup({ items: [], total: 0 })
  expect(screen.getByText('还没有项目，请先创建一个项目。')).toBeTruthy()
  expect(screen.queryByText('没有匹配的项目。')).toBeNull()
  await user.click(screen.getByRole('button', { name: '新建项目' }))
  expect(onCreate).toHaveBeenCalledOnce()
})

test('offers clearing filters for an empty filtered result', async () => {
  const { user, onQueryChange } = setup({ items: [], total: 0, query: { ...initialQuery, q: '无匹配' } })
  expect(screen.getByText('没有匹配的项目。')).toBeTruthy()
  expect(screen.queryByText('还没有项目，请先创建一个项目。')).toBeNull()
  await user.click(screen.getByRole('button', { name: '清除筛选' }))
  expect(onQueryChange).toHaveBeenCalledWith(initialQuery)
})

test('retains current table results while loading and allows changing filters', async () => {
  const { user, onQueryChange } = setup({ loading: true })
  expect(screen.getByRole('status').textContent).toContain('正在读取项目列表')
  expect(screen.getByRole('cell', { name: '药学项目' })).toBeTruthy()
  expect((screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement).disabled).toBe(true)
  await user.selectOptions(screen.getByLabelText('筛选项目类型'), 'sci')
  expect(onQueryChange).toHaveBeenCalledWith({ ...initialQuery, type: 'sci' })
})

test('shows list errors with retry without pretending the project list is empty', async () => {
  const { user, onRetry } = setup({ items: [], total: 0, error: '项目列表读取失败。' })
  expect(screen.getByRole('alert').textContent).toContain('项目列表读取失败。')
  expect(screen.queryByText('还没有项目，请先创建一个项目。')).toBeNull()
  await user.click(screen.getByRole('button', { name: '重试项目列表' }))
  expect(onRetry).toHaveBeenCalledOnce()
})

test('does not show an empty list message while the first request is loading', () => {
  setup({ items: [], total: 0, loading: true })
  expect(screen.queryByText('还没有项目，请先创建一个项目。')).toBeNull()
})
