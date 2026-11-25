import type { readingScopeLabels } from '../manuscripts/ParagraphReferenceExcerpts'
import type { Snapshot } from '../manuscripts/manuscriptTypes'
import { projectBase, useResearchRead } from '../research-results/api'
import type { TaskStatus } from '../tasks/taskTypes'

export type DraftRequest = { projectId: string; manuscriptId: string; revision: number; requestId: string }
export type Citation = {
  number: number; project_reference_id: string; title: string
  excerpts: {id: string; quote: string; reading_scope: keyof typeof readingScopeLabels}[]
}
export type Group = Pick<Snapshot['results_groups'][number], 'id' | 'title' | 'tables' | 'figures'>
export type Paragraph = { id: string; parts: {text: string; citations: Citation[]}[]; figures?: Group['figures'] }
export type Section = { id: string; heading: string; level: number; purpose?: string; output_language?: 'zh-CN' | 'en'
  paragraphs: Paragraph[]; groups: Group[]; keywords?: string[] }
export type Draft = {
  title: string; english_title?: string; output_language: 'en' | 'zh-CN'; sections: Section[]; keywords: string[]; acknowledgements: string
  references: {number: number; project_reference_id: string; text: string}[]
  reference_heading?: {heading: string; level: number}
}
export type DraftChange = {section_id: string; heading: string; before: string[]; after: string[]; paragraph_ids: string[]}
export type DraftReplyPart = {section_id: string | null; text: string}
type Detail = { project_id: string; manuscript_id: string; request_id: string; revision: number; status: TaskStatus; editable_section_ids?: string[]
  error_code: string | null; draft: Draft | null; previous_request_id: string | null; changes: DraftChange[]; can_revise: boolean;
  draft_advice?: true; advice?: string; target_sections?: string[]; partial_reply?: DraftReplyPart[] }

export const inProgress = (detail: Detail) => detail?.status === 'queued' || detail?.status === 'running'

function firstReplyDelay(detail: Detail) {
  if (detail.status === 'running' && detail.target_sections?.length && !detail.partial_reply?.some(part => part.text.trim())) {
    return 400
  }
}

export function useSciDraftRead({ projectId, manuscriptId, revision, requestId }: DraftRequest, active = true, live = false, pollMs = 3000) {
  const base = `${projectBase(projectId)}/manuscripts/${encodeURIComponent(manuscriptId)}/writing-requests/${encodeURIComponent(requestId)}/draft-reader`
  const result = useResearchRead<Detail>(`${base}?revision=${revision}`, active, inProgress, 0,
    live ? {maxDelayMs:pollMs, retryTemporaryErrors:true, maxDelayFor:firstReplyDelay} : undefined)
  const detail = result.data
  const wrongRequest = detail && (detail.request_id !== requestId || detail.revision !== revision ||
    detail.project_id !== projectId || detail.manuscript_id !== manuscriptId)
  const unreadable = detail?.status === 'succeeded' && (detail.draft_advice ? typeof detail.advice !== 'string' : !detail.draft)
  const error = result.error || (wrongRequest || unreadable ? '指定初稿暂时无法读取。' : '')
  return { ...result, base, data: error ? null : detail, error }
}

export type DraftRead = ReturnType<typeof useSciDraftRead>
