import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { setLocale, translate } from './i18n'
import VersionLabel from './VersionLabel'
import { versionLabelText } from './versionLabelText'

afterEach(() => { cleanup(); setLocale('zh-CN') })

const savedAt = '2026-11-18T06:20:45Z'
const minute = (locale: string) => new Date(savedAt).toLocaleString(locale, {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
})

it('shows the business revision and the minute it was saved in Chinese', () => {
  const { container } = render(<VersionLabel revision={3} savedAt={savedAt} />)
  expect(container.textContent).toBe(`第 3 版 · ${minute('zh-CN')}`)
  expect(container.querySelector('time')?.getAttribute('dateTime')).toBe(savedAt)
  expect(container.textContent).not.toContain('45')
  expect(screen.queryByText('当前')).toBeNull()
})

it('marks the current version', () => {
  render(<VersionLabel revision={1} savedAt={savedAt} current />)
  expect(screen.getByText('当前')).toBeTruthy()
})

it('shows the English form and follows a language change', () => {
  setLocale('en')
  const { container } = render(<VersionLabel revision={3} savedAt={savedAt} current />)
  expect(container.textContent).toBe(`Version 3 · ${minute('en')}Current`)
  act(() => setLocale('zh-CN'))
  expect(container.textContent).toBe(`第 3 版 · ${minute('zh-CN')}当前`)
})

it('keeps the revision without inventing a time when the saved time is unreadable', () => {
  const { container } = render(<VersionLabel revision={5} savedAt="not-a-date" />)
  expect(container.textContent).toBe('第 5 版')
  expect(container.querySelector('time')).toBeNull()
})

it('gives the same plain text for option elements in both languages', () => {
  expect(versionLabelText(translate, 'zh-CN', 3, savedAt)).toBe(`第 3 版 · ${minute('zh-CN')}`)
  expect(versionLabelText(translate, 'zh-CN', 5, 'not-a-date')).toBe('第 5 版')
  setLocale('en')
  expect(versionLabelText(translate, 'en', 3, savedAt)).toBe(`Version 3 · ${minute('en')}`)
  expect(versionLabelText(translate, 'en', 5, '')).toBe('Version 5')
})
