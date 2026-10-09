import { afterEach, expect, it } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { apiError, setLocale, translate, useI18n } from './index'

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
it.each([
  ['model_provider_unavailable', '模型服务暂时不可用，请稍后重试。', 'The model service is temporarily unavailable. Please try again later.'],
  ['model_authentication_failed', '模型服务身份验证失败，请联系管理员检查凭据。', 'Model service authentication failed. Contact the administrator to check the credentials.'],
  ['model_permission_denied', '模型服务权限不足，请联系管理员检查权限。', 'Access to the model service was denied. Contact the administrator to check permissions.'],
  ['model_request_rejected', '模型请求或配置不符合要求，请联系管理员核对。', 'The model request or configuration is invalid. Contact the administrator to review it.'],
  ['model_response_invalid', '模型返回的内容未通过验证，请核对输入和配置后重试。', 'The model response failed validation. Review the input and configuration before retrying.'],
])('maps %s to fixed safe text in both languages', (code, zh, en) => {
  const error = apiError({ code, message: 'PRIVATE TRACE', response_id: 'resp-private', params: { secret: 'sk-secret' } }, '请求失败，请重试。')
  expect(translate(error)).toBe(zh)
  setLocale('en'); expect(translate(error)).toBe(en)
})
