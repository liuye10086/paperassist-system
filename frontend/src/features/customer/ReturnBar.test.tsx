import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { setLocale } from '../../shared/i18n'
import ReturnBar from './ReturnBar'
import { narrowScreenStyles } from '../../test/narrowScreenStyles'

afterEach(() => { cleanup(); setLocale('zh-CN') })

const target = { href: '#customer-project=p1&step=progress', label: '任务进度' }

it('shows the purpose and a return link to the stored address', () => {
  const { container } = render(<ReturnBar target={target}>正在为“任务进度”补充资料</ReturnBar>)
  expect(container.querySelector('.return-bar')).toBeTruthy()
  expect(screen.getByText('正在为“任务进度”补充资料')).toBeTruthy()
  expect(screen.getByRole('link', { name: '返回 任务进度' }).getAttribute('href')).toBe(target.href)
})

it('lets the page handle the return itself', () => {
  const onReturn = vi.fn()
  render(<ReturnBar target={target} onReturn={onReturn} />)
  fireEvent.click(screen.getByRole('link', { name: '返回 任务进度' }))
  expect(onReturn).toHaveBeenCalledWith(target.href)
})

it('renders nothing without a valid token', () => {
  const { container } = render(<ReturnBar target={null} />)
  expect(container.innerHTML).toBe('')
})

it('uses the English return text', () => {
  setLocale('en')
  render(<ReturnBar target={{ ...target, label: 'Project progress' }} />)
  expect(screen.getByRole('link', { name: 'Return to Project progress' })).toBeTruthy()
})

it('pins the return bar at the top while reading a narrow page', () => {
  const { container } = render(<ReturnBar target={target} />)
  const bar = container.querySelector('.return-bar')!
  const styles = narrowScreenStyles(bar, 'customer/returnBar.css')
  expect(styles.some(style => style.position === 'sticky' && ['0', '0px'].includes(style.top))).toBe(true)
})
