import { afterEach, expect, it } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { apiError, setLocale, translate, useI18n } from './i18n'

afterEach(() => { cleanup(); setLocale('zh-CN') })

it('updates mounted UI and document language without changing input values', () => {
  function View() { const { t } = useI18n(); return <><h1>{t('项目中心')}</h1><input defaultValue="我的研究" /></> }
  render(<View />)
  act(() => setLocale('en'))
  expect(screen.getByRole('heading').textContent).toBe('Projects')
  expect(document.documentElement.lang).toBe('en')
  expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('我的研究')
})

it('formats named parameters as literal content', () => {
  setLocale('en')
  expect(translate('打开项目 {name}', { name: '<研究>{count}' })).toBe('Open project <研究>{count}')
})

it('translates stored errors when language changes and ignores server message text', () => {
  const message = apiError({ detail: { code: 'project_not_found', message: 'secret server trace', params: {} } }, '请求失败，请重试。')
  setLocale('en')
  expect(translate(message)).toMatch(/project/i)
  expect(translate(message)).not.toContain('secret')
  setLocale('zh-CN')
  expect(translate(message)).toMatch(/项目/)
})

it('uses a safe fallback for unknown codes and hostile parameter shapes', () => {
  for (const detail of [{ code: 'unknown', message: 'SECRET' }, { code: '__proto__', params: { toString: 'SECRET' } }]) {
    expect(translate(apiError({ detail }, '请求失败，请重试。'))).toBe('请求失败，请重试。')
  }
})

it('validates error parameters by code and falls back when required values are absent', () => {
  setLocale('en')
  const fallback = '请求失败，请重试。'
  const hostile = apiError({ detail: { code: 'numeric_precision', params: { column: 'PRIVATE SECRET', row: 'PRIVATE INPUT' } } }, fallback)
  expect(translate(hostile)).toBe('Request failed. Please try again.')
  expect(translate(apiError({ code: 'file_too_large' }, fallback))).toBe('Request failed. Please try again.')
  expect(translate(apiError({ code: 'numeric_precision', params: { column: 'AB', row: 12 } }, fallback))).toContain('AB12')
})
