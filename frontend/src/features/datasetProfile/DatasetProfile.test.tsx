import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setLocale } from '../../shared/i18n'
import { source, binding, profile, issue, rowResponse, preparedSource } from './profileFixtures'
import DatasetProfile from './DatasetProfile'

function mockApi() {
 const fetch = vi.fn(async (url: string) => {
  const parsed = new URL(url, 'http://test'); const prepared = url.includes('/pd1/'); const currentSource = prepared ? preparedSource : source
  if (parsed.pathname.endsWith('/profile')) return Response.json({ ...profile, source: currentSource, data_range: prepared ? 'C5:C50' : profile.data_range })
  if (parsed.pathname.endsWith('/issues')) { const kind = parsed.searchParams.get('kind')!; const page = Number(parsed.searchParams.get('page')); return Response.json({ source: currentSource, rules_version: 'excel_profile_v1', kind, column: kind === 'duplicate' ? null : 3, page, page_size: 20, total: kind === 'missing' ? 21 : kind === 'duplicate' ? 2 : 1, items: kind === 'duplicate' ? [27,48].map(row => ({ row, column: null, coordinate: null, kind: null, value: null, group_first_row: 27, group_size: 2 })) : kind === 'missing' && page === 1 ? Array.from({ length: 20 }, (_, i) => ({ ...issue, row: i + 2, coordinate: `C${i + 2}`, kind: null, value: null })) : [issue] }) }
  if (parsed.pathname.endsWith('/rows')) return Response.json(rowResponse(Number(parsed.searchParams.get('start_row')), prepared))
  throw new Error(url)
 }); vi.stubGlobal('fetch', fetch); return fetch
}
async function component() {
 return DatasetProfile
}
async function open() { const Component = await component(); const view = render(<Component base="/api/v1/projects/p1/files/f1" binding={binding} />); await screen.findByRole('heading', { name: '字段详细概况' }); return { Component, view } }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })

test('prepared quality profile exposes a parent-bound quality processing entry', async () => {
 mockApi(); render(<DatasetProfile base="/api/v1/projects/p1/files/f1" projectId="p1" binding={{ ...preparedSource, source: preparedSource }} />)
 expect(await screen.findByRole('button', { name: '按此版本处理质量问题' })).toBeTruthy()
})

