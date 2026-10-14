import { isTask, isTaskWait, sameInputVersion, type TaskView, type TaskWait } from '../tasks/taskTypes'
import { isReviewSource, isReviewSummary, isReviewEdits, sameReviewSource, type ReviewSource, type ReviewSummary, type ReviewEdit } from './ocrReviewTypes'
export { isReviewSource, isReviewSummary, isReviewEdits } from './ocrReviewTypes'
export type { ReviewSource, ReviewSummary, ReviewEdit } from './ocrReviewTypes'
export const reviewBase=(project:string,file:string)=>`/api/v1/projects/${encodeURIComponent(project)}/files/${encodeURIComponent(file)}/ocr-reviews`
export const reviewVersionsBase=(project:string,file:string)=>`/api/v1/projects/${encodeURIComponent(project)}/files/${encodeURIComponent(file)}/ocr-review-versions`
export const reviewTaskBase=(task:string)=>`/api/v1/tasks/${encodeURIComponent(task)}/ocr-review`
export type ReviewVersion={id:string;file_id:string;parent_parse_id:string;parent_parse_version:number;version:number;created_at:string;task_id:string;source:ReviewSource;summary:ReviewSummary;download_url:string}
export type ReviewDetail=ReviewVersion&{edits:ReviewEdit[]}
export type ReviewPage={items:ReviewVersion[];total:number;page:number;page_size:5}
export type ReviewWorkspace={task:TaskView;source:ReviewSource;wait:TaskWait|null;checkpoint_id:string|null;edit_revision:number;edits:ReviewEdit[];summary:ReviewSummary|null;preview_download_url:string|null;result:ReviewVersion|null}
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0
export function isReviewTask(v:unknown,project:string,file:string,parse:string,task?:string):v is TaskView {
 return isTask(v,project,task)&&v.task_type==='review_ocr'&&v.input_version.kind==='ocr_review'&&v.input_version.source.file_id===file&&v.input_version.source.parse_id===parse
}
export function isReviewVersion(v:unknown,project:string,file:string,parse:string):v is ReviewVersion {
 return record(v)&&typeof v.id==='string'&&!!v.id&&v.file_id===file&&v.parent_parse_id===parse&&integer(v.parent_parse_version)&&v.parent_parse_version>=1&&integer(v.version)&&v.version>=1&&typeof v.created_at==='string'&&Number.isFinite(Date.parse(v.created_at))&&typeof v.task_id==='string'&&isReviewSource(v.source)&&v.source.file_id===file&&v.source.parse_id===parse&&v.source.parse_version===v.parent_parse_version&&isReviewSummary(v.summary)&&v.summary.unreviewed_blocks===0&&v.download_url===`${reviewVersionsBase(project,file)}/${encodeURIComponent(v.id)}/download`
}
export function isReviewWorkspace(v:unknown,project:string,file:string,parse:string,task:string):v is ReviewWorkspace {
 if(!record(v)||!isReviewTask(v.task,project,file,parse,task)||v.task.input_version.kind!=='ocr_review'||!isReviewSource(v.source)||!sameReviewSource(v.source,v.task.input_version.source)||!integer(v.edit_revision)||!isReviewEdits(v.edits)||!(v.checkpoint_id===null||typeof v.checkpoint_id==='string'&&!!v.checkpoint_id)||!(v.summary===null||isReviewSummary(v.summary))||!(v.preview_download_url===null||v.preview_download_url===`${reviewTaskBase(task)}/preview/download`)||!(v.result===null||isReviewVersion(v.result,project,file,parse)&&sameReviewSource(v.source,v.result.source)))return false
 const source=v.source
 if(v.summary&&(v.summary.reviewed_blocks!==v.edits.length||v.summary.accepted_blocks!==v.edits.filter(e=>e.action==='accept_original').length||v.summary.corrected_blocks!==v.edits.filter(e=>e.action==='replace_text').length||v.summary.unreadable_blocks!==v.edits.filter(e=>e.action==='unreadable').length||v.summary.no_text_pages.some(p=>!source.selected_pages.includes(p))))return false
 return v.wait===null||isTaskWait(v.wait)&&v.wait.kind==='ocr_review_confirmation'&&sameInputVersion(v.task.input_version,v.wait.input_version)&&(v.wait.status!=='open'||v.wait.task_revision===v.task.revision&&v.checkpoint_id!==null&&v.summary!==null&&v.preview_download_url!==null)
}
export function isReviewPage(v:unknown,project:string,file:string,parse:string,page:number):v is ReviewPage {
 return record(v)&&v.page===page&&v.page_size===5&&integer(v.total)&&Array.isArray(v.items)&&v.items.length<=5&&v.items.length<=v.total&&v.items.every(item=>isReviewVersion(item,project,file,parse))
}
export function isReviewDetail(v:unknown,project:string,file:string,parse:string,id:string):v is ReviewDetail {
 return record(v)&&isReviewEdits(v.edits)&&isReviewVersion(v,project,file,parse)&&v.id===id&&(v as ReviewDetail).edits.length===v.summary.total_blocks
}
