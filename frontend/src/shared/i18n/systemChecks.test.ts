import { afterEach, expect, it } from 'vitest'
import { setLocale } from './index'
import { systemCheckText } from './systemChecks'

afterEach(() => setLocale('zh-CN'))
it('displays fixed engineering checks in the active language without rewriting the saved value', () => {
  const saved = { message: 'Reference numbering is not contiguous.' }
  expect(systemCheckText(saved.message)).toBe('参考文献编号不连续。')
  setLocale('en')
  expect(systemCheckText(saved.message)).toBe(saved.message)
  expect(systemCheckText('任务成功仅表示只读检查完成，不表示全部投稿要求合规。')).toBe('Task success means the read-only check finished; it does not establish compliance with every submission requirement.')
  setLocale('zh-CN')
  expect(systemCheckText(saved.message)).toBe('参考文献编号不连续。')
  expect(saved.message).toBe('Reference numbering is not contiguous.')
})
it('preserves user prose and original reason text outside the finite system-message contract', () => {
  for (const locale of ['zh-CN', 'en'] as const) {
    setLocale(locale)
    expect(systemCheckText('My study uses 原始值 alpha=3; 请保留。')).toBe('My study uses 原始值 alpha=3; 请保留。')
    expect(systemCheckText('normal')).toBe('normal')
    expect(systemCheckText(null)).toBe('')
    expect(systemCheckText({ message: 'untrusted object' })).toBe('')
  }
})
it('changes finite engineering labels while preserving the supplied reference token', () => {
  expect(systemCheckText('Unmatched body or caption reference: Figure 9B. Verify the number and supplied panel; original text retained.')).toBe('正文或图注引用无法对应：Figure 9B。请核对编号和已提供分面；原文保留。')
  setLocale('en')
  expect(systemCheckText('正文或图注引用无法对应：图 9B。请核对编号和已提供分面；原文保留。')).toBe('Unmatched body or caption reference: 图 9B. Verify the number and supplied panel; original text retained.')
  expect(systemCheckText('future_heading_or_order_after_confirmation')).toBe('Heading or order changes after confirmation')
})
