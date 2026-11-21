import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import AccountsPanel from './AccountsPanel'

const account = { id: 'other', email: 'other@example.test', role: 'analyst', review_status: 'approved', active: true, admin_revision: 3, updated_at: 1792700000, allowed_actions: ['edit'] }
let fetchMock: ReturnType<typeof vi.fn>
beforeEach(() => {
  setApiSession('csrf', 'self')
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'PATCH') return Response.json({ ...account, role: 'customer', admin_revision: 4 })
    if (url.startsWith('/api/v1/admin/users?')) return Response.json({ items: [account], total: 1, page: 1, page_size: 10 })
    return Response.json({ detail: { code: 'invalid_request' } }, { status: 422 })
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); clearApiSession(); setLocale('zh-CN') })

function mount() { render(<AccountsPanel userId="self" onForbidden={vi.fn()} onAudit={vi.fn()} />) }
async function row() { return within((await screen.findByText(account.email)).closest('tr')!) }

it.each(['zh-CN', 'en'] as const)('announces a saved account and the re-login it causes until the next edit in %s', async locale => {
  setLocale(locale)
  const saved = locale === 'en' ? 'Account saved. This account must sign in again.' : '账号已保存，该账号需重新登录。'
  mount()
  const item = await row()
  fireEvent.change(item.getByLabelText(locale === 'en' ? 'Account role' : '账号角色'), { target: { value: 'customer' } })
  expect(screen.queryByText(saved)).toBeNull()
  fireEvent.click(item.getByRole('button', { name: locale === 'en' ? 'Save account change' : '保存账号变更' }))
  const status = await screen.findByText(saved)
  expect(status.closest('[role="status"]')).toBeTruthy()
  fireEvent.change((await row()).getByLabelText(locale === 'en' ? 'Account status' : '账号状态'), { target: { value: 'false' } })
  expect(screen.queryByText(saved)).toBeNull()
})
