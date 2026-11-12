import type { Content, DeliveryKind, Intake, Version } from '../research-intake/contracts'
import { emptyRequirement } from '../research-intake/state'

export type Choice = { id: string; label: string; parent?: { id: string; label: string } }
export type RequirementInput = { selected: string[]; notes: string }
type ScopeItem = {
  id: string
  title: string
  delivery_kind: DeliveryKind
  status?: 'planned' | 'completed' | 'pending_review' | 'not_included'
  source?: string
}

function analysisType(key: string, label: string, analyses: [string, string][], figures: [string, string][]) {
  const type = { id: `customer.type.${key}`, label }
  const choices = (category: 'analysis' | 'figure', items: [string, string][]): Choice[] => items.map(([name, title]) => ({
    id: `customer.${category}.${key}.${name}`, label: title, parent: type,
  }))
  return { type, analyses: choices('analysis', analyses), figures: choices('figure', figures) }
}

export const analysisTypes = [
  analysisType('single_cell', '单细胞 RNA 测序数据分析', [
    ['differential', '差异表达'], ['enrichment', '富集分析'], ['pseudotime', '拟时分析'],
  ], [
    ['umap', 'UMAP 图'], ['heatmap', '热图'],
  ]),
  analysisType('bulk', 'RNA 转录组学分析（Bulk RNA-seq）', [
    ['differential', '差异表达'], ['enrichment', '富集分析'],
  ], [
    ['heatmap', '热图'], ['volcano', '火山图'],
  ]),
  analysisType('spatial', '空间转录组分析', [
    ['differential', '差异表达'], ['enrichment', '富集分析'], ['spatial_domains', '空间区域识别'],
  ], [
    ['spatial_distribution', '空间分布图'], ['heatmap', '热图'],
  ]),
]

export const deliveryChoices: Choice[] = [
  { id: 'customer.delivery.word', label: 'Word 报告' },
  { id: 'customer.delivery.package', label: '交付包' },
]

const allChoices: Choice[] = [...analysisTypes.flatMap(group => [group.type, ...group.analyses, ...group.figures]), ...deliveryChoices]
const managedIds = new Set(allChoices.map(choice => choice.id))
const items = (content?: Content) => (content?.scope_items ?? []) as ScopeItem[]

function validSelection(selected: Set<string>) {
  return allChoices.filter(choice => selected.has(choice.id) && (!choice.parent || selected.has(choice.parent.id)))
}

export function readRequirementInput(version: Version | null): RequirementInput {
  const content = version?.content
  const selected = new Set(items(content).filter(item => item.status !== 'not_included').map(item => item.id))
  return { selected: validSelection(selected).map(choice => choice.id), notes: typeof content?.notes === 'string' ? content.notes : '' }
}

export function toggleRequirementChoice(input: RequirementInput, id: string, checked: boolean): RequirementInput {
  const selected = new Set(input.selected)
  if (checked) selected.add(id)
  else selected.delete(id)
  return { ...input, selected: validSelection(selected).map(choice => choice.id) }
}

export function sameRequirementInput(left: RequirementInput, right: RequirementInput) {
  return left.notes === right.notes && left.selected.length === right.selected.length && left.selected.every((id, index) => id === right.selected[index])
}

export function mergeRequirementInput(baseline: RequirementInput, local: RequirementInput, latest: RequirementInput): RequirementInput {
  const original = new Set(baseline.selected)
  const edited = new Set(local.selected)
  const merged = new Set(latest.selected)
  for (const { id, parent } of allChoices) {
    if (original.has(id) === edited.has(id)) continue
    if (edited.has(id)) {
      merged.add(id)
      if (parent) merged.add(parent.id)
    } else merged.delete(id)
  }
  return { selected: validSelection(merged).map(choice => choice.id), notes: local.notes === baseline.notes ? latest.notes : local.notes }
}

export function buildRequirementContent(intake: Intake, input: RequirementInput, operation: Version['operation'], t: (label: string) => string): Content {
  const registeredServices = intake.deliveries.filter(delivery => delivery.active).map(delivery => delivery.kind)
  const base = intake.current_requirement?.content ?? { ...emptyRequirement(), services: registeredServices }
  const services = Array.isArray(base.services) ? base.services : registeredServices
  const previousItems = items(base)
  const previousById = new Map(previousItems.map(item => [item.id, item]))
  const requestedItems = validSelection(new Set(input.selected)).map((choice): ScopeItem => {
    const previous = previousById.get(choice.id)
    if (previous && previous.status !== 'not_included') return previous
    const title = choice.parent ? `${t(choice.parent.label)} · ${t(choice.label)}` : t(choice.label)
    return { id: choice.id, title, delivery_kind: 'analysis', status: 'planned', source: '客户需求选择' }
  })
  return {
    ...base,
    services: (operation === 'confirm' || requestedItems.length > 0) && !services.includes('analysis')
      ? [...services, 'analysis'] : services,
    scope_items: [...previousItems.filter(item => !managedIds.has(item.id)), ...requestedItems],
    notes: input.notes,
  }
}
