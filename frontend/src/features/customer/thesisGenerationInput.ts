import {emptyInput, mergeAnalysisSelection, sourceKey, validInput, type AnalysisSelection, type Candidates, type Manuscript} from '../manuscripts/manuscriptTypes'
import {paperDraftMaterials} from '../manuscripts/paperDraftMaterials'
import type {SchoolPurpose} from '../manuscripts/thesisTypes'
import type {Project} from '../projects/projectTypes'
import type {ThesisRequirements} from './thesisProjectRequirements'

export function thesisDraftMaterials(project:Project, requirements:ThesisRequirements | null, candidates:Candidates,
  current:Manuscript | undefined, purposes:Record<string, SchoolPurpose>, resultChapter:string, analysis?:AnalysisSelection | null) {
  const latest = current?.versions.find(v => v.revision === current.current_revision)
  const language = requirements?.language ?? project.default_output_language ?? 'zh-CN'
  let base = validInput(latest?.input) ? {...latest.input, output_language:language} : emptyInput(project.name, language)
  if (analysis?.project_id === project.id && analysis.project_type === 'thesis') base = mergeAnalysisSelection(base, analysis)
  const {input,chapterQuestions} = paperDraftMaterials(candidates, base, {omittedFiles:[],chapterPurposes:purposes}, current?.current_revision ?? 0)
  const previous = new Map(latest?.snapshot.sources.map(s => [sourceKey(s),s]))
  const labels = new Map(candidates.items.map(s => [sourceKey(s),s]))
  const sources = input.sources.flatMap(s => {
    const item = labels.get(sourceKey(s)) ?? previous.get(sourceKey(s))
    return item ? [item] : []
  })
  const parsing = sources.filter(s => s.kind === 'original' && /\.(docx|xlsx)$/i.test(s.label))
  const resultGroups = new Set(input.results_groups.map(g => g.id))
  if (input.reported_result) resultGroups.add('reported-result')
  const planned = new Set(candidates.paper_plan?.sections.filter(s => s.purpose === 'results').map(s => s.id))
  const chapters = input.thesis?.chapter_mappings ?? []
  for (const c of chapters) c.result_group_ids = c.result_group_ids.filter(id => planned.has(id) || resultGroups.has(id))
  const results = chapters.filter(c => c.purpose === 'results')
  if (results.length === 1) results[0].result_group_ids = [...new Set([...results[0].result_group_ids,...resultGroups])]
  const needsPlacement = !!input.reported_result && !results.some(c => c.result_group_ids.includes('reported-result'))
  const chosen = needsPlacement ? results.find(c => c.chapter_id === resultChapter) : undefined
  if (chosen) chosen.result_group_ids.push('reported-result')
  const resultChoices = needsPlacement && results.length > 1 ? new Set(results.map(c => c.chapter_id)) : null
  return {input, sources, parsing, unassignedResult:needsPlacement && !chosen,chapterQuestions,resultChoices}
}
