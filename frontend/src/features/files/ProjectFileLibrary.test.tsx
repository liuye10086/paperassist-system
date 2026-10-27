import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import ProjectFileLibrary from './ProjectFileLibrary'
import { setLocale } from '../../shared/i18n'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })

test.each(['zh-CN', 'en'] as const)('batch summaries survive pagination, refresh, details and purpose save (%s)', async locale => {
  setLocale(locale)
  const user = userEvent.setup()
  const batch = { created_at: '2026-10-13T01:00:00Z', item_count: 3, item_position: 2 }
  const file = { id: 'f', filename: 'same.xlsx', file_type: 'xlsx', size_bytes: 100, uploaded_at: '2026-10-13T01:01:00Z',
    parse_status: 'queued', error: null, purposes: [], metadata_revision: 1, uploader_recorded: true, upload_batch: batch }
  const other = { ...file, id: 'other', upload_batch: { ...batch, created_at: '2026-10-12T01:00:00Z', item_position: 1 } }
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/purposes')) return Response.json({ ...file, purposes: ['paper'], metadata_revision: 2 })
    if (url.endsWith('/details')) return Response.json({ ...file, references: {}, source: { kind: 'excel_parse', preview_available: false, preview_row_limit: 20 } })
    if (init?.method) throw new Error(`Unexpected mutation ${url}`)
    const page = Number(new URL(url, 'http://localhost').searchParams.get('page'))
    if (!page) throw new Error(`Unexpected request ${url}`)
    return Response.json({ items: page === 1 ? [file, other, { ...file, id: 'legacy', upload_batch: null }, { ...file, id: 'old', upload_batch: undefined }] : [{ ...other, id: 'page2' }], total: 6, page, page_size: 5 })
  })
  vi.stubGlobal('fetch', fetch)
  render(<ProjectFileLibrary projectId="p" active uploadVersion={0} busy={false} previewState={null} onPreview={() => {}} onUnavailable={() => {}} />)
  const text = locale === 'zh-CN'
    ? `上传批次：${new Date(batch.created_at).toLocaleString(locale)} · 本批登记 3 项 · 第 2 项`
    : `Upload batch: ${new Date(batch.created_at).toLocaleString(locale)} · 3 registered items · Item 2`
  expect(await screen.findByText(text)).toBeTruthy()
  expect(screen.getAllByText(locale === 'zh-CN' ? '未记录上传批次' : 'Upload batch not recorded')).toHaveLength(2)
  const row = screen.getByText(text).closest('li')!
  expect(within(row).getByRole('link', { name: locale === 'zh-CN' ? '下载 same.xlsx' : 'Download same.xlsx' }).getAttribute('href')).toContain('/f/download')
  await user.click(within(row).getByRole('button', { name: locale === 'zh-CN' ? '文件详情 same.xlsx' : 'File details same.xlsx' }))
  await screen.findByRole('checkbox', { name: locale === 'zh-CN' ? '论文' : 'Paper' })
  expect(screen.getByText(text)).toBeTruthy()
  await user.click(screen.getByRole('checkbox', { name: locale === 'zh-CN' ? '论文' : 'Paper' }))
  await user.click(screen.getByRole('button', { name: locale === 'zh-CN' ? '保存用途' : 'Save purposes' }))
  await screen.findByText(locale === 'zh-CN' ? '文件用途已保存。' : 'File purposes saved.')
  expect(screen.getByText(text)).toBeTruthy()
  await user.click(screen.getByRole('button', { name: locale === 'zh-CN' ? '返回文件列表' : 'Back to files' }))
  await user.click(await screen.findByRole('button', { name: locale === 'zh-CN' ? '下一页' : 'Next page' }))
  await screen.findByText(locale === 'zh-CN' ? /第 1 项$/ : /Item 1$/)
  await user.click(screen.getByRole('button', { name: locale === 'zh-CN' ? '上一页' : 'Previous page' }))
  await screen.findByText(text)
  await user.click(screen.getByRole('button', { name: locale === 'zh-CN' ? '刷新文件列表' : 'Refresh files' }))
  await screen.findByText(text)
  expect(fetch.mock.calls.filter(([url]) => url.includes('file-batches'))).toHaveLength(0)
})
