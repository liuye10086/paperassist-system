import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { clearApiSession } from '../../shared/api/client'
import AuthBoundary from './AuthBoundary'

afterEach(() => {
  cleanup()
  clearApiSession()
  vi.unstubAllGlobals()
})

it('reveals and hides the login password without submitting, and masks it again after returning to login', async () => {
  const fetch = vi.fn(async (_url: string) => new Response(null, { status: 401 }))
  vi.stubGlobal('fetch', fetch)
  render(<AuthBoundary><p>Private workspace</p></AuthBoundary>)

  const password = await screen.findByLabelText('密码', { exact: true })
  expect(password).toHaveProperty('type', 'password')
  fireEvent.change(password, { target: { value: 'synthetic-password' } })
  fireEvent.click(screen.getByRole('button', { name: '显示密码' }))
  expect(password).toHaveProperty('type', 'text')
  expect(password).toHaveProperty('value', 'synthetic-password')
  fireEvent.click(screen.getByRole('button', { name: '隐藏密码' }))
  expect(password).toHaveProperty('type', 'password')
  expect(password).toHaveProperty('value', 'synthetic-password')

  fireEvent.click(screen.getByRole('button', { name: '显示密码' }))
  fireEvent.click(screen.getByRole('button', { name: '注册账号' }))
  fireEvent.click(screen.getByRole('button', { name: '返回登录' }))
  expect(screen.getByLabelText('密码', { exact: true })).toHaveProperty('type', 'password')
  expect(screen.getByLabelText('密码', { exact: true })).toHaveProperty('value', '')
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/login'))).toBe(false)
})

it('validates confirmation and returns to login after submitting an application', async () => {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => url.endsWith('/me')
    ? new Response(null, { status: 401 })
    : Response.json({ status: 'submitted' }, { status: 202 }))
  vi.stubGlobal('fetch', fetch)
  render(<AuthBoundary><p>Private workspace</p></AuthBoundary>)
  fireEvent.click(await screen.findByRole('button', { name: '注册账号' }))
  expect(screen.queryByLabelText('申请说明（选填）')).toBeNull()
  fireEvent.change(screen.getByLabelText('称呼'), { target: { value: '申请人' } })
  fireEvent.change(screen.getByLabelText('单位或团队（选填）'), { target: { value: '合成研究团队' } })
  fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'new@example.test' } })
  fireEvent.change(screen.getByLabelText('密码', { exact: true }), { target: { value: 'synthetic-password' } })
  const confirmation = screen.getByLabelText('确认密码')
  fireEvent.change(confirmation, { target: { value: 'different-password' } })
  fireEvent.submit(confirmation.closest('form')!)
  expect(screen.getByRole('alert').textContent).toBe('两次输入的密码不一致。')
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/register'))).toBe(false)

  fireEvent.change(confirmation, { target: { value: 'synthetic-password' } })
  fireEvent.submit(confirmation.closest('form')!)
  await screen.findByText('申请已提交，请登录查看审核状态。')
  expect(screen.getByLabelText('邮箱')).toHaveProperty('value', 'new@example.test')
  expect(screen.getByLabelText('密码', { exact: true })).toHaveProperty('value', '')
  const [, request] = fetch.mock.calls.find(([url]) => url.endsWith('/register'))!
  expect(JSON.parse(String(request?.body))).toEqual({
    display_name: '申请人', email: 'new@example.test', password: 'synthetic-password', organization: '合成研究团队', note: '',
  })
  expect(screen.queryByText('Private workspace')).toBeNull()
})
