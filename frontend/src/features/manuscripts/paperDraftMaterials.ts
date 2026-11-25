import {plannedThesisInput, supplementaryInput} from './paperPlan'
import {defaultPaperFiles} from './preparePaperDraft'
import {sourceKey, type Candidates, type ManuscriptInput, type SourceSelection} from './manuscriptTypes'
import {isSchoolWritingPurpose, type SchoolPurpose, type ThesisInput} from './thesisTypes'
import type {Chapter} from '../school-templates/contracts'

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
  封面: 'manual', cover: 'manual', 扉页:'manual', 题名页:'manual', 'title page':'manual',
  图目录:'manual', 表目录:'manual', 图表目录:'manual', 插图目录:'manual', 附表目录:'manual',
  'list of figures':'manual', 'list of tables':'manual', 缩略语表:'manual', 'list of abbreviations':'manual',
  原创性声明:'manual', 独创性声明:'manual', 学位论文原创性声明:'manual', 学位论文使用授权声明:'manual',
  学位论文使用授权书:'manual', 'declaration of originality':'manual', 'copyright declaration':'manual',
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

const contentsTitles = new Set(['目录','目次','contents','table of contents'])
function chapterTitle(title:string) {
  return title.normalize('NFKC').toLowerCase().trim()
    .replace(/^(?:第[一二三四五六七八九十百零\d]+[章节]|chapter\s+(?:\d+|[ivxlcdm]+)\b|\d+(?:\.\d+)*(?=[\s.、:\p{Script=Han}]))[\s.、:：-]*/iu, '')
    .replace(/(?<=\p{Script=Han})\s+(?=\p{Script=Han})/gu, '')
    .replace(/\s*\((?:根据实际情况填写|按实际情况填写)\)$/, '').trim()
}

export function inferSchoolChapterPurposes(chapters: readonly Chapter[], {saved, protectedPurposes, choose, protectOutline = false}: {
  saved?: ReadonlyMap<string, SchoolPurpose>
  protectedPurposes?: Readonly<Partial<Record<string, SchoolPurpose>>>
  choose?: (chapterId: string) => SchoolPurpose | undefined
  protectOutline?: boolean
} = {}) {
  const ancestors: {level: number; purpose?: SchoolPurpose; protected: boolean}[] = []
  return chapters.map(({id, title, level}) => {
    const name = chapterTitle(title)
    while (ancestors.length && ancestors[ancestors.length - 1].level >= level) ancestors.pop()
    const parent = ancestors.at(-1)
    const inherited = parent?.purpose === 'references' ? 'manual' : parent?.purpose
    const contents = contentsTitles.has(name)
    const named = Object.hasOwn(chapterNames,name) ? chapterNames[name] : undefined
    // The editor protects template-owned headings. Writing keeps historical saved purposes.
    const namedProtection = named && !isSchoolWritingPurpose(named) ? named : undefined
    const inheritedProtection = parent?.protected ? inherited : undefined
    const outlinePurpose = protectOutline ? namedProtection ?? inheritedProtection : undefined
    const locked = contents ? 'manual' : protectedPurposes?.[id] ?? outlinePurpose
    const fixed = locked ?? saved?.get(id) ?? named
    const needsChoice = !fixed && !parent
    const purpose = fixed ?? (needsChoice ? choose?.(id) : inherited)
    const protectedChapter = locked !== undefined
    ancestors.push({level, purpose, protected:protectedChapter})
    return {name, purpose, needsChoice, protected:protectedChapter}
  })
}

function schoolInput(candidates: Candidates, base: ManuscriptInput, choices: MaterialChoices) {
  const school = candidates.thesis
  if (!school?.ready || !school.confirmation_id) return
  const plan = candidates.paper_plan ?? {kind: 'thesis' as const, title: '', keywords: [], materials: [], sections: []}
  const planned = plannedThesisInput(plan, school, base.thesis)
  if (!planned) return
  const questions = new Set<string>()
  const defaults = inferSchoolChapterPurposes(school.chapters, {
    saved:new Map(planned.chapter_mappings.filter(mapping => mapping.purpose).map(mapping => [mapping.chapter_id, mapping.purpose])),
    protectedPurposes:school.protected_chapter_purposes,
    choose:id => choices.chapterPurposes[school.confirmation_id + '/' + id],
  })
  const titles = defaults.map(chapter => chapter.name)
  const pairedAbstracts = titles.includes('abstract') && titles.some(t => ['中文摘要','摘要','内容摘要'].includes(t))
  const mappings:ThesisInput['chapter_mappings'] = planned.chapter_mappings.map((mapping, index) => {
    const {name:title, purpose:inferred, needsChoice} = defaults[index]
    if (needsChoice) questions.add(mapping.chapter_id)
    const purpose = inferred ?? mapping.purpose
    const previous = base.thesis?.confirmation_id === school.confirmation_id &&
      base.thesis.chapter_mappings.find(item => item.chapter_id === mapping.chapter_id)
    const abstractLanguage = title === '英文摘要' || title === 'english abstract' || pairedAbstracts && title === 'abstract' ? 'en' :
      ['中文摘要','chinese abstract'].includes(title) || pairedAbstracts && ['摘要','内容摘要'].includes(title) ? 'zh-CN' : null
    const language = !previous && purpose === 'abstract' && abstractLanguage || mapping.output_language
    return {...mapping, purpose, output_language:language, result_group_ids:purpose === 'results' ? mapping.result_group_ids : []}
  })
  return {input:{...planned, chapter_mappings:mappings}, questions}
}

export function paperDraftMaterials(candidates: Candidates, base: ManuscriptInput, choices: MaterialChoices, revision: number, review = false) {
  const plan = candidates.paper_plan
  const excluded = new Set([...(candidates.thesis?.template_source_file_ids ?? []), ...(plan?.materials.map(m => m.selection.file_id) ?? [])])
  const panelFiles = new Set(plan?.thesis_figures?.flatMap(figure => figure.panel_file_ids ?? []))
  const repeatedImages = base.sources.filter(s => s.kind === 'original' && s.role === 'image_observation' && panelFiles.has(s.file_id))
  const carried = supplementaryInput(base, new Set([...excluded, ...repeatedImages.map(source => source.file_id)]), id => new Set([id]))
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
  const repeatedImageIds = new Set(repeatedImages.map(source => source.id))
  const manual = {...carried, sources: restored, figure_notes: carried.figure_notes.filter(note => !repeatedImageIds.has(note.figure_id)),
    method_source_ids: Object.fromEntries(Object.entries(carried.method_source_ids).map(([field, ids]) => [field, ids?.map(upgrade)]))}
  const already = new Set(manual.sources.map(source => source.file_id))
  const options = defaultPaperFiles(candidates.items, new Set([...excluded, ...already, ...panelFiles]))
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
