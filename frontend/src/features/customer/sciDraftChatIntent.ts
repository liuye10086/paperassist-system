import type {Section} from './useSciDraftRead'

export type DraftChatKind = 'revision' | 'advice'
type ChatSection = Pick<Section, 'id' | 'heading' | 'purpose' | 'output_language'>

const sectionNames: Record<string, string[]> = {
  title: ['标题', '论文题目', 'title'],
  abstract: ['摘要', 'abstract'],
  introduction: ['引言', '前言', '绪论', 'introduction'],
  materials_and_methods: ['材料与方法', '研究方法', 'methods', 'materials and methods'],
  results: ['结果', 'results'],
  discussion: ['讨论', 'discussion'],
  conclusion: ['结论', 'conclusion', 'conclusions'],
  references: ['参考文献', 'references', 'bibliography'],
}
const abstractNames = {'zh-CN':['中文摘要', 'Chinese abstract', 'abstract in Chinese'],
  en:['英文摘要', 'English abstract', 'abstract in English']}

const opensWithEdit = /^(?:(?:请(?:你)?|麻烦(?:你)?|帮我|可以|能不能|能否)\s*)*(?:把|重写|改写|修改|润色|精简|扩写|缩短|调整|删除|改一下|改改)|^(?:(?:please|can you|could you)\s+)*(?:rewrite|revise|edit|shorten|expand|polish)\b/i
const adviceQuestion = /有(?:什么|没有)(?:问题|建议|不足)|哪里(?:不妥|有问题|可以改进|需要修改)|(?:怎么|如何)(?:改|修改|优化|写|重写|完善)|写得(?:怎么样|好不好)|为什么|(?:给|提|说).{0,6}(?:建议|意见)|(?:指出|找出|看看|看一下).{0,16}(?:问题|不足|这段|本节)|(?:评价|点评)(?:一下)?(?:这段|本节|这一章)|\b(?:what|why|how|suggest|feedback|recommend|advice|critique)\b/i
const followUp = /^(?:那(?:就)?|那\s*|请\s*)?(?:再|接着|继续|还是|同一|刚才|上[一轮次]|按(?:照)?(?:这个|这些|刚才|你说的|上次)|就这样改)|^(?:again\b|continue\b|(?:make it|a bit|even)\b|same (?:section|chapter)\b|apply (?:that|these|those|your)\b)/i

function mentions(message: string, label: string) {
  const name = label.trim().toLowerCase()
  if (!name) return false
  if (/\p{Script=Han}/u.test(name)) return message.includes(name)
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`\\b${escaped}\\b`, 'i').test(message)
}

function namedSchoolChapters(message: string, sections: ChatSection[], active?: string) {
  const selected = new Set<string>()
  const namedPurposes = new Set<string>()
  const preferred = new Map<string, string>()
  for (const {id, heading, purpose, output_language} of sections) {
    const aliases = sectionNames[purpose ?? ''] ?? []
    const label = heading.trim().toLowerCase()
    const languages = purpose === 'abstract' && output_language ? abstractNames[output_language] : []
    if ((!aliases.includes(label) && mentions(message, label)) || languages.some(name => mentions(message, name))) {
      selected.add(id)
      if (purpose) namedPurposes.add(purpose)
    } else if (purpose && aliases.some(name => mentions(message, name)) && (!preferred.has(purpose) || id === active)) {
      preferred.set(purpose, id)
    }
  }
  for (const [purpose, id] of preferred) if (!namedPurposes.has(purpose)) selected.add(id)
  return sections.filter(section => selected.has(section.id))
}

export function resolveDraftChat(message: string, sections: ChatSection[],
  scope: {selected?: string[]; active?: string; previous?: string[]; fromFile?: boolean; thesis?: boolean}) {
  const normalized = message.trim().normalize('NFKC').toLowerCase()
  const edit = opensWithEdit.test(normalized)
  const kind: DraftChatKind = !scope.fromFile && !edit && adviceQuestion.test(normalized) ? 'advice' : 'revision'
  const inherited = !scope.fromFile && followUp.test(normalized)
  if (scope.selected) return {kind, sectionIds:scope.selected, inherited:false}
  const named = scope.thesis ? namedSchoolChapters(normalized, sections, scope.active)
    : sections.filter(section => [section.heading, ...(sectionNames[section.id] ?? [])].some(name => mentions(normalized, name)))
  if (named.length) return {kind, sectionIds:named.map(section => section.id), inherited:false}
  // An explicitly named missing chapter must not turn into an edit of the one on screen.
  if (edit && Object.values(sectionNames).flat().some(name => mentions(normalized, name))) {
    return {kind, sectionIds:[], inherited:false}
  }
  const previous = inherited ? sections.filter(section => scope.previous?.includes(section.id)).map(section => section.id) : []
  return {kind, sectionIds:previous.length ? previous : scope.active ? [scope.active] : [], inherited:previous.length > 0}
}
