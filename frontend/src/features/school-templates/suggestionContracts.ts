import type {Source} from './contracts'
import type {TaskView} from '../tasks/taskTypes'

export type SuggestionDecision={candidate_id:string;action:'accept'|'reject'|'defer';reason:string}
export type SuggestionSelection={suggestion_id:string;suggestion_artifact_sha256:string;suggestion_decisions:SuggestionDecision[]}
export type SuggestionCandidate={id:string;target_id:string|null;value:string|null;note_alias:string;start:number;end:number;quote:string;status:'proposed'|'conflict'|'unknown'|'unsupported';reason:string;normalized_value:string|number|null;source_verified:boolean;human_confirmed:false;current_value?:unknown;source:Source}
export type SuggestionView={schema_version:1;id:string;template_version_id:string;analysis_sha256:string;task:TaskView;bundle_sha256:string;artifact_sha256:string|null;result:{candidates:SuggestionCandidate[]}|null;model_calls:{id:string;status:string;model:string;provider_provenance:null|'synthetic_fixture'|'openai_live';estimated_cost_micro_usd:number|null}[]}
export type SuggestionPreview={schema_version:1;template_version_id:string;analysis_sha256:string;notes:{id:string;alias:string;text:string;source:Source;sha256:string}[];material:{notes:{alias:string;text:string}[];capabilities:{id:string;kind:string;current_value:unknown}[];capability_catalog_version:'school-rule-capabilities-v1'};bundle_sha256:string;policy:{model:string;price:Record<string,unknown>;[key:string]:unknown};input_token_allowance:number;reserved_micro_usd:number;real_calls_enabled:boolean}
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const text=(v:unknown):v is string=>typeof v==='string'
const sha=(v:unknown):v is string=>text(v)&&/^[a-f0-9]{64}$/.test(v)
const source=(v:unknown)=>record(v)&&['part','path','text'].every(k=>text(v[k]))
const nullableText=(v:unknown)=>v===null||text(v)
const nonnegative=(v:unknown)=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0
function candidate(v:unknown):v is SuggestionCandidate{
 return record(v)&&text(v.id)&&nullableText(v.target_id)&&nullableText(v.value)&&text(v.note_alias)&&nonnegative(v.start)&&nonnegative(v.end)&&Number(v.end)>=Number(v.start)&&text(v.quote)&&['proposed','conflict','unknown','unsupported'].includes(String(v.status))&&text(v.reason)&&(v.normalized_value===null||text(v.normalized_value)||typeof v.normalized_value==='number'&&Number.isFinite(v.normalized_value))&&typeof v.source_verified==='boolean'&&v.human_confirmed===false&&source(v.source)
}
export function isSuggestionView(v:unknown,templateId:string,analysisSha:string):v is SuggestionView{
 return record(v)&&v.schema_version===1&&text(v.id)&&v.template_version_id===templateId&&v.analysis_sha256===analysisSha&&sha(v.bundle_sha256)&&(v.artifact_sha256===null||sha(v.artifact_sha256))&&record(v.task)&&text(v.task.id)&&['queued','running','waiting_input','waiting_confirmation','succeeded','failed'].includes(String(v.task.status))&&(v.result===null||record(v.result)&&Array.isArray(v.result.candidates)&&v.result.candidates.every(candidate)&&new Set(v.result.candidates.map(c=>c.id)).size===v.result.candidates.length)&&Array.isArray(v.model_calls)&&v.model_calls.every(c=>record(c)&&['id','status','model'].every(k=>text(c[k]))&&[null,'synthetic_fixture','openai_live'].includes(c.provider_provenance as string|null)&&(c.estimated_cost_micro_usd===null||nonnegative(c.estimated_cost_micro_usd)))
}
export function isSuggestionList(v:unknown,templateId:string,analysisSha:string):v is {items:SuggestionView[]}{
 return record(v)&&Array.isArray(v.items)&&v.items.every(item=>isSuggestionView(item,templateId,analysisSha))&&new Set(v.items.map(item=>item.id)).size===v.items.length
}
export function isSuggestionPreview(v:unknown,templateId:string,analysisSha:string,noteIds:string[]):v is SuggestionPreview{
 if(!record(v)||v.schema_version!==1||v.template_version_id!==templateId||v.analysis_sha256!==analysisSha||!sha(v.bundle_sha256)||!Array.isArray(v.notes)||!v.notes.every(n=>record(n)&&text(n.id)&&text(n.alias)&&text(n.text)&&source(n.source)&&sha(n.sha256)))return false
 const notes=v.notes
 if(notes.length!==noteIds.length||!noteIds.every(id=>notes.some(n=>n.id===id))||new Set(notes.map(n=>n.id)).size!==notes.length)return false
 return record(v.material)&&v.material.capability_catalog_version==='school-rule-capabilities-v1'&&Array.isArray(v.material.notes)&&v.material.notes.length===notes.length&&v.material.notes.every(n=>record(n)&&text(n.alias)&&text(n.text)&&notes.some(note=>note.alias===n.alias&&note.text===n.text))&&Array.isArray(v.material.capabilities)&&v.material.capabilities.every(c=>record(c)&&text(c.id)&&text(c.kind)&&Object.hasOwn(c,'current_value'))&&record(v.policy)&&text(v.policy.model)&&record(v.policy.price)&&nonnegative(v.input_token_allowance)&&nonnegative(v.reserved_micro_usd)&&typeof v.real_calls_enabled==='boolean'
}
export function suggestionSelection(view:SuggestionView|null,decisions:Record<string,{action:string;reason:string}>):SuggestionSelection|null{
 if(!view||view.task.status!=='succeeded'||!view.artifact_sha256||!view.result)return null
 const complete=view.result.candidates.every(candidate=>{const decision=decisions[candidate.id];return decision&&['accept','reject','defer'].includes(decision.action)&&!!decision.reason.trim()&&(decision.action!=='accept'||['proposed','conflict'].includes(candidate.status)&&candidate.source_verified)})
 return complete?{suggestion_id:view.id,suggestion_artifact_sha256:view.artifact_sha256,suggestion_decisions:view.result.candidates.map(candidate=>({candidate_id:candidate.id,action:decisions[candidate.id].action as SuggestionDecision['action'],reason:decisions[candidate.id].reason.trim()}))}:null
}
