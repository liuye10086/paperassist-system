import { articleHeading } from '../manuscripts/articleStructure'
import { object, type Evidence, type RevisionLocation } from './revisionTypes'
import type { Item, Location, PlanLocationSpan, Round } from './reviewTypes'

type Translate = (key: string, params?: Record<string, string | number>) => string

export function unchangedInitialPlan(round: Round, item: Item, revision: number) {
  const versions = round.versions?.filter(version => version.revision <= revision)
  return versions?.[0]?.revision === 1 && versions.every(version => version.items.find(entry => entry.id === item.id)?.plan === item.plan)
}

export function customerPlanText(round: Round, item: Item, edit: string, revision: number, locations: (Location & {label: string})[], t: Translate, evidenceNames?: ReadonlyMap<string,string>) {
  if (edit !== item.plan || !unchangedInitialPlan(round,item,revision)) return edit
  return renderPlanReferences(edit,round.generated_plan_locations?.[item.id],locations,t,evidenceNames)
}

export function renderPlanReferences(edit: string, spans: PlanLocationSpan[] | undefined, locations: {kind:string;id:string;label:string}[], t: Translate, evidenceNames?: ReadonlyMap<string,string>) {
  if (!spans?.length) return edit
  // Python offsets count Unicode code points, including non-BMP characters in quoted source text.
  const chars = Array.from(edit)
  const parts: string[] = []
  let end = 0
  for (const span of spans) {
    if (!Number.isInteger(span.start) || !Number.isInteger(span.end) || span.start < end || span.end <= span.start || span.end > chars.length) return edit
    const label = span.kind === 'evidence'
      ? readerName(span.label) || readerName(evidenceNames?.get(span.id)) || t('依据材料')
      : locations.find(location => location.kind === span.kind && location.id === span.id)?.label
        || (span.kind === 'section' && reviewSectionTitle(undefined, span.id, t)) || t('稿件位置')
    parts.push(chars.slice(end, span.start).join(''), label)
    end = span.end
  }
  return parts.join('') + chars.slice(end).join('')
}

function readerName(value: unknown): string {
  if (typeof value !== 'string') return ''
  const name = value.trim()
  const identifier = /^(?:[a-f0-9]{24,64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}(?::\d+)?|[\w-]+(?::[\w-]+)+|(?:[a-z0-9-]+_)+[a-z0-9-]+)$/i
  return identifier.test(name) ? '' : name
}

export function reviewSectionTitle(title: unknown, id: unknown, t: Translate) {
  for (const value of [title, id]) {
    if (typeof value !== 'string' || !value) continue
    const label = articleHeading('research', value, 'zh-CN')
    if (label !== value) return t(label)
    if (value === 'methods') return t('方法')
    if (value === title && value !== id && readerName(value)) return value
  }
  return ''
}

export function customerReviewLocation(location: Partial<RevisionLocation>, t: Translate) {
  const section = reviewSectionTitle(location.section_title, location.section_id, t)
  const kind = { paragraph: '段落', figure: '图', table: '表' }[location.kind ?? '']
  const number = location.paragraph_number ?? location.figure_number ?? location.table_number
  const position = kind ? (number ? t('{kind} {number}', { kind: t(kind), number }) : t(kind)) : ''
  return [section, position, location.removed_from_output ? t('已从修订稿移出') : ''].filter(Boolean).join(' · ') || t('稿件位置')
}

export function customerReturnLocation(value: unknown, chapters: { id: string; title: string }[], t: Translate) {
  const id = typeof value === 'string' ? value : object(value) ? value.chapter_id ?? value.section_id : undefined
  const chapter = chapters.find(c => c.id === id)
  if (chapter) return reviewSectionTitle(chapter.title, chapter.id, t)
  if (typeof value === 'string' && /[\s\u3400-\u9fff]/.test(value)) return readerName(value)
  return reviewSectionTitle(undefined, id, t)
}

