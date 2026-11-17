import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import CustomerDeliveries from './CustomerDeliveries'

const base = '/api/v1/projects/history/customer-workspace/deliveries'
const summary = { id: 'original-snapshot', delivery_id: 'writing-delivery', title: '固定历史成果',
  kind: 'sci_draft', revision: 2, published_at: '2026-11-17T00:00:00Z', member_count: 1 }
const guard = () => () => {}

afterEach(() => {
  cleanup()
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
