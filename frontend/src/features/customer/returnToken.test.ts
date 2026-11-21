import { afterEach, describe, expect, it } from 'vitest'
import { setLocale } from '../../shared/i18n'
import { buildReturn, carryReturnParams, readReturn, returnParamKeys } from './returnToken'

afterEach(() => setLocale('zh-CN'))

const progress = new URLSearchParams('customer-project=p1&step=progress')

function token(record: Record<string, string>) {
  return new URLSearchParams(record)
}

describe('buildReturn', () => {
  it('stores the current workspace address without the hash and the location key', () => {
    expect(buildReturn(progress, 'progress')).toEqual({ return: 'customer-project=p1&step=progress', returnLabel: 'progress' })
  })

  it('adds only the location parameters that belong to the label', () => {
    const current = new URLSearchParams('customer-project=p1&step=manuscripts&view=body&manuscript=m1&revision=2')
    expect(buildReturn(current, 'paragraph', { returnSection: '讨论', returnParagraph: '2', view: 'list' })).toEqual({
      return: 'customer-project=p1&step=manuscripts&view=body&manuscript=m1&revision=2',
      returnLabel: 'paragraph', returnSection: '讨论', returnParagraph: '2',
    })
  })

  it('does not nest a token that the current page already carries', () => {
    const current = new URLSearchParams('customer-project=p1&step=upload&mode=supplement&return=customer-project%3Dp1%26step%3Dprogress&returnLabel=progress')
    expect(buildReturn(current, 'materials').return).toBe('customer-project=p1&step=upload&mode=supplement')
  })
})

describe('readReturn', () => {
  it('restores an address in the same project', () => {
    const params = token(buildReturn(progress, 'progress'))
    expect(readReturn(params, 'p1')).toEqual({ href: '#customer-project=p1&step=progress', label: '任务进度' })
  })

  it('round-trips the encoded address through the location hash', () => {
    const current = new URLSearchParams('customer-project=p1&step=reviews&view=plan&round=r1&item=s%3A1')
    const hash = new URLSearchParams({ 'customer-project': 'p1', step: 'upload', ...buildReturn(current, 'review-item', { returnRound: '1', returnItem: '3' }) }).toString()
    const result = readReturn(new URLSearchParams(hash), 'p1')
    expect(result).toEqual({ href: '#customer-project=p1&step=reviews&view=plan&round=r1&item=s%3A1', label: '第 1 轮 · 意见 3' })
  })

  it.each([
    ['paragraph', { returnSection: '讨论', returnParagraph: '2' }, '讨论第 2 段', '讨论 paragraph 2'],
    ['chapter', { returnChapter: '第 3 章' }, '第 3 章', '第 3 章'],
    ['materials', {}, '写作资料', 'Writing materials'],
    ['progress', {}, '任务进度', 'Project progress'],
  ] as const)('labels %s locations in both languages', (label, extra, zh, en) => {
    const params = token(buildReturn(progress, label, extra))
    expect(readReturn(params, 'p1')?.label).toBe(zh)
    setLocale('en')
    expect(readReturn(params, 'p1')?.label).toBe(en)
  })

  it('round-trips a chapter of the thesis materials through the template page address (B04 task 8)', () => {
    const current = new URLSearchParams('customer-project=p1&step=manuscripts&view=materials&chapter=chapter-3')
    const hash = new URLSearchParams({ 'customer-project': 'p1', step: 'school', ...buildReturn(current, 'chapter', { returnChapter: '第 3 章 研究设计', returnSection: '讨论' }) }).toString()
    expect(new URLSearchParams(hash).has('returnSection')).toBe(false)
    expect(readReturn(new URLSearchParams(hash), 'p1')).toEqual({
      href: '#customer-project=p1&step=manuscripts&view=materials&chapter=chapter-3', label: '第 3 章 研究设计',
    })
    expect(readReturn(new URLSearchParams(hash), 'p2')).toBeNull()
  })

  it('labels review items in English', () => {
    setLocale('en')
    expect(readReturn(token(buildReturn(progress, 'review-item', { returnRound: '2', returnItem: '5' })), 'p1')?.label).toBe('Round 2 · Comment 5')
  })

  it('discards a token for another project', () => {
    const params = token({ return: 'customer-project=p2&step=progress', returnLabel: 'progress' })
    expect(readReturn(params, 'p1')).toBeNull()
  })

  it.each([
    ['missing', {}],
    ['empty', { return: '', returnLabel: 'progress' }],
    ['hash prefixed', { return: '#customer-project=p1&step=progress', returnLabel: 'progress' }],
    ['external url', { return: 'https://example.com/#customer-project=p1&step=progress', returnLabel: 'progress' }],
    ['script url', { return: 'javascript:alert(1)//customer-project=p1&step=progress', returnLabel: 'progress' }],
    ['other workspace', { return: 'project=p1&section=reviews', returnLabel: 'progress' }],
    ['analyst workspace', { return: 'analyst-project=p1&step=progress&customer-project=p1', returnLabel: 'progress' }],
    ['unknown step', { return: 'customer-project=p1&step=admin', returnLabel: 'progress' }],
    ['missing step', { return: 'customer-project=p1', returnLabel: 'progress' }],
    ['invalid project id', { return: 'customer-project=p%2F1&step=progress', returnLabel: 'progress' }],
    ['duplicate keys', { return: 'customer-project=p1&step=progress&step=upload', returnLabel: 'progress' }],
    ['nested token', { return: 'customer-project=p1&step=progress&return=customer-project%3Dp1%26step%3Ddetails', returnLabel: 'progress' }],
    ['unknown label', { return: 'customer-project=p1&step=progress', returnLabel: 'admin' }],
    ['missing label', { return: 'customer-project=p1&step=progress' }],
    ['paragraph without number', { return: 'customer-project=p1&step=manuscripts', returnLabel: 'paragraph', returnSection: '讨论' }],
    ['paragraph with bad number', { return: 'customer-project=p1&step=manuscripts', returnLabel: 'paragraph', returnSection: '讨论', returnParagraph: '0' }],
    ['review item without round', { return: 'customer-project=p1&step=reviews', returnLabel: 'review-item', returnItem: '1' }],
    ['chapter without name', { return: 'customer-project=p1&step=manuscripts', returnLabel: 'chapter', returnChapter: ' ' }],
    ['chapter with control text', { return: 'customer-project=p1&step=manuscripts', returnLabel: 'chapter', returnChapter: 'a\u202eb' }],
  ])('discards a %s token', (_name, record) => {
    expect(readReturn(token(record as Record<string, string>), 'p1')).toBeNull()
  })

  it('discards duplicated token parameters in the current address', () => {
    const params = new URLSearchParams('return=customer-project%3Dp1%26step%3Dprogress&return=customer-project%3Dp1%26step%3Ddetails&returnLabel=progress')
    expect(readReturn(params, 'p1')).toBeNull()
  })
})

