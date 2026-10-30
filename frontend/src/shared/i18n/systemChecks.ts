import { translate } from './index'
import { systemCheckPairs } from './systemCheckMessages'

const sources = new Map(systemCheckPairs.flatMap(([zh, en]) => [[zh, zh], [en, zh]] as const))
const automation: Record<string, string> = {
  future_heading_or_order_after_confirmation: '确认后调整标题或顺序',
  future_supported_layout_after_confirmation: '确认后应用支持的版式',
  future_supported_reference_layout_after_confirmation: '确认后应用支持的参考文献版式',
  manual_add_or_review_abstract: '人工补充或审核摘要',
  manual_semantic_restructure: '人工调整摘要语义结构',
  manual_semantic_compression: '人工精简摘要语义结构',
  manual_public_consistency_fix: '人工修正公共一致性',
  journal_display_v1: '固定期刊显示配置v1',
}

/** UI display only; saved checks, research text and user-supplied reasons stay intact. */
export function systemCheckText(value: unknown): string {
  if (typeof value !== 'string') return ''
  const source = sources.get(value) ?? (Object.hasOwn(automation, value) ? automation[value] : undefined)
  if (source) return translate(source)
  const reference = value.match(/^Unmatched body or caption reference: (.+)\. Verify the number and supplied panel; original text retained\.$/)
    ?? value.match(/^正文或图注引用无法对应：(.+)。请核对编号和已提供分面；原文保留。$/)
  if (reference && /^(?:Figure|Fig\.?|Table|图|表)\s*[0-9]+(?:\s*\(?[A-Za-z]\)?)?$/i.test(reference[1])) {
    return translate('正文或图注引用无法对应：{reference}。请核对编号和已提供分面；原文保留。', { reference: reference[1] })
  }
  const parts = value.split('；')
  if (parts.length > 1 && parts.every(part => sources.has(part) || sources.has(part + '。'))) {
    return parts.map(part => translate(sources.get(part) ?? sources.get(part + '。')!)).join(translate('；'))
  }
  return value
}
