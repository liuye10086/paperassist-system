import {plannedThesisInput, supplementaryInput} from './paperPlan'
import {defaultPaperFiles} from './preparePaperDraft'
import {sourceKey, type Candidates, type ManuscriptInput, type SourceSelection} from './manuscriptTypes'
import type {SchoolPurpose, ThesisInput} from './thesisTypes'

export type MaterialChoices = {
  omittedFiles: string[]; resultText?: string; resultSource?: string
  chapterPurposes: Record<string, SchoolPurpose>
}
const chapterNames: Record<string, SchoolPurpose> = {
  摘要: 'abstract', 中文摘要: 'abstract', 英文摘要: 'abstract', abstract: 'abstract',
  引言: 'introduction', 绪论: 'introduction', introduction: 'introduction',
  材料与方法: 'materials_and_methods', 研究方法: 'materials_and_methods', 'materials and methods': 'materials_and_methods',
  结果: 'results', 研究结果: 'results', results: 'results', 讨论: 'discussion', discussion: 'discussion',
  结论: 'conclusion', conclusion: 'conclusion', 参考文献: 'references', references: 'references',
  致谢: 'acknowledgements', acknowledgements: 'acknowledgements',
  acknowledgments: 'acknowledgements', 研究背景: 'introduction', background: 'introduction',
  实验方法: 'materials_and_methods', 方法: 'materials_and_methods', methods: 'materials_and_methods',
  实验结果: 'results', conclusions: 'conclusion', 文献目录: 'references', bibliography: 'references',
  目录: 'manual', 'table of contents': 'manual', 封面: 'manual', cover: 'manual',
  原创性声明: 'manual', 学位论文原创性声明: 'manual', 学位论文使用授权声明: 'manual',
  'english abstract':'abstract','chinese abstract':'abstract', 内容摘要:'abstract',
  前言:'introduction', 文献综述:'introduction', 研究现状:'introduction', 国内外研究现状:'introduction',
  'literature review':'introduction', 'related work':'introduction',
  研究设计:'materials_and_methods', 技术路线:'materials_and_methods', 实验设计:'materials_and_methods',
  对象与方法:'materials_and_methods', 研究对象与方法:'materials_and_methods', 'study design':'materials_and_methods',
  研究过程与分析:'results', 结果与分析:'results', 研究结果与分析:'results', 研究结果与讨论:'results',
  结果分析:'results', 'results and analysis':'results',
  研究讨论:'discussion', 研究结论:'conclusion', 研究建议:'conclusion', 结论与展望:'conclusion',
  研究结论与建议:'conclusion', 结论与建议:'conclusion', 'conclusions and recommendations':'conclusion',
  附录:'manual', appendix:'manual', appendices:'manual', 个人简历:'manual', 声明:'manual',
}

const contentsTitles = new Set(['目录','contents','table of contents'])
function chapterTitle(title:string) {
  return title.normalize('NFKC').toLowerCase().trim()
    .replace(/^(?:第[一二三四五六七八九十百零\d]+[章节]|chapter\s+(?:\d+|[ivxlcdm]+)\b|\d+(?:\.\d+)*(?=[\s.、:\p{Script=Han}]))[\s.、:：-]*/iu, '')
    .replace(/(?<=\p{Script=Han})\s+(?=\p{Script=Han})/gu, '')
    .replace(/\s*\((?:根据实际情况填写|按实际情况填写)\)$/, '').trim()
}

export const isSchoolContentsTitle = (title:string) => contentsTitles.has(chapterTitle(title))