describe('carryReturnParams', () => {
  it('copies every token parameter to the rebuilt parameters and keeps the rest', () => {
    const from = new URLSearchParams({ view: 'items', round: 'r1', ...buildReturn(progress, 'paragraph', { returnSection: '讨论', returnParagraph: '2' }), reviewReturn: 'x1' })
    const to = carryReturnParams(from, new URLSearchParams('view=plan&round=r1&item=i1'))
    expect(to.get('view')).toBe('plan')
    expect(to.get('item')).toBe('i1')
    expect(to.get('reviewReturn')).toBeNull()
    for (const key of ['return', 'returnLabel', 'returnSection', 'returnParagraph']) expect(to.get(key)).toBe(from.get(key))
    expect(returnParamKeys).toEqual(['return', 'returnLabel', 'returnSection', 'returnParagraph', 'returnRound', 'returnItem', 'returnChapter'])
  })

  it('returns the target unchanged when there is no token', () => {
    const to = new URLSearchParams('view=list')
    expect(carryReturnParams(new URLSearchParams('view=items'), to).toString()).toBe('view=list')
  })
})

describe('review-round tokens (B05 task 7)', () => {
  it('keeps only the round and labels it in both languages', () => {
    const current = new URLSearchParams('customer-project=p1&step=reviews&view=continuation&round=r1')
    const record = buildReturn(current, 'review-round', { returnRound: '3', returnItem: '2' })
    expect(record).toEqual({ return: current.toString(), returnLabel: 'review-round', returnRound: '3' })
    expect(readReturn(token(record), 'p1')).toEqual({ href: '#' + current.toString(), label: '第 3 轮' })
    setLocale('en')
    expect(readReturn(token(record), 'p1')?.label).toBe('Round 3')
  })

  it.each([
    ['missing round', {}],
    ['zero round', { returnRound: '0' }],
    ['negative round', { returnRound: '-1' }],
    ['text round', { returnRound: 'one' }],
    ['repeated round', { returnRound: ['1', '2'] }],
  ] as const)('discards a token with a %s', (_name, extra) => {
    const params = new URLSearchParams({ return: 'customer-project=p1&step=reviews', returnLabel: 'review-round' })
    for (const [key, value] of Object.entries(extra)) for (const item of [value].flat()) params.append(key, item)
    expect(readReturn(params, 'p1')).toBeNull()
  })
})
