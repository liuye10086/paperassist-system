import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ExternalSendReview from './ExternalSendReview'
import { setLocale } from '../i18n'
import type { ArtifactDisclosure } from '../api/artifactDisclosure'

const disclosure: ArtifactDisclosure = { version: 1, provider: 'openai', task_type: 'explanation', source_digest: 'secret-source', has_saved_result: false,
  summary: { valid_count: 8, excluded_count: 1, group_count: 2 }, labels: [{ key: 'numeric_name', value: '历史结果' }, { key: 'unit', value: '' }, { key: 'group_name', value: '原分组' }, { key: 'group:0', value: 'A' }, { key: 'group:1', value: 'B' }, { key: 'figure_title', value: '图 1' }] }
afterEach(() => { cleanup(); setLocale('zh-CN') })

it('uses readable bilingual labels while leaving supplied and edited text unchanged', () => {
  const onConfirm = vi.fn(); render(<ExternalSendReview disclosure={disclosure} disabled={false} onConfirm={onConfirm} onCancel={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox', { name: '分组 1 名称' }), { target: { value: '公开分组' } })
  act(() => setLocale('en'))
  expect((screen.getByRole('textbox', { name: 'Numeric label' }) as HTMLInputElement).value).toBe('历史结果')
  expect((screen.getByRole('textbox', { name: 'Group 1 label' }) as HTMLInputElement).value).toBe('公开分组')
  expect(screen.getByRole('textbox', { name: 'Grouping field label' })).toBeTruthy()
  expect(screen.getByRole('textbox', { name: 'Chart title' })).toBeTruthy()
  expect(screen.queryByText(/secret-source|numeric_name|group:0/)).toBeNull()
  expect(screen.getByRole('link', { name: 'View data policy' }).getAttribute('href')).toBe('https://developers.openai.com/api/docs/guides/your-data')
  fireEvent.submit(screen.getByRole('form', { name: 'Review before sending' }))
  expect(onConfirm).toHaveBeenCalledWith({ version: 1, confirmed: true, source_digest: 'secret-source', labels: { numeric_name: '历史结果', unit: '', group_name: '原分组', 'group:0': '公开分组', 'group:1': 'B', figure_title: '图 1' } })
})

it.each(['', ' ', 'x'.repeat(161), 'text\u0007', 'text\u200b', 'text\u202e', 'text\ud800'])('blocks invalid required labels (%j) without sending', value => {
  const onConfirm = vi.fn(); render(<ExternalSendReview disclosure={disclosure} disabled={false} onConfirm={onConfirm} onCancel={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox', { name: '数值名称' }), { target: { value } })
  expect((screen.getByRole('button', { name: '确认发送并生成' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.submit(screen.getByRole('form', { name: '发送前检查' })); expect(onConfirm).not.toHaveBeenCalled()
})

it('blocks duplicate group names and permits an empty unit', () => {
  const onConfirm = vi.fn(); render(<ExternalSendReview disclosure={disclosure} disabled={false} onConfirm={onConfirm} onCancel={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox', { name: '分组 2 名称' }), { target: { value: ' A ' } })
  expect((screen.getByRole('button', { name: '确认发送并生成' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByRole('textbox', { name: '分组 2 名称' }), { target: { value: '新分组' } })
  fireEvent.submit(screen.getByRole('form', { name: '发送前检查' })); expect(onConfirm).toHaveBeenCalledOnce()
})

it('keeps cancel usable when sending is disabled', () => {
  const onCancel = vi.fn(); const onConfirm = vi.fn()
  render(<ExternalSendReview disclosure={disclosure} disabled onConfirm={onConfirm} onCancel={onCancel} />)
  fireEvent.submit(screen.getByRole('form', { name: '发送前检查' })); expect(onConfirm).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '取消' })); expect(onCancel).toHaveBeenCalledOnce()
})