test('selected source directly loads numeric, categorical and four temporal summaries without saving', async () => {
 const fetch = mockApi(); await open(); const user = userEvent.setup(); await user.click(screen.getByText('C · Measure'))
 expect(screen.getByText('Q1')).toBeTruthy(); expect(screen.getByText('NA')).toBeTruthy()
 for (const name of ['日期', '日期时间', '时刻', '时长']) expect(screen.getAllByText(name).length).toBeGreaterThan(0)
 expect(screen.getByText('文本日期识别仅作提示，不改变原类型。')).toBeTruthy()
 expect(document.body.textContent).not.toContain('std_insufficient'); expect(document.body.textContent).not.toContain(source.dataset_sha256)
 expect(fetch.mock.calls.every(([url]) => !url.includes('analysis-setup'))).toBe(true)
})
test('missing issues page by 20 and C27 loads and highlights the actual raw row across pages', async () => {
 const fetch = mockApi(); await open(); const user = userEvent.setup(); await user.click(screen.getByText('C · Measure')); await user.click(screen.getByRole('button', { name: '缺失值 · 21' })); await screen.findByRole('button', { name: 'C2' })
 await user.click(screen.getByRole('button', { name: '下一页问题' })); await user.click(await screen.findByRole('button', { name: 'C27' }))
 const table = await screen.findByRole('table', { name: '位置核对（保留 Excel 原始坐标）' }); expect(table.querySelector('[data-coordinate="C27"]')?.className).toContain('profile-cell-selected')
 expect(fetch.mock.calls.some(([url]) => url.includes('page=2&page_size=20'))).toBe(true)
 expect(fetch.mock.calls.some(([url]) => url.includes('/dataset-versions/d1/rows?start_row=21&limit=20'))).toBe(true)
})
test('duplicate groups show first row and all members and temporal candidates have separate filters', async () => {
 mockApi(); await open(); const user = userEvent.setup(); await user.click(screen.getByRole('button', { name: '查看重复行' })); await screen.findByText('起始行 27 · 共 2 行')
 expect(screen.getByRole('button', { name: '第 27 行' })).toBeTruthy(); expect(screen.getByRole('button', { name: '第 48 行' })).toBeTruthy()
 await user.click(screen.getByText('C · Measure')); for (const name of ['有效日期文本 · 1', '无效日期文本 · 1', '歧义日期文本 · 1']) expect(screen.getByRole('button', { name })).toBeTruthy()
})
test('switching to prepared version clears old issues and rows and ignores a late response', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let finish!: (r: Response) => void
 const { Component, view } = await open(); const user = userEvent.setup(); await user.click(screen.getByText('C · Measure')); await user.click(screen.getByRole('button', { name: '异常候选 · 1' })); await user.click(await screen.findByRole('button', { name: 'C27' })); await screen.findByRole('table', { name: '位置核对（保留 Excel 原始坐标）' })
 fetch.mockImplementation(url => url.includes('/d1/profile/issues') ? new Promise(resolve => { finish = resolve }) : original(url))
 await user.click(screen.getByRole('button', { name: '缺失值 · 21' })); view.rerender(<Component base="/api/v1/projects/p1/files/f1" binding={{ ...preparedSource, source: preparedSource }} />)
 await act(async () => finish(Response.json({ source, rules_version: 'excel_profile_v1', kind: 'missing', column: 3, page: 1, page_size: 20, total: 1, items: [issue] })))
 expect(screen.queryByRole('button', { name: 'C27' })).toBeNull(); expect(screen.queryByRole('table', { name: '位置核对（保留 Excel 原始坐标）' })).toBeNull()
 cleanup(); render(<Component base="/api/v1/projects/p1/files/f1" binding={{ ...preparedSource, source: preparedSource }} />); await screen.findByText('C · Measure'); await user.click(screen.getByText('C · Measure')); await user.click(screen.getByRole('button', { name: '异常候选 · 1' })); await user.click(await screen.findByRole('button', { name: 'C27' })); await screen.findByRole('table', { name: '位置核对（保留 Excel 原始坐标）' })
 expect(fetch.mock.calls.some(([url]) => url.includes('/prepared-dataset-versions/pd1/rows?start_row=25&limit=20'))).toBe(true)
})
test('profile errors expose translated retry and source mismatch is rejected', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let failed = true
 fetch.mockImplementation(url => failed && url.endsWith('/profile') ? Promise.resolve(Response.json({ detail: { code: 'internal_bad_code', message: 'secret' } }, { status: 500 })) : original(url))
 const Component = await component(); render(<Component base="/api/v1/projects/p1/files/f1" binding={binding} />); await screen.findByRole('alert'); expect(document.body.textContent).not.toContain('secret'); failed = false; await userEvent.setup().click(screen.getByRole('button', { name: '重试概况' })); await screen.findByRole('heading', { name: '字段详细概况' })
 cleanup(); fetch.mockImplementation(async () => Response.json({ ...profile, source: { ...source, dataset_sha256: 'c'.repeat(64) } })); render(<Component base="/api/v1/projects/p1/files/f1" binding={binding} />); await screen.findByRole('alert'); expect(screen.queryByText('C · Measure')).toBeNull()
})
test('English summary and warning texts contain no untranslated UI or backend codes', async () => {
 setLocale('en'); mockApi(); const Component = await component(); render(<Component base="/api/v1/projects/p1/files/f1" binding={binding} />); await screen.findByRole('heading', { name: 'Detailed field profile' }); await userEvent.setup().click(screen.getByText('C · Measure'))
 expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/); expect(document.body.textContent).not.toContain('std_insufficient'); expect(screen.getByText('Duration')).toBeTruthy()
})

test('English raw unconfirmed unit is translated while saved filename and field name stay unchanged', async () => {
 setLocale('en'); const fetch = mockApi(); const original = fetch.getMockImplementation()!
 fetch.mockImplementation(url => url.endsWith('/profile') ? Promise.resolve(Response.json({ ...profile, filename: '原始样本.xlsx', fields: [{ ...profile.fields[0], name: '原始浓度', unit: { status: 'unconfirmed', value: null } }] })) : original(url))
 const Component = await component(); render(<Component base="/api/v1/projects/p1/files/f1" binding={binding} />)
 await screen.findByRole('heading', { name: 'Detailed field profile' }); await userEvent.setup().click(screen.getByText('C · 原始浓度'))
 expect(screen.getByText(/unit Unconfirmed/)).toBeTruthy()
 expect(document.body.textContent).toContain('原始样本.xlsx'); expect(document.body.textContent).toContain('原始浓度')
 expect(document.body.textContent?.replaceAll('原始样本.xlsx', '').replaceAll('原始浓度', '')).not.toMatch(/[\u4e00-\u9fff]/)
})
test('late profile cannot replace newly selected version', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let finish!: (r: Response) => void
 fetch.mockImplementation(url => url.endsWith('/d1/profile') ? new Promise(resolve => { finish = resolve }) : original(url)); const Component = await component(); const view = render(<Component base="/api/v1/projects/p1/files/f1" binding={binding} />)
 view.rerender(<Component base="/api/v1/projects/p1/files/f1" binding={{ ...preparedSource, source: preparedSource }} />); await screen.findByRole('heading', { name: '字段详细概况' }); await act(async () => finish(Response.json({ ...profile, record_count: 999 })))
 await waitFor(() => expect(document.body.textContent).not.toContain('999')); expect(document.body.textContent).toContain('整理数据 v2')
})

