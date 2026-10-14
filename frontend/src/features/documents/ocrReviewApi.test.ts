import { expect, test } from 'vitest'
import { isReviewSummary, isReviewEdits, isReviewSource, isReviewWorkspace, reviewBase } from './ocrReviewApi'
import { isTask, sameInputVersion, taskPhaseName, type TaskView } from '../tasks/taskTypes'
test('review summary accounts for all explicit decisions and preserves no-text physical pages',()=>{
 const summary={total_blocks:3,reviewed_blocks:2,unreviewed_blocks:1,accepted_blocks:1,corrected_blocks:0,unreadable_blocks:1,no_text_pages:[8]}
 expect(isReviewSummary(summary)).toBe(true)
 expect(isReviewSummary({...summary,reviewed_blocks:3})).toBe(false)
 expect(isReviewSummary({...summary,no_text_pages:[8,8]})).toBe(false)
})
test('review edits never silently accept missing blocks and only replacement carries text',()=>{
 expect(isReviewEdits([])).toBe(true)
 expect(isReviewEdits([{block_id:'b',action:'unreadable'}])).toBe(true)
 expect(isReviewEdits([{block_id:'b',action:'unreadable',text:'guess'}])).toBe(false)
 expect(isReviewEdits([{block_id:'b',action:'replace_text'}])).toBe(false)
 expect(isReviewEdits([{block_id:'b',action:'replace_text',text:'   '}])).toBe(false)
 expect(isReviewEdits([{block_id:'b',action:'replace_text',text:'x'.repeat(20001)}])).toBe(false)
 expect(isReviewEdits([{block_id:'b',action:'accept_original'},{block_id:'b',action:'unreadable'}])).toBe(false)
})
test('review task accepts frozen provenance and compares the full parent identity',()=>{
 const source={file_id:'f',parse_id:'parse',parse_version:2,source_sha256:'a'.repeat(64),document_sha256:'b'.repeat(64),parser_version:'ocr-v1',selected_pages:[3,8]}
 const input={kind:'ocr_review',source,workflow_version:'ocr_review_v1'} as const
 const task={id:'t',project_id:'p',task_type:'review_ocr',status:'waiting_confirmation',phase:'plan',display_status:'waiting_confirmation',revision:3,current_attempt:1,created_at:'2026-10-12',updated_at:'2026-10-12',reason_code:null,error_code:null,input_version:input}
 expect(isReviewSource(source)).toBe(true);expect(isReviewSource({...source,selected_pages:[3,3]})).toBe(false)
 expect(isTask(task,'p')).toBe(true)
 expect(sameInputVersion(input,input)).toBe(true)
 expect(sameInputVersion(input,{...input,source:{...source,document_sha256:'c'.repeat(64)}})).toBe(false)
 expect(reviewBase('p /','f /')).toBe('/api/v1/projects/p%20%2F/files/f%20%2F/ocr-reviews')
})
test('candidate reads bind decisions, summary, checkpoint and task to the same source',()=>{
 const source={file_id:'f',parse_id:'parse',parse_version:2,source_sha256:'a'.repeat(64),document_sha256:'b'.repeat(64),parser_version:'ocr-v1',selected_pages:[3,8]}
 const input={kind:'ocr_review',source,workflow_version:'ocr_review_v1'}
 const task={id:'t',project_id:'p',task_type:'review_ocr',status:'waiting_confirmation',phase:'plan',display_status:'waiting_confirmation',revision:3,current_attempt:1,created_at:'2026-10-12',updated_at:'2026-10-12',reason_code:null,error_code:null,input_version:input}
 const summary={total_blocks:2,reviewed_blocks:1,unreviewed_blocks:1,accepted_blocks:1,corrected_blocks:0,unreadable_blocks:0,no_text_pages:[8]}
 const value={task,source,wait:{id:'w',kind:'ocr_review_confirmation',status:'open',task_revision:3,input_version:input,reason_code:null,error_code:null,created_at:'2026-10-12',resolved_at:null},checkpoint_id:'c',edit_revision:0,edits:[{block_id:'b',action:'accept_original'}],summary,preview_download_url:'/api/v1/tasks/t/ocr-review/preview/download',result:null}
 expect(isReviewWorkspace(value,'p','f','parse','t')).toBe(true)
 expect(isReviewWorkspace({...value,source:{...source,document_sha256:'c'.repeat(64)}},'p','f','parse','t')).toBe(false)
 expect(isReviewWorkspace({...value,preview_download_url:'https://invalid.example/preview'},'p','f','parse','t')).toBe(false)
 expect(isReviewWorkspace({...value,summary:{...summary,accepted_blocks:0,corrected_blocks:1}},'p','f','parse','t')).toBe(false)
 expect(isReviewWorkspace({...value,checkpoint_id:null},'p','f','parse','t')).toBe(false)
 expect(taskPhaseName(task as TaskView)).toBe('逐条核对')
})
