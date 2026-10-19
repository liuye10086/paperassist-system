import type {ReviewInput} from './evidenceApi'
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const text=(v:unknown):v is string=>typeof v==='string'
const identifier=(v:unknown):v is string=>text(v)&&/^[A-Za-z0-9_-]{1,64}$/.test(v)
const reviewStatuses=['supported','partial','unsupported','needs_review'] as const
export type SearchPlanResult={direction:string;terms:string[];synonyms:string[];mesh_candidates:{term:string;verified:false}[];query:string;explanation:string}
export type EvidenceReviewResult={status:ReviewInput['status'];relevance:'related'|'unrelated'|'uncertain';reason:string;narrowed_statement:string;limitations:string[];evidence_ids:string[]}
const strings=(v:unknown):v is string[]=>Array.isArray(v)&&v.every(text)
export function validSearchPlanResult(v:unknown):v is SearchPlanResult{return object(v)&&text(v.direction)&&strings(v.terms)&&v.terms.length>0&&strings(v.synonyms)&&Array.isArray(v.mesh_candidates)&&v.mesh_candidates.every(m=>object(m)&&text(m.term)&&m.verified===false)&&text(v.query)&&text(v.explanation)}
export function validEvidenceReviewResult(v:unknown):v is EvidenceReviewResult{return object(v)&&(reviewStatuses as readonly string[]).includes(String(v.status))&&['related','unrelated','uncertain'].includes(String(v.relevance))&&text(v.reason)&&text(v.narrowed_statement)&&strings(v.limitations)&&Array.isArray(v.evidence_ids)&&v.evidence_ids.every(identifier)&&new Set(v.evidence_ids).size===v.evidence_ids.length&&(!['supported','partial'].includes(String(v.status))||v.evidence_ids.length>0&&v.relevance==='related')&&(v.status!=='partial'||!!v.narrowed_statement.trim())&&(v.relevance!=='uncertain'||v.status==='needs_review')}
export type EvidenceComparisonResult=EvidenceReviewResult&{comparison:'consistent'|'conflicting'|'incomparable'|'insufficient'}
export function validEvidenceComparisonResult(v:unknown):v is EvidenceComparisonResult{return validEvidenceReviewResult(v)&&'comparison' in v&&['consistent','conflicting','incomparable','insufficient'].includes(String(v.comparison))&&(v.comparison==='consistent'||v.status==='needs_review')&&(v.status==='needs_review'||v.evidence_ids.length>=2)}
export function validAssistanceResult(kind:string,value:unknown):value is SearchPlanResult|EvidenceReviewResult|EvidenceComparisonResult{return kind==='search_plan'?validSearchPlanResult(value):kind==='evidence_comparison'?validEvidenceComparisonResult(value):kind==='evidence_review'&&validEvidenceReviewResult(value)}
