import { afterEach, expect, it } from 'vitest'
import { apiError, setLocale, translate } from './index'

afterEach(() => setLocale('zh-CN'))

it.each([
  ['zh-CN', ['增大图幅', '缩短显示名称']],
  ['en', ['Increase the figure size', 'shorter display names']],
] as const)('explains how to fit complete UpSet labels in %s', (locale, required) => {
  const id = apiError({ detail: { code: 'bio_insights_figure_layout_too_small', message: 'PRIVATE TRACE' } }, 'fallback')
  setLocale(locale)
  const message = translate(id)
  for (const text of required) expect(message).toContain(text)
  expect(message).not.toMatch(/减少集合|fewer sets/)
  expect(message).not.toContain('PRIVATE TRACE')
})
