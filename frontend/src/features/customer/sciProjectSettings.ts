import { preparePaperKeywords, type PaperKeywordDraft } from './paperKeywords'

export const articleTypes = { research: '研究型论文', narrative_review: '综述' } as const
export const journalChoices = { nature_subjournal: 'Nature 子刊', science: 'Science', other: '其他期刊' } as const
export const journalPresetRows = [
  ['Nature', 'Nature Communications'],
  ['Science', 'Cell', 'PLOS ONE'],
] as const
const journalPresets = journalPresetRows.flat()

type ArticleType = keyof typeof articleTypes
type JournalChoice = keyof typeof journalChoices
type JournalIntent = { choice: JournalChoice; name: string | null }
type JournalDraft = { selection: typeof journalPresets[number] | 'other' | ''; customName: string }
type FigurePlan = { title: string; description: string }
type FigureFinding = { id: string; finding: string }
type ReviewSection = { id: string; heading: string; content: string }

type SciIntent = {
  target_journal: JournalIntent | null
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
}
export type SciSettingsDraft = SciDraftIntent & {
  proposed_title: string
  target_journal: JournalDraft
  figure_findings: FigureFinding[]
  legacy_draft?: LegacySciContent
}
export type StoredSciSettingsDraft = (
  | (Omit<SciSettingsDraft, 'target_journal'> & { review_sections?: ReviewSection[] })
  | (SciDraftIntent & LegacySciContent)
) & {
  target_journal: JournalDraft | { choice: JournalChoice | ''; name: string }
}

export type SciSettingsState = { revision: number; settings: SciSettings | null; legacy_settings?: LegacySciSettings }

export function isLegacySciSettings(settings: SciSettings): settings is LegacySciSettings {
  return 'main_results' in settings
}

function journalDraft(journal?: { choice: JournalChoice | ''; name: string | null } | null): JournalDraft {
  if (!journal?.choice) return { selection: '', customName: '' }
  if (journal.choice === 'science') return { selection: 'Science', customName: '' }
  const name = journal.name ?? ''
  const normalized = name.trim().toLowerCase()
  const preset = journalPresets.find(option => option.toLowerCase() === normalized)
  return preset ? { selection: preset, customName: '' } : { selection: 'other', customName: name }
}

export function sciSettingsDraft(settings: SciSettings | null = null): SciSettingsDraft {
  const requirements = settings && !isLegacySciSettings(settings) ? settings : null
  return {
    article_type: settings?.article_type ?? '',
    proposed_title: requirements?.proposed_title ?? '',
    target_journal: journalDraft(settings?.target_journal),
    keywords: settings?.keywords ?? [],
    figure_findings: requirements?.article_type === 'research' ? requirements.figure_findings : [],
    keywordInput: '',
  }
}

export function restoreSciSettingsDraft(stored?: StoredSciSettingsDraft): SciSettingsDraft {
  if (!stored) return sciSettingsDraft()
  const journal = stored.target_journal
  const target_journal = 'selection' in journal ? journal : journalDraft(journal)
  if ('proposed_title' in stored) {
    const { review_sections: _reviewSections, ...draft } = stored
    return { ...draft, target_journal }
  }
  const { main_results, figure_plan, ...intent } = stored
  return { ...sciSettingsDraft(), ...intent, target_journal, legacy_draft: { main_results, figure_plan } }
}

export function legacySciResult(settings: SciSettings | null | undefined) {
  return settings && isLegacySciSettings(settings) ? settings.main_results : ''
}

export function prepareSciSettings(draft: SciSettingsDraft, savedReviewSections: ReviewSection[] = []): { settings: SciRequirements } | { error: string } {
  const { article_type, target_journal } = draft
  if (!article_type) return { error: '请选择论文类型。' }
  const proposed_title = draft.proposed_title.trim()
  if (!proposed_title) return { error: '请填写拟定论文题目。' }
  const prepared = preparePaperKeywords(draft)
  if ('error' in prepared) return prepared
  const { selection, customName } = target_journal
  if (!selection) return { error: '请选择一个目标期刊。' }
  const name = selection === 'other' ? customName.trim() : selection
  if (!name) return { error: '请填写具体期刊名称。' }
  const journal: JournalIntent = selection === 'Science' ? { choice: 'science', name: null } : { choice: 'other', name }
  const intent = { proposed_title, target_journal: journal, keywords: prepared.keywords }
  if (article_type === 'research') {
    const figure_findings = draft.figure_findings.map(({ id, finding }) => ({ id, finding: finding.trim() })).filter(item => item.finding)
    return { settings: { ...intent, article_type, figure_findings } }
  }
  return { settings: { ...intent, article_type, review_sections: savedReviewSections } }
}
