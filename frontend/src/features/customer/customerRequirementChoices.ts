import type { Content, DeliveryKind, Intake, SampleRegistration, Version } from '../research-intake/contracts'
import { emptyRequirement } from '../research-intake/state'

export type Choice = {
  id: string
  label: string
  disabledReason?: string
  parent?: { id: string; label: string }
}
export type RequirementInput = { selected: string[]; notes: string; sampleInformation?: SampleRegistration }
type ScopeItem = {
  id: string
  title: string
  delivery_kind: DeliveryKind
  status?: 'planned' | 'completed' | 'pending_review' | 'not_included'
  source?: string
}

function analysisType(
  key: string,
  label: string,
  standardSteps: string[],
  analyses: [string, string][],
  figures: [string, string][],
  customer: { label?: string; disabledReason?: string } = {},
) {
  const type = { id: `customer.type.${key}`, label }
  const customerChoice = { ...type, ...customer }
  const choices = (category: 'analysis' | 'figure', items: [string, string][]): Choice[] => items.map(([name, title]) => ({
    id: `customer.${category}.${key}.${name}`, label: title, parent: type,
  }))
  return { type, customerChoice, standardSteps, analyses: choices('analysis', analyses), figures: choices('figure', figures) }
}

export const analysisTypes = [
  analysisType('single_cell', '单细胞 RNA 测序数据分析', [
    '细胞与基因质控', '表达量标准化与对数转换', '高变基因筛选',
    '降维（PCA、UMAP）', '细胞聚类', '聚类标记基因识别',
  ], [
    ['differential', '差异表达'], ['enrichment', '富集分析'], ['pseudotime', '拟时分析'],
  ], [
    ['umap', 'UMAP 图'], ['heatmap', '热图'],
  ]),
  analysisType('bulk', 'RNA 转录组学分析（Bulk RNA-seq）', [
    '表达矩阵与样本表核对', '样本质控与基因过滤', '表达量预处理',
    '主成分分析（PCA）', '样本聚类', '样本相关性与距离',
  ], [
    ['differential', '差异表达'], ['enrichment', '富集分析'],
  ], [
    ['heatmap', '热图'], ['volcano', '火山图'],
  ], { label: 'RNA 转录组学分析' }),
  analysisType('spatial', '空间转录组分析', [], [
    ['differential', '差异表达'], ['enrichment', '富集分析'], ['spatial_domains', '空间区域识别'],
  ], [
    ['spatial_distribution', '空间分布图'], ['heatmap', '热图'],
  ], { disabledReason: '建设中' }),
]

export const analysisTypeChoices: Choice[] = [
  ...analysisTypes.map(group => group.customerChoice),
  // These types are displayed before they have supported requirement scopes.
  { id: 'customer.type.metabolomics', label: '代谢组学分析', disabledReason: '建设中' },
  { id: 'customer.type.genomics', label: '基因组学分析', disabledReason: '建设中' },
  { id: 'customer.type.multi_omics', label: '多组学联合分析', disabledReason: '建设中' },
  { id: 'customer.type.gut_16s_rrna', label: '肠道菌群16S-rRNA分析', disabledReason: '建设中' },
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
  return { selected: validSelection(selected).map(choice => choice.id), notes: typeof content?.notes === 'string' ? content.notes : '',
    sampleInformation: content?.sample_information as SampleRegistration | undefined }
}

export function toggleRequirementChoice(input: RequirementInput, id: string, checked: boolean): RequirementInput {
  const selected = new Set(input.selected)
  if (checked) selected.add(id)
  else selected.delete(id)
  return { ...input, selected: validSelection(selected).map(choice => choice.id) }
}

export function sameRequirementInput(left: RequirementInput, right: RequirementInput) {
  return left.notes === right.notes && left.selected.length === right.selected.length && left.selected.every((id, index) => id === right.selected[index])
    && sameValue(left.sampleInformation, right.sampleInformation)
}

function sameValue(left: unknown, right: unknown) {
  return left === right || JSON.stringify(left) === JSON.stringify(right)
}

function mergeSampleRows(baseline: SampleRegistration['samples'], local: SampleRegistration['samples'], latest: SampleRegistration['samples']) {
  if (sameValue(local, baseline)) return latest
  const previous = new Map(baseline.map(row => [row.id, row]))
  const merged = new Map(latest.map(row => [row.id, row]))
  const localIds = new Set(local.map(row => row.id))
  // An unfinished draft can contain repeated or empty identifiers. Keep those rows available for correction.
  if (localIds.size !== local.length || local.some(row => !row.id)) return local
  for (const id of previous.keys()) if (!localIds.has(id)) merged.delete(id)
  for (const row of local) {
    const original = previous.get(row.id)
    if (sameValue(row, original)) continue
    const remote = merged.get(row.id)
    if (!original || !remote) {
      merged.set(row.id, row)
      continue
    }
    const result = {...remote}
    for (const field of new Set([...Object.keys(original), ...Object.keys(row)])) {
      if (sameValue(row[field], original[field])) continue
      if (Object.hasOwn(row, field)) result[field] = row[field]
      else delete result[field]
    }
    merged.set(row.id, result)
  }
  return [...merged.values()]
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
  const samples = local.sampleInformation
  const sampleInformation = !samples || sameValue(samples, baseline.sampleInformation) ? latest.sampleInformation : {
    groups: mergeSampleRows(baseline.sampleInformation?.groups ?? [], samples.groups, latest.sampleInformation?.groups ?? []),
    samples: mergeSampleRows(baseline.sampleInformation?.samples ?? [], samples.samples, latest.sampleInformation?.samples ?? []),
  }
  return { selected: validSelection(merged).map(choice => choice.id), notes: local.notes === baseline.notes ? latest.notes : local.notes, sampleInformation }
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
    ...(input.sampleInformation ? { sample_information: input.sampleInformation } : {}),
  }
}
