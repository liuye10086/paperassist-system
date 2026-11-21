import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { createRef, useState } from 'react'
import { setLocale } from '../../shared/i18n'
import CustomerDeliveries from './CustomerDeliveries'

const base = '/api/v1/projects/history/customer-workspace/deliveries'
const summary = { id: 'original-snapshot', delivery_id: 'writing-delivery', title: '固定历史成果',
  kind: 'sci_draft', revision: 2, published_at: '2026-11-17T00:00:00Z', member_count: 1 }
const guard = () => () => {}

afterEach(() => {
  cleanup()
  setLocale('zh-CN')
  vi.unstubAllGlobals()
})

it('filters the published snapshots to the exact legacy delivery', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ items: [
    summary, { ...summary, id: 'other-snapshot', delivery_id: 'other-delivery', title: '另一个项目交付' },
  ] })))
  const select = vi.fn()
  render(<CustomerDeliveries projectId="history" initialDeliveryId="writing-delivery"
    onSelectSnapshot={select} headingRef={createRef()} registerLeaveGuard={guard} />)
  expect(await screen.findByText('固定历史成果')).toBeTruthy()
  expect(screen.queryByText('另一个项目交付')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查看交付 固定历史成果' }))
  expect(select).toHaveBeenCalledWith('original-snapshot')
})

it.each([true, false])('matches the delivery and exact fixed snapshot before showing material, exact = %s', async exact => {
  const fetch = vi.fn(async () => Response.json({ ...summary, delivery_id: exact ? 'writing-delivery' : 'other-delivery',
    members: [], package_url: null, feedback: [] }))
  const select = vi.fn()
  vi.stubGlobal('fetch', fetch)
  render(<CustomerDeliveries projectId="history" initialDeliveryId="writing-delivery" initialSnapshotId="original-snapshot"
    onSelectSnapshot={select} headingRef={createRef()} registerLeaveGuard={guard} />)
  if (exact) expect(await screen.findByRole('heading', { name: '固定历史成果' })).toBeTruthy()
  else {
    expect(await screen.findByText('该交付版本与链接不匹配。')).toBeTruthy()
    expect(screen.queryByText('固定历史成果')).toBeNull()
  }
  expect(fetch.mock.calls).toHaveLength(1)
  expect(fetch).toHaveBeenCalledWith(base + '/original-snapshot', expect.anything())
  fireEvent.click(screen.getByRole('button', { name: '返回交付列表' }))
  expect(select).toHaveBeenCalledWith(null)
})

// Published snapshots, newest first, as the list endpoint returns them. Revision 2 of the report was
// confirmed but never published, so the customer sees versions 1 and 3 only.
const report = { delivery_id: 'report-delivery', title: '血清指标比较报告', kind: 'analysis' }
const reportV3 = { ...report, id: 'report-v3', revision: 3, published_at: '2026-11-18T08:30:00Z', member_count: 3 }
const figures = { id: 'figures-v1', delivery_id: 'figure-delivery', title: '补充图件', kind: 'analysis', revision: 1,
  published_at: '2026-11-15T02:00:00Z', member_count: 2 }
// Published under the earlier requirement version, before the customer updated the requirements.
const reportV1 = { ...report, id: 'report-v1', revision: 1, published_at: '2026-11-12T01:10:00Z', member_count: 1 }
const member = (snapshot: string, id: string, name: string) => ({ id, name, format: 'docx', size_bytes: 10,
  download_url: `${base}/${snapshot}/members/${id}/download` })
const details: Record<string, unknown> = {
  'report-v3': { ...reportV3, package_url: `${base}/report-v3/download`, feedback: [],
    members: [member('report-v3', 'm1', 'a.docx'), member('report-v3', 'm2', 'b.png'), member('report-v3', 'm3', 'c.xlsx')] },
  'figures-v1': { ...figures, package_url: null, feedback: [],
    members: [member('figures-v1', 'f1', 'f1.png'), member('figures-v1', 'f2', 'f2.png')] },
  'report-v1': { ...reportV1, package_url: null, feedback: [], members: [member('report-v1', 'old', '旧版报告.docx')] },
}
const versions = (group: HTMLElement) => Array.from(group.querySelectorAll('.version-label'), label => label.textContent)
const minute = (time: string, locale = 'zh-CN') => new Date(time).toLocaleString(locale,
  { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

function serveGrouped() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url === base
    ? Response.json({ items: [reportV3, figures, reportV1] })
    : Response.json(details[url.slice(base.length + 1)])))
}

