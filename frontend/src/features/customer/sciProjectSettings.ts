export const articleTypes = { research: '研究型论文', narrative_review: '综述' } as const
export const journalChoices = { nature_subjournal: 'Nature 子刊', science: 'Science', other: '其他期刊' } as const
export const MAX_KEYWORDS = 30
export const MAX_FIGURE_PLANS = 30

type ArticleType = keyof typeof articleTypes
type JournalChoice = keyof typeof journalChoices
type FigurePlan = { title: string; description: string }

export type SciSettings = {
  article_type: ArticleType
  main_results: string
  target_journal: { choice: JournalChoice; name: string | null }
  keywords: string[]
  figure_plan: FigurePlan[]
}

export type SciSettingsDraft = Omit<SciSettings, 'article_type' | 'target_journal'> & {
  article_type: ArticleType | ''
  target_journal: { choice: JournalChoice | ''; name: string }
  keywordInput: string
}

export type SciSettingsState = { revision: number; settings: SciSettings | null }

export function sciSettingsDraft(settings: SciSettings | null = null): SciSettingsDraft {
  return {
    article_type: settings?.article_type ?? '',
    main_results: settings?.main_results ?? '',
    target_journal: { choice: settings?.target_journal.choice ?? '', name: settings?.target_journal.name ?? '' },
    keywords: settings?.keywords ?? [],
    figure_plan: settings?.figure_plan ?? [],
    keywordInput: '',
  }
}

export function hasKeyword(keywords: string[], value: string) {
  return keywords.some(keyword => keyword.toLowerCase() === value.toLowerCase())
}

export function prepareSciSettings(draft: SciSettingsDraft): { settings: SciSettings } | { error: string } {
  const { article_type, target_journal, keywordInput } = draft
  const main_results = draft.main_results.trim()
  if (!article_type) return { error: '请选择论文类型。' }
  if (!main_results) return { error: '请填写主要结果或结论。' }
  if (!target_journal.choice) return { error: '请选择一个目标期刊。' }
  const name = target_journal.choice === 'science' ? '' : target_journal.name.trim()
  if (target_journal.choice === 'other' && !name) return { error: '请填写具体期刊名称。' }
  const pending = keywordInput.trim()
  if (pending && hasKeyword(draft.keywords, pending)) return { error: '关键词已添加。' }
  const keywords = pending ? [...draft.keywords, pending] : draft.keywords
  if (!keywords.length || keywords.length > MAX_KEYWORDS) return { error: '请填写 1 至 30 个关键词。' }
  const figure_plan = draft.figure_plan.map(item => ({ title: item.title.trim(), description: item.description.trim() }))
  if (!figure_plan.length || figure_plan.some(item => !item.title || !item.description)) {
    return { error: '请至少添加一项图表计划，并填写每项的标题和拟表达内容。' }
  }
  return { settings: { article_type, main_results, target_journal: { choice: target_journal.choice, name: name || null }, keywords, figure_plan } }
}
