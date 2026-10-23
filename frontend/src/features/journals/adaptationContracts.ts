import {isTask,type TaskView} from '../tasks/taskTypes'
import {record} from './contracts'
import {sectionIds,styleBounds} from './formatContracts'
export type FixedManuscript={id:string;revision:number;version_id:string}
export type AdaptationRequest={target_id:string;check_id:string;manuscript:FixedManuscript}
export type Action={id:string;key:string;before:unknown;after:unknown;evidence:unknown[];reason:string}
export type Unexecuted={key:string;evidence:unknown[];reason:string}
export type AdaptationPreview=AdaptationRequest&{expected_current_revision:number;preview_sha256:string;sections:{section_id:string;before:unknown;after:unknown;changed:boolean}[];actions:Action[];unexecuted:Unexecuted[];synthetic:boolean;can_adopt:boolean;display_version?:string}
export type AdoptRequest=AdaptationRequest&{expected_current_revision:number;preview_sha256:string;selected_action_ids:string[]}
export type Adaptation={validation?:{public_issues:Record<string,unknown>[];public_check_version:3;candidate_sha256:string;can_publish:boolean}|null;id:string;created_at:string;task:TaskView;input_snapshot:AdaptationRequest&{id:string;project_id:string;kind:'journal_adaptation';workflow_version:'journal_adaptation_v1';requirements_version:string;expected_current_revision:number;preview_sha256:string;preview:AdaptationPreview;selected_action_ids:string[];synthetic:boolean;real_model_calls:false;real_network_calls:false};result:{actual_changes:Action[];unexecuted:Unexecuted[];public_issues:Record<string,unknown>[];output:{manuscript_id:string;version_id:string;revision:number;parent_version_id:string;task_id:string};synthetic:boolean;display_version:string}|null}
export const submissionStatuses={not_recorded:'未记录',submitted:'已投稿',revision:'返修',accepted:'录用',published:'发表',withdrawn:'撤回'} as const
export type SubmissionRequest={target_id:string;status:keyof typeof submissionStatuses;event_date:string;note:string;manuscript?:FixedManuscript|null;export_id?:string|null;corrects_event_id?:string|null}
export type SubmissionEvent=SubmissionRequest&{id:string;project_id:string;created_at:string;recorded_by:string}
export type SubmissionHistory={items:SubmissionEvent[];current_by_target:Record<string,SubmissionEvent>}
const id=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9_-]{1,64}$/.test(v)
const text=(v:unknown):v is string=>typeof v==='string'
const hash=(v:unknown)=>text(v)&&/^[a-f0-9]{64}$/.test(v)
const revision=(v:unknown):v is number=>Number.isSafeInteger(v)&&Number(v)>=1
export function isFixedManuscript(v:unknown):v is FixedManuscript{return record(v)&&id(v.id)&&id(v.version_id)&&revision(v.revision)}
export function sameManuscript(a:FixedManuscript,b:FixedManuscript){return a.id===b.id&&a.revision===b.revision&&a.version_id===b.version_id}
export function actualSections(preview:AdaptationPreview,changes:Action[]){return preview.sections.map(section=>{
 const original=record(section.before)?section.before:{},before=section.section_id==='title'?{...original,styles:{}}:original,after={...before,styles:record(before.styles)?{...before.styles}:{}} as Record<string,unknown>
 for(const change of changes){if(change.key==='section_display_names'&&record(change.after)&&typeof change.after[section.section_id]==='string')after.display_name=change.after[section.section_id]
 else if(change.key==='section_order'&&Array.isArray(change.after))after.position=change.after.indexOf(section.section_id)
 else if(section.section_id!=='title'&&Object.hasOwn(styleBounds,change.key))(after.styles as Record<string,unknown>)[change.key]=change.after}
 const changed=before.display_name!==after.display_name||before.position!==after.position||JSON.stringify(record(before.styles)?before.styles:{})!==JSON.stringify(after.styles)
 return {...section,before,after,changed}
})}
function action(v:unknown):v is Action{return record(v)&&text(v.id)&&!!v.id&&v.id.length<=200&&text(v.key)&&Object.hasOwn(v,'before')&&Object.hasOwn(v,'after')&&Array.isArray(v.evidence)&&text(v.reason)}
function unexecuted(v:unknown):v is Unexecuted{return record(v)&&text(v.key)&&text(v.reason)&&Array.isArray(v.evidence)}
export function isAdaptationPreview(v:unknown,expected?:AdaptationRequest):v is AdaptationPreview{
 if(!record(v)||!id(v.target_id)||!id(v.check_id)||!isFixedManuscript(v.manuscript)||!revision(v.expected_current_revision)||!hash(v.preview_sha256)||typeof v.synthetic!=='boolean'||typeof v.can_adopt!=='boolean'||!Array.isArray(v.actions)||!v.actions.every(action)||new Set(v.actions.map(a=>a.id)).size!==v.actions.length||!Array.isArray(v.unexecuted)||!v.unexecuted.every(unexecuted)||!Array.isArray(v.sections)||v.sections.length!==7||!sectionIds.every(id=>Array.isArray(v.sections)&&v.sections.filter(s=>record(s)&&s.section_id===id&&typeof s.changed==='boolean'&&Object.hasOwn(s,'before')&&Object.hasOwn(s,'after')).length===1)||v.can_adopt!==(v.actions.length>0))return false
 return !expected||v.target_id===expected.target_id&&v.check_id===expected.check_id&&sameManuscript(v.manuscript,expected.manuscript)
}
export function isAdaptation(v:unknown,projectId:string):v is Adaptation{
 if(!record(v)||!id(v.id)||!text(v.created_at)||!isTask(v.task,projectId)||v.task.task_type!=='journal_adaptation'||v.task.input_version.kind!=='journal_adaptation'||v.task.input_version.adaptation_id!==v.id||!record(v.input_snapshot))return false
 if(v.validation!=null&&(!record(v.validation)||!Array.isArray(v.validation.public_issues)||!v.validation.public_issues.every(record)||v.validation.public_check_version!==3||!hash(v.validation.candidate_sha256)||typeof v.validation.can_publish!=='boolean'))return false
 const s=v.input_snapshot,i=v.task.input_version
 if(s.id!==v.id||s.project_id!==projectId||s.kind!=='journal_adaptation'||s.workflow_version!=='journal_adaptation_v1'||s.target_id!==i.target_id||s.check_id!==i.check_id||s.requirements_version!==i.requirements_version||!isFixedManuscript(s.manuscript)||s.manuscript.version_id!==i.manuscript_version_id||!revision(s.expected_current_revision)||!hash(s.preview_sha256)||!isAdaptationPreview(s.preview,{target_id:i.target_id,check_id:i.check_id,manuscript:s.manuscript})||s.preview.preview_sha256!==s.preview_sha256||!Array.isArray(s.selected_action_ids)||!s.selected_action_ids.length||!s.selected_action_ids.every(a=>text(a)&&(s.preview as AdaptationPreview).actions.some(x=>x.id===a))||typeof s.synthetic!=='boolean'||s.real_model_calls!==false||s.real_network_calls!==false)return false
 if(v.result===null)return true
 const r=v.result
 return v.task.status==='succeeded'&&record(r)&&Array.isArray(r.actual_changes)&&r.actual_changes.every(action)&&r.actual_changes.every(a=>(s.selected_action_ids as string[]).includes(a.id))&&Array.isArray(r.unexecuted)&&r.unexecuted.every(unexecuted)&&Array.isArray(r.public_issues)&&r.public_issues.every(record)&&typeof r.synthetic==='boolean'&&text(r.display_version)&&record(r.output)&&id(r.output.manuscript_id)&&id(r.output.version_id)&&id(r.output.task_id)&&revision(r.output.revision)&&r.output.parent_version_id===s.manuscript.version_id
}
export function isSubmissionEvent(v:unknown,projectId:string):v is SubmissionEvent{return record(v)&&v.project_id===projectId&&id(v.id)&&id(v.target_id)&&Object.hasOwn(submissionStatuses,String(v.status))&&text(v.event_date)&&/^\d{4}-\d{2}-\d{2}$/.test(v.event_date)&&Number.isFinite(Date.parse(v.event_date))&&text(v.note)&&text(v.created_at)&&text(v.recorded_by)&&(v.manuscript==null||isFixedManuscript(v.manuscript))&&(v.export_id==null||id(v.export_id))&&(v.corrects_event_id==null||id(v.corrects_event_id))}
export function isSubmissionHistory(v:unknown,projectId:string):v is SubmissionHistory{return record(v)&&Array.isArray(v.items)&&v.items.every(e=>isSubmissionEvent(e,projectId))&&record(v.current_by_target)&&Object.entries(v.current_by_target).every(([target,e])=>isSubmissionEvent(e,projectId)&&e.target_id===target&&(v.items as SubmissionEvent[]).some(item=>item.id===e.id))}
