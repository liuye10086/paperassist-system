import { translate } from '../../shared/i18n'
import { validCustomerRouteId } from './customerReviewNavigation'

// A return token is only a same-project, same-workspace address. It never carries
// authorization: the page it leads to still reads everything through the server.
export type ReturnLabel = 'paragraph' | 'review-item' | 'review-round' | 'chapter' | 'materials' | 'progress' | 'word'
export type ReturnTarget = { href: string; label: string }

export const returnParamKeys = ['return', 'returnLabel', 'returnSection', 'returnParagraph', 'returnRound', 'returnItem', 'returnChapter'] as const
type ReturnParam = typeof returnParamKeys[number]

const labelParams: Record<ReturnLabel, ReturnParam[]> = {
  paragraph: ['returnSection', 'returnParagraph'],
  'review-item': ['returnRound', 'returnItem'],
  // A review round without a selected opinion, e.g. the returned Word page (B05 task 7).
  'review-round': ['returnRound'],
  chapter: ['returnChapter'],
  materials: [],
  progress: [],
  word: [],
}
const customerSteps = new Set([
  'details', 'upload', 'requirements', 'progress', 'deliveries', 'school', 'materials', 'citations',
  'manuscripts', 'journals', 'word', 'reviews', 'tasks',
])
const maxAddressLength = 2000
const maxNameLength = 200

function isReturnLabel(value: string | null): value is ReturnLabel {
  return value !== null && Object.hasOwn(labelParams, value)
}

function positive(value: string | null) {
  return value !== null && /^[1-9]\d{0,5}$/.test(value) ? Number(value) : null
}

function displayName(value: string | null) {
  const name = value?.trim()
  return name && name.length <= maxNameLength && !/[\p{Cc}\u202a-\u202e\u2066-\u2069]/u.test(name) ? name : null
}

function single(params: URLSearchParams, key: string) {
  const values = params.getAll(key)
  return values.length === 1 ? values[0] : values.length ? undefined : null
}

/** Copy the return token from the current address onto parameters rebuilt by a view. */
export function carryReturnParams(from: URLSearchParams, to: URLSearchParams) {
  for (const key of returnParamKeys) {
    const value = from.get(key)
    if (value !== null) to.set(key, value)
  }
  return to
}

/**
 * Build the parameters to append to a target page address. `current` is the
 * workspace address (`customer-project=…&step=…`) without the leading `#`.
 * Only the location parameters belonging to `label` are kept from `extra`.
 */
export function buildReturn(current: URLSearchParams, label: ReturnLabel, extra: Record<string, string> = {}): Record<string, string> {
  const origin = new URLSearchParams(current)
  for (const key of returnParamKeys) origin.delete(key)
  const result: Record<string, string> = { return: origin.toString(), returnLabel: label }
  for (const key of labelParams[label]) if (Object.hasOwn(extra, key)) result[key] = extra[key]
  return result
}

function locationLabel(label: ReturnLabel, params: URLSearchParams, origin: URLSearchParams) {
  if (label === 'materials') return translate('写作资料')
  if (label === 'progress') return translate('任务进度')
  if (label === 'word') return translate('稿件 Word')
  if (label === 'chapter') {
    const title = displayName(single(params, 'returnChapter') ?? null)
    if (!title) return null
    const wholeSection = origin.get('step') === 'manuscripts' && origin.get('focus') === 'chapters' && !origin.has('chapter')
    return wholeSection ? translate('章节与复核') : title
  }
  if (label === 'paragraph') {
    const section = displayName(single(params, 'returnSection') ?? null)
    const paragraph = positive(single(params, 'returnParagraph') ?? null)
    return section && paragraph ? translate('{section}第 {paragraph} 段', { section, paragraph }) : null
  }
  const round = positive(single(params, 'returnRound') ?? null)
  if (label === 'review-round') return round ? translate('第 {round} 轮', { round }) : null
  const item = positive(single(params, 'returnItem') ?? null)
  return round && item ? translate('第 {round} 轮 · 意见 {item}', { round, item }) : null
}

/** Read a token from the current address; anything unexpected is discarded. */
export function readReturn(params: URLSearchParams, projectId: string): ReturnTarget | null {
  const value = single(params, 'return')
  const label = single(params, 'returnLabel') ?? null
  if (!value || value.length > maxAddressLength || !isReturnLabel(label)) return null
  // Rebuilt below from parsed parameters, so the link can only be a hash in this workspace.
  const origin = new URLSearchParams(value)
  const keys = [...origin.keys()]
  if (keys[0] !== 'customer-project' || keys[1] !== 'step' || new Set(keys).size !== keys.length ||
    keys.slice(2).some(key => key === 'section' || /(^|-)project$/.test(key)) ||
    returnParamKeys.some(key => origin.has(key))) return null
  const project = origin.get('customer-project')
  const step = origin.get('step')
  if (!validCustomerRouteId(project) || project !== projectId || !step || !customerSteps.has(step)) return null
  const name = locationLabel(label, params, origin)
  return name ? { href: '#' + origin.toString(), label: name } : null
}