export function customerEvidenceLabel(evidence: Evidence, t: Translate, names?: ReadonlyMap<string, string>) {
  const value = object(evidence.content) ? evidence.content : {}
  const file = object(value.file) ? value.file : null
  const name = [names?.get(evidence.id), value.filename, file?.filename, value.label, value.title].map(readerName).find(Boolean)
  const labels: Record<string, string> = { document_version: '文档资料', analysis_run: '统计结果', figure: '图件', analysis_report: '分析报告', collection_report: '分析报告', external_evidence_version: '文献资料' }
  return name || t(labels[evidence.kind] ?? '依据材料')
}

function excerpt(value: unknown, depth = 0): string {
  if (typeof value === 'string') return readerName(value)
  if (depth > 3) return ''
  if (Array.isArray(value)) {
    for (const part of value) {
      const text = excerpt(part, depth + 1)
      if (text) return text
    }
    return ''
  }
  if (!object(value)) return ''
  const textKeys = ['normalized_text', 'text', 'excerpt', 'claim_text', 'caption', 'abstract', 'description']
  for (const key of textKeys) {
    const text = readerName(value[key])
    if (text) return text
  }
  for (const key of ['paragraphs', 'pages', 'sections', 'document', 'content', 'reference']) {
    const text = excerpt(value[key], depth + 1)
    if (text) return text
  }
  return ''
}

export function customerEvidenceExcerpt(evidence: Evidence, t: Translate) {
  const text = excerpt(evidence.content)
  if (text) return text.length > 420 ? text.slice(0, 420) + '…' : text
  if (evidence.kind !== 'analysis_run' || !object(evidence.content)) return ''
  const content = evidence.content
  const values = object(content.overall) ? content.overall : object(content.statistics) ? content.statistics : {}
  const keys = { n: '样本数', mean: '均值', std: '标准差', median: '中位数', min: '最小值', max: '最大值', p_value: 'P 值' }
  const facts = Object.entries(keys).flatMap(([key, label]) => {
    const value = values[key]
    return typeof value === 'number' || typeof value === 'string' && /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(value) ? [t(label) + ' ' + value] : []
  })
  return [readerName(content.numeric_name), ...facts].filter(Boolean).join(' · ')
}

export function customerGroundedAdvice(category: Item['category'] | undefined, t: Translate) {
  const advice: Partial<Record<Item['category'], string>> = {
    statistics: '对照已保存的统计材料核对样本口径和数值。补充结果后，逐处核对相关表述。',
    method: '对照原稿和已有资料核对研究步骤、样本口径和方法说明。',
    structure: '核对段落顺序，按需要拆分或调整，保留原有事实和引用。',
    figure: '对照资料核对图注、研究对象和单位，标明仍待补充的内容。',
    literature: '核对原有引文对陈述的支持，补充引用前先核验来源。',
    experiment: '列出需要补做的实验及所需材料，收到可核验资料后再更新稿件。',
    format: '根据本轮选定的学校模板或期刊指南检查稿件格式。',
  }
  return t(advice[category ?? 'uncategorized'] ?? '根据原稿和已有依据提供具体改文，保留原有事实、引用和局限。')
}

export function customerChangeText(value: unknown, t: Translate, kind?: string, before?: unknown, locations?: RevisionLocation[]) {
  if (kind === 'bind_citation' && Array.isArray(value)) {
    if (!value.length) return t('尚未关联引用')
    const titles = value.map(entry => object(entry) && object(entry.metadata) ? readerName(entry.metadata.title) : '').filter(Boolean)
    return titles.join(' · ') || t('已关联核验引用')
  }
  if (kind === 'reorder_paragraphs' && Array.isArray(value) && Array.isArray(before)) {
    return value.map(id => locations?.find(location => location.id === id)?.text?.slice(0, 120) ??
      t('段落 {number}', { number: before.indexOf(id) + 1 })).join(' → ')
  }
  if (kind === 'remove_figure' && value === null) return t('已从修订稿移出')
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  if (object(value)) return [readerName(value.title), readerName(value.caption) || excerpt(value)].filter(Boolean).join(' · ') ||
    t('请在修订稿中查看此处内容')
  return value == null ? '—' : t('请在修订稿中查看此处内容')
}
