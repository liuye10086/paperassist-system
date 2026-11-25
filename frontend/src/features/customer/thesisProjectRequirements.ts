import type { Locale } from '../../shared/i18n'
import type { Chapter } from '../school-templates/contracts'
import type { SchoolWritingPurpose } from '../manuscripts/thesisTypes'
import { preparePaperKeywords, type PaperKeywordDraft } from './paperKeywords'

export const educationLevels = ['本科', '硕士', '博士'] as const
export const thesisLanguages = { 'zh-CN': '中文', en: '英文' } as const

type EducationLevel = typeof educationLevels[number]
type ThesisBasics = { education_level: EducationLevel; school: string; title: string; keywords: string[] }
export type ThesisBasicsDraft = PaperKeywordDraft & Omit<ThesisBasics, 'keywords' | 'education_level'> & {
  education_level: EducationLevel | ''; language: Locale | ''
}
export type ThesisSectionPurpose = SchoolWritingPurpose
export type ThesisSection = { chapter_id: string; purpose: ThesisSectionPurpose; content: string }
export type BoundThesisTemplate = {
  name: string; confirmation_id: string; chapters: Chapter[]
  source_file?: {file_id: string; filename: string}
  protected_chapter_purposes?: Record<string, 'manual' | 'acknowledgements'>
}
export type ThesisRequirements = Omit<ThesisBasics, 'education_level'> & {
  revision: number
  education_level: string
  language: Locale
  template: BoundThesisTemplate | null
  sections: ThesisSection[]
}

export function thesisBasicsDraft(saved?: ThesisRequirements): ThesisBasicsDraft {
  return {
    education_level: educationLevels.find(level => level === saved?.education_level) ?? '',
    language: saved?.language ?? '', school: saved?.school ?? '', title: saved?.title ?? '',
    keywords: saved?.keywords ?? [], keywordInput: '',
  }
}

export function prepareThesisBasics(draft: ThesisBasicsDraft): { basics: ThesisBasics; language: Locale } | { error: string } {
  const { education_level, language } = draft
  const school = draft.school.trim(), title = draft.title.trim()
  if (!education_level) return { error: '请选择学位层次。' }
  if (!language) return { error: '请选择论文语种。' }
  if (!school) return { error: '请填写学校名称。' }
  if (!title) return { error: '请填写论文题目。' }
  const keywords = preparePaperKeywords(draft)
  if ('error' in keywords) return keywords
  return { language, basics: { education_level, school, title, keywords: keywords.keywords } }
}