function schoolInput(candidates: Candidates, base: ManuscriptInput, choices: MaterialChoices) {
  const school = candidates.thesis
  if (!school?.ready || !school.confirmation_id) return
  const plan = candidates.paper_plan ?? {kind: 'thesis' as const, title: '', keywords: [], materials: [], sections: []}
  const planned = plannedThesisInput(plan, school, base.thesis)
  if (!planned) return
  const ancestors: {level:number; purpose:SchoolPurpose}[] = []
  const questions = new Set<string>()
  const titles = school.chapters.map(chapter => chapterTitle(chapter.title))
  const pairedAbstracts = titles.includes('abstract') && titles.some(t => ['中文摘要','摘要','内容摘要'].includes(t))
  const mappings:ThesisInput['chapter_mappings'] = planned.chapter_mappings.map((mapping, index) => {
    const chapter = school.chapters[index]
    const title = titles[index]
    while (ancestors.length && ancestors[ancestors.length - 1].level >= chapter.level) ancestors.pop()
    const parent = ancestors.at(-1)
    const key = school.confirmation_id + '/' + mapping.chapter_id
    const fixed = contentsTitles.has(title) ? 'manual' : mapping.purpose || (Object.hasOwn(chapterNames,title) && chapterNames[title])
    const inherited = parent?.purpose === 'references' ? 'manual' : parent?.purpose
    const needsChoice = !fixed && !parent
    if (needsChoice) questions.add(mapping.chapter_id)
    const purpose = fixed || (needsChoice && choices.chapterPurposes[key]) || inherited || mapping.purpose
    ancestors.push({level:chapter.level, purpose})
    const previous = base.thesis?.confirmation_id === school.confirmation_id &&
      base.thesis.chapter_mappings.find(item => item.chapter_id === mapping.chapter_id)
    const abstractLanguage = title === '英文摘要' || title === 'english abstract' || pairedAbstracts && title === 'abstract' ? 'en' :
      ['中文摘要','chinese abstract'].includes(title) || pairedAbstracts && ['摘要','内容摘要'].includes(title) ? 'zh-CN' : null
    const language = !previous && purpose === 'abstract' && abstractLanguage || mapping.output_language
    return {...mapping, purpose, output_language:language}
  })
  return {input:{...planned, chapter_mappings:mappings}, questions}
}

export function paperDraftMaterials(candidates: Candidates, base: ManuscriptInput, choices: MaterialChoices, revision: number, review = false) {
  const plan = candidates.paper_plan
  const excluded = new Set([...(candidates.thesis?.template_source_file_ids ?? []), ...(plan?.materials.map(m => m.selection.file_id) ?? [])])
  const carried = supplementaryInput(base, excluded, id => new Set([id]))
  const readable = new Map(defaultPaperFiles(candidates.items, excluded).map(item => [item.file_id, item]))
  // A Word or workbook can finish parsing after the user saved its original as a source.
  const upgrades = new Map<string, string>()
  const restored = carried.sources.map(s => {
    const copy = readable.get(s.file_id)
    if (s.kind !== 'original' || !copy || s.role === 'image_observation' || copy.kind === 'original' || !copy.allowed_roles.includes(s.role)) return s
    upgrades.set(s.id, copy.id)
    return {...s, kind: copy.kind, id: copy.id}
  })
  const upgrade = (id: string) => upgrades.get(id) ?? id
  const manual = {...carried, sources: restored,
    method_source_ids: Object.fromEntries(Object.entries(carried.method_source_ids).map(([field, ids]) => [field, ids?.map(upgrade)]))}
  const already = new Set(manual.sources.map(source => source.file_id))
  const options = defaultPaperFiles(candidates.items, new Set([...excluded, ...already]))
    .filter(s => !review || s.kind !== 'original' || !s.allowed_roles.includes('image_observation'))
  const added: SourceSelection[] = options.filter(source => !choices.omittedFiles.includes(source.file_id)).map(source => ({
    kind: source.kind, id: source.id, file_id: source.file_id,
    role: source.kind === 'original' && source.allowed_roles.includes('image_observation') ? 'image_observation' :
      source.allowed_roles.includes('methods') ? 'methods' : source.allowed_roles[0],
  }))
  const selected = [...manual.sources, ...added]
  const resultSources = candidates.items.filter(item => item.allowed_roles.includes('user_results') && selected.some(s => sourceKey(s) === sourceKey(item)))
  const resultSource = choices.resultSource ? upgrade(choices.resultSource) : ''
  const sources = selected.map(s => s.id === resultSource ? {...s, role: 'user_results' as const} : s)
  const input: ManuscriptInput = {...manual, title: plan?.title || base.title, sources, expected_revision: revision}
  delete input.paper_plan_token
  if (plan) input.paper_plan_token = plan.token
  const thesis = schoolInput(candidates, base, choices)
  if (thesis) input.thesis = thesis.input
  else if (candidates.project_type === 'thesis') delete input.thesis
  const text = (choices.resultText ?? base.reported_result?.text ?? '').trim()
  const sourceIds = (choices.resultSource ? [choices.resultSource] : base.reported_result?.source_ids ?? []).map(upgrade)
    .filter(id => sources.some(s => s.id === id && s.role === 'user_results'))
  if (text && sourceIds.length) input.reported_result = {text, source_ids: sourceIds}
  else delete input.reported_result
  if (resultSource) {
    input.method_source_ids = Object.fromEntries(Object.entries(input.method_source_ids).map(([field, ids]) => [field, ids?.filter(id => id !== resultSource)]))
  }
  return {input, options, resultSources, chapterQuestions:thesis?.questions ?? new Set<string>()}
}