test('issue and row failures can each retry without exposing server prose', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let failIssue = true; let failRows = true
 fetch.mockImplementation(url => failIssue && url.includes('/issues?') || failRows && url.includes('/rows?') ? Promise.resolve(Response.json({ detail: { code: 'secret_code', message: 'private' } }, { status: 500 })) : original(url))
 await open(); const user = userEvent.setup(); await user.click(screen.getByText('C · Measure')); await user.click(screen.getByRole('button', { name: '异常候选 · 1' })); await screen.findByRole('button', { name: '重试问题读取' }); failIssue = false
 await user.click(screen.getByRole('button', { name: '重试问题读取' })); await user.click(await screen.findByRole('button', { name: 'C27' })); await screen.findByRole('button', { name: '重试位置读取' }); failRows = false
 await user.click(screen.getByRole('button', { name: '重试位置读取' })); await screen.findByRole('table', { name: '位置核对（保留 Excel 原始坐标）' }); expect(document.body.textContent).not.toContain('private'); expect(document.body.textContent).not.toContain('secret_code')
})

test('a late raw row page cannot appear in a newly selected prepared profile', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let finish!: (r: Response) => void
 fetch.mockImplementation(url => url.includes('/d1/rows?') ? new Promise(resolve => { finish = resolve }) : original(url))
 const { Component, view } = await open(); const user = userEvent.setup(); await user.click(screen.getByText('C · Measure')); await user.click(screen.getByRole('button', { name: '异常候选 · 1' })); await user.click(await screen.findByRole('button', { name: 'C27' })); await screen.findByText('正在读取对应数据行……')
 view.rerender(<Component base="/api/v1/projects/p1/files/f1" binding={{ ...preparedSource, source: preparedSource }} />); await screen.findByRole('heading', { name: '字段详细概况' }); await act(async () => finish(Response.json(rowResponse(21))))
 expect(screen.queryByRole('table', { name: '位置核对（保留 Excel 原始坐标）' })).toBeNull(); expect(screen.queryByText('定位：C27；每次读取 20 行。')).toBeNull()
})

test('field details explain missing proportion, confirmed units and non-destructive issue rules', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!
 fetch.mockImplementation(url => url.endsWith('/profile') ? Promise.resolve(Response.json({ ...profile, fields: [{ ...profile.fields[0], categories: { ...profile.fields[0].categories, other_count: 21 } }] })) : original(url))
 await open(); const user = userEvent.setup(); await user.click(screen.getByText('C · Measure'))
 expect(screen.getByText('缺失 21 / 49（42.86%）')).toBeTruthy(); expect(screen.getByText(/单位 已确认：kg/)).toBeTruthy(); expect(screen.getByText('分类不同值 2 个；显示前 10 项，其余 21 条记录。')).toBeTruthy()
 await user.click(screen.getByRole('button', { name: '异常候选 · 1' })); expect(screen.getByText('规则命中仅为异常候选，不代表数值有错误。')).toBeTruthy()
 await user.click(screen.getByRole('button', { name: '查看重复行' })); expect(screen.getByText('按首次出现行标识各重复组，列出全部成员，不删除记录。')).toBeTruthy()
})

test('zero records have no calculable missing proportion and explicitly confirmed empty unit is labeled', async () => {
 const fetch = mockApi(); fetch.mockImplementation(async () => Response.json({ ...profile, record_count: 0, blank_row_count: 0, duplicate_groups: 0, duplicate_rows: 0, duplicate_extra_rows: 0, fields: [{ ...profile.fields[0], unit: { status: 'confirmed', value: '' }, type_counts: {}, missing_count: 0, non_missing_count: 0, distinct_count: 0, numeric: null, categories: null, temporal: [], issue_counts: {}, time_candidates: { valid_count: 0, invalid_count: 0, ambiguous_count: 0 } }] }))
 await open(); await userEvent.setup().click(screen.getByText('C · Measure')); expect(screen.getByText('无记录，缺失比例不可计算。')).toBeTruthy(); expect(screen.getByText(/已确认无单位/)).toBeTruthy()
})