it('groups published snapshots by delivery and marks the newest one as the current delivery', async () => {
  serveGrouped()
  render(<CustomerDeliveries projectId="history" onSelectSnapshot={vi.fn()} headingRef={createRef()} registerLeaveGuard={guard} />)
  const reportGroup = await screen.findByRole('region', { name: '血清指标比较报告' })
  const figureGroup = screen.getByRole('region', { name: '补充图件' })
  expect(screen.getAllByRole('region')).toEqual([reportGroup, figureGroup])
  const current = within(reportGroup).getByText('当前交付')
  expect(current.closest('.customer-delivery-row')?.textContent).toContain('第 3 版')
  expect(within(reportGroup).getAllByText('当前交付')).toHaveLength(1)
  expect(within(reportGroup).getByRole('heading', { name: '之前发布的版本' })).toBeTruthy()
  expect(versions(reportGroup)).toEqual([`第 3 版 · ${minute(reportV3.published_at)}`, `第 1 版 · ${minute(reportV1.published_at)}`])
  expect(within(reportGroup).getByText('只列出已发布的版本，版次可能不连续。')).toBeTruthy()
  expect(within(figureGroup).getByText('当前交付')).toBeTruthy()
  expect(within(figureGroup).queryByText('之前发布的版本')).toBeNull()
})

it('downloads the package or the only file straight from the list and opens the details otherwise', async () => {
  serveGrouped()
  const select = vi.fn()
  render(<CustomerDeliveries projectId="history" onSelectSnapshot={select} headingRef={createRef()} registerLeaveGuard={guard} />)
  const pack = await screen.findByRole('link', { name: '下载交付 血清指标比较报告' })
  expect(pack.getAttribute('href')).toBe(`${base}/report-v3/download`)
  expect(pack.textContent).toBe('下载')
  // The older version from before the requirement update stays listed and downloadable (its only file).
  const old = await screen.findByRole('link', { name: '下载交付 血清指标比较报告 第 1 版' })
  expect(old.getAttribute('href')).toBe(`${base}/report-v1/members/old/download`)
  // Several files and no package: “下载” opens the delivery details.
  const several = await screen.findByRole('button', { name: '下载交付 补充图件' })
  expect(several.textContent).toBe('下载')
  fireEvent.click(several)
  expect(select).toHaveBeenCalledWith('figures-v1')
  fireEvent.click(screen.getByRole('button', { name: '查看交付 血清指标比较报告 第 1 版' }))
  expect(select).toHaveBeenLastCalledWith('report-v1')
})

it('labels the current delivery and versions in English', async () => {
  setLocale('en')
  serveGrouped()
  render(<CustomerDeliveries projectId="history" onSelectSnapshot={vi.fn()} headingRef={createRef()} registerLeaveGuard={guard} />)
  const reportGroup = await screen.findByRole('region', { name: '血清指标比较报告' })
  expect(within(reportGroup).getByText('Current delivery')).toBeTruthy()
  expect(within(reportGroup).getByRole('heading', { name: 'Earlier published versions' })).toBeTruthy()
  expect(versions(reportGroup)).toEqual([`Version 3 · ${minute(reportV3.published_at, 'en')}`,
    `Version 1 · ${minute(reportV1.published_at, 'en')}`])
  expect(await screen.findByRole('link', { name: 'Download deliverable 血清指标比较报告' })).toBeTruthy()
})

it.each(['zh-CN', 'en'] as const)('shows readable file formats when opening a delivery from the list in %s', async locale => {
  setLocale(locale)
  const formats = ['Docx', 'XLSX', 'pdf', 'PNG', 'jpg', 'jpeg', 'tiff', 'svg', 'zip', 'csv', 'tsv', 'bin']
  const snapshot = { ...reportV3, member_count: formats.length }
  const members = formats.map((format, index) => ({
    ...member(snapshot.id, format, 'result.' + format), format, size_bytes: 7_724_755 + index,
  }))
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url === base ? { items: [snapshot] }
    : { ...snapshot, package_url: null, feedback: [], members })))
  function View() {
    const [id, setId] = useState<string | null>(null)
    return <CustomerDeliveries projectId="history" initialSnapshotId={id ?? undefined}
      onSelectSnapshot={setId} headingRef={createRef()} registerLeaveGuard={guard} />
  }
  render(<View />)
  const english = locale === 'en'
  fireEvent.click(await screen.findByRole('button', { name: english ? /View deliverable/ : /查看交付/ }))
  const list = await screen.findByRole('list', { name: english ? 'Delivery files' : '交付文件' })
  const published = screen.getByText(minute(snapshot.published_at, locale), { selector: 'time' })
  expect(published.getAttribute('datetime')).toBe(snapshot.published_at)
  const rows = within(list).getAllByRole('listitem')
  const img = english ? 'Image' : '图片'
  expect(rows.map(row => row.querySelector('p')?.textContent?.split(' · ')[0])).toEqual([
    'Word', 'Excel', 'PDF', img, img, img, img, img,
    english ? 'ZIP archive' : 'ZIP 压缩包', english ? 'CSV table' : 'CSV 数据表',
    english ? 'TSV table' : 'TSV 数据表', english ? 'File' : '文件',
  ])
  expect(rows.map(row => row.querySelector('strong')?.textContent)).toEqual(members.map(file => file.name))
  expect(rows.map(row => row.querySelector('p')?.textContent?.split(' · ')[1])).toEqual(
    members.map(file => `${file.size_bytes.toLocaleString(locale)} ${english ? 'bytes' : '字节'}`),
  )
})
