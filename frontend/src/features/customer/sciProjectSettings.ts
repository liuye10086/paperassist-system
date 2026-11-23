import { preparePaperKeywords, type PaperKeywordDraft } from './paperKeywords'

export const articleTypes = { research: '研究型论文', narrative_review: '综述' } as const
export const journalChoices = { nature_subjournal: 'Nature 子刊', science: 'Science', other: '其他期刊' } as const

type ArticleType = keyof typeof articleTypes
type JournalChoice = keyof typeof journalChoices
type FigurePlan = { title: string; description: string }
type FigureFinding = { id: string; finding: string }
type ReviewSection = { id: string; heading: string; content: string }

type SciIntent = {
  target_journal: { choice: JournalChoice; name: string | null } | null
  keywords: string[]
}

export type LegacySciContent = {
  main_results: string
  figure_plan: FigurePlan[]
}

export type LegacySciSettings = SciIntent & LegacySciContent & { article_type: ArticleType }
type SciRequirements = SciIntent & { proposed_title: string } & (
  | { article_type: 'research'; figure_findings: FigureFinding[] }
  | { article_type: 'narrative_review'; review_sections: ReviewSection[] }
)
export type SciSettings = LegacySciSettings | SciRequirements

type SciDraftIntent = PaperKeywordDraft & {
  article_type: ArticleType | ''
  target_journal: { choice: JournalChoice | ''; name: string }
}
export type SciSettingsDraft = SciDraftIntent & {
  proposed_title: string
  figure_findings: FigureFinding[]
  review_sections: ReviewSection[]
  legacy_draft?: LegacySciContent
}
export type StoredSciSettingsDraft = SciSettingsDraft | (SciDraftIntent & LegacySciContent)

export type SciSettingsState = { revision: number; settings: SciSettings | null; legacy_settings?: LegacySciSettings }

export function isLegacySciSettings(settings: SciSettings): settings is LegacySciSettings {
  return 'main_results' in settings
}

export function sciSettingsDraft(settings: SciSettings | null = null): SciSettingsDraft {
  const requirements = settings && !isLegacySciSettings(settings) ? settings : null
  return {
    article_type: settings?.article_type ?? '',
    proposed_title: requirements?.proposed_title ?? '',
    target_journal: { choice: settings?.target_journal?.choice ?? '', name: settings?.target_journal?.name ?? '' },
    keywords: settings?.keywords ?? [],
    figure_findings: requirements?.article_type === 'research' ? requirements.figure_findings : [],
    review_sections: requirements?.article_type === 'narrative_review' ? requirements.review_sections : [],
    keywordInput: '',
  }
}

export function restoreSciSettingsDraft(stored?: StoredSciSettingsDraft): SciSettingsDraft {
  if (!stored) return sciSettingsDraft()
  if ('proposed_title' in stored) return stored
  const { main_results, figure_plan, ...intent } = stored
  return { ...sciSettingsDraft(), ...intent, legacy_draft: { main_results, figure_plan } }
}

export function legacySciResult(settings: SciSettings | null | undefined) {
  return settings && isLegacySciSettings(settings) ? settings.main_results : ''
}

export function prepareSciSettings(draft: SciSettingsDraft): { settings: SciRequirements } | { error: string } {
  const { article_type, target_journal } = draft
  if (!article_type) return { error: '请选择论文类型。' }
  const proposed_title = draft.proposed_title.trim()
  if (!proposed_title) return { error: '请填写拟定论文题目。' }
  const name = target_journal.choice === 'science' ? '' : target_journal.name.trim()
  const prepared = preparePaperKeywords(draft)
  if ('error' in prepared) return prepared
  const journal = target_journal.choice && (name || target_journal.choice === 'science')
    ? { choice: target_journal.choice, name: name || null } : null
  const intent = { proposed_title, target_journal: journal, keywords: prepared.keywords }
  if (article_type === 'research') {
    const figure_findings = draft.figure_findings.map(({ id, finding }) => ({ id, finding: finding.trim() })).filter(item => item.finding)
    return { settings: { ...intent, article_type, figure_findings } }
  }
  const review_sections = draft.review_sections.map(({ id, heading, content }) => ({ id, heading: heading.trim(), content: content.trim() }))
  if (review_sections.some(item => !item.heading || !item.content)) {
    return { error: '请至少添加一个小标题，并填写每项需要涵盖的内容。' }
  }
  return { settings: { ...intent, article_type, review_sections } }
}
