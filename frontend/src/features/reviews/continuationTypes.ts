import {object} from './revisionTypes'
export type ManuscriptInput={id:string;revision:number;version_id:string}
export type NextRoundInput={previous_round_id:string;user_return_id?:string;manuscript:ManuscriptInput}
export type ReturnMapping={input_section_id:string;chapter_id:string}
export type UserReturn={
 id:string;previous_round_id:string;revision_id:string|null;synthetic:boolean;manuscript_id:string;base_version_id:string;base_revision:number
 source:Record<string,unknown>;original_download_url:string
 input_sections:{id:string;title:string;paragraphs:string[];candidate_chapter_ids:string[];match_method:string;suggested_chapter_id:string|null}[]
 target_chapters:{id:string;title:string}[];mappings:ReturnMapping[]
 differences:{kind:string;location:unknown;message:string;before:string;after:string}[]
 issues:{code:string;severity:string;message:string;location:unknown}[];can_adopt:boolean;preview_sha256:string|null
 output:{manuscript_id:string;version_id:string;revision:number;parent_version_id:string;task_id:string;status:'pending'|'published'|'failed'}|null;created_at:string
}
export type ContinuationContext={previous_round_id:string;manuscript_id:string;expected_current_revision:number;eligible_inputs:(ManuscriptInput&{title:string;exports:{id:string;status:string}[]})[];successful_revisions:{id:string;output:{version_id:string;[key:string]:unknown}}[];returns:UserReturn[]}
export type ProgressStatus='submitted'|'revision'|'accepted'|'published'|'withdrawn'|'not_recorded'
export type ProgressEvent={id:string;project_id:string;status:ProgressStatus;event_date:string;note:string;synthetic:boolean;target_id:string|null;round_id:string|null;manuscript:ManuscriptInput|null;export_id:string|null;corrects_event_id:string|null;recorded_by:string;created_at:string;source_kind:'project'|'journal'}
export type ProgressHistory={items:ProgressEvent[];current:ProgressEvent|null;journal_current_by_target:Record<string,ProgressEvent>}
const text=(v:unknown):v is string=>typeof v==='string'
const id=(v:unknown):v is string=>text(v)&&!!v
const positive=(v:unknown)=>Number.isSafeInteger(v)&&Number(v)>0
export const manuscriptInput=(v:unknown):v is ManuscriptInput=>object(v)&&id(v.id)&&id(v.version_id)&&positive(v.revision)
export function validReturn(v:unknown,projectId:string,roundId:string):v is UserReturn{
 return object(v)&&id(v.id)&&v.previous_round_id===roundId&&typeof v.synthetic==='boolean'&&id(v.manuscript_id)&&id(v.base_version_id)&&positive(v.base_revision)&&object(v.source)&&typeof v.original_download_url==='string'&&v.original_download_url.startsWith(`/api/v1/projects/${encodeURIComponent(projectId)}/files/`)&&Array.isArray(v.input_sections)&&v.input_sections.every(s=>object(s)&&id(s.id)&&text(s.title)&&Array.isArray(s.paragraphs)&&s.paragraphs.every(text))&&Array.isArray(v.target_chapters)&&v.target_chapters.every(s=>object(s)&&id(s.id)&&text(s.title))&&Array.isArray(v.mappings)&&v.mappings.every(m=>object(m)&&id(m.input_section_id)&&id(m.chapter_id))&&Array.isArray(v.differences)&&v.differences.every(d=>object(d)&&text(d.kind)&&text(d.message)&&text(d.before)&&text(d.after))&&Array.isArray(v.issues)&&v.issues.every(i=>object(i)&&text(i.code)&&text(i.severity)&&text(i.message))&&typeof v.can_adopt==='boolean'&&(v.preview_sha256===null||text(v.preview_sha256)&&/^[a-f0-9]{64}$/.test(v.preview_sha256))&&(v.output===null||object(v.output)&&['manuscript_id','version_id','parent_version_id','task_id'].every(k=>id((v.output as Record<string,unknown>)[k]))&&positive(v.output.revision)&&['pending','published','failed'].includes(String(v.output.status)))&&text(v.created_at)
}
export function validContinuation(v:unknown,projectId:string,roundId:string):v is ContinuationContext{
 return object(v)&&v.previous_round_id===roundId&&id(v.manuscript_id)&&positive(v.expected_current_revision)&&Array.isArray(v.eligible_inputs)&&v.eligible_inputs.every(i=>object(i)&&text(i.title)&&Array.isArray(i.exports)&&i.exports.every(e=>object(e)&&id(e.id)&&text(e.status))&&manuscriptInput(i)&&i.id===v.manuscript_id)&&Array.isArray(v.successful_revisions)&&v.successful_revisions.every(r=>object(r)&&id(r.id)&&object(r.output)&&id(r.output.version_id))&&Array.isArray(v.returns)&&v.returns.every(r=>validReturn(r,projectId,roundId))
}
export const progressStatuses:Record<ProgressStatus,string>={submitted:'已投稿',revision:'修改中',accepted:'已录用',published:'已发表',withdrawn:'已撤回',not_recorded:'未记录'}
export const schoolProgressStatuses:Record<ProgressStatus,string>={submitted:'送审',revision:'修改',accepted:'评审通过',published:'学校流程已完成',withdrawn:'撤回送审',not_recorded:'未记录'}
export function validProgress(v:unknown,projectId:string):v is ProgressEvent{return object(v)&&id(v.id)&&v.project_id===projectId&&Object.hasOwn(progressStatuses,String(v.status))&&text(v.event_date)&&/^\d{4}-\d{2}-\d{2}$/.test(v.event_date)&&text(v.note)&&typeof v.synthetic==='boolean'&&['project','journal'].includes(String(v.source_kind))&&(v.source_kind==='project'?v.target_id===null:id(v.target_id))&&['round_id','export_id','corrects_event_id'].every(k=>v[k]===null||id(v[k]))&&(v.manuscript===null||manuscriptInput(v.manuscript))&&text(v.recorded_by)&&text(v.created_at)}
export function validProgressHistory(v:unknown,projectId:string):v is ProgressHistory{return object(v)&&Array.isArray(v.items)&&v.items.every(i=>validProgress(i,projectId))&&(v.current===null||validProgress(v.current,projectId))&&object(v.journal_current_by_target)&&Object.entries(v.journal_current_by_target).every(([target,e])=>validProgress(e,projectId)&&e.source_kind==='journal'&&e.target_id===target)}
export function manuscriptHash(projectId:string,m:ManuscriptInput){return `#project=${encodeURIComponent(projectId)}&section=manuscripts&manuscript=${encodeURIComponent(m.id)}&revision=${m.revision}`}
