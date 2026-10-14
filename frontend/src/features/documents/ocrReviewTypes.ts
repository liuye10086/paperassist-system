export type ReviewSource = {file_id:string;parse_id:string;parse_version:number;source_sha256:string;document_sha256:string;parser_version:string;selected_pages:number[]}
export type ReviewInputVersion = {kind:'ocr_review';source:ReviewSource;workflow_version:'ocr_review_v1';setup_revision?:never;output_language?:never}
export type ReviewEdit = {block_id:string;action:'accept_original'|'unreadable';text?:never}|{block_id:string;action:'replace_text';text:string}
export type ReviewSummary = {total_blocks:number;reviewed_blocks:number;unreviewed_blocks:number;accepted_blocks:number;corrected_blocks:number;unreadable_blocks:number;no_text_pages:number[]}
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const text=(v:unknown):v is string=>typeof v==='string'&&v.length>0
const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0
export function isReviewSource(v:unknown):v is ReviewSource {
 return record(v)&&text(v.file_id)&&text(v.parse_id)&&integer(v.parse_version)&&v.parse_version>=1&&text(v.source_sha256)&&/^[a-f0-9]{64}$/.test(v.source_sha256)&&text(v.document_sha256)&&/^[a-f0-9]{64}$/.test(v.document_sha256)&&text(v.parser_version)&&Array.isArray(v.selected_pages)&&v.selected_pages.length>=1&&v.selected_pages.length<=10&&v.selected_pages.every(p=>integer(p)&&p>=1&&p<=100)&&new Set(v.selected_pages).size===v.selected_pages.length
}
export function sameReviewSource(a:ReviewSource,b:ReviewSource) {
 return a.file_id===b.file_id&&a.parse_id===b.parse_id&&a.parse_version===b.parse_version&&a.source_sha256===b.source_sha256&&a.document_sha256===b.document_sha256&&a.parser_version===b.parser_version&&a.selected_pages.length===b.selected_pages.length&&a.selected_pages.every((p,i)=>p===b.selected_pages[i])
}
export function isReviewEdits(v:unknown):v is ReviewEdit[] {
 if(!Array.isArray(v)||!v.every(e=>record(e)&&text(e.block_id)&&(['accept_original','unreadable'].includes(String(e.action))?!('text' in e):e.action==='replace_text'&&typeof e.text==='string'&&e.text.trim().length>0&&e.text.length<=20000)))return false
 return new Set(v.map(e=>e.block_id)).size===v.length&&v.reduce((n,e)=>n+(e.action==='replace_text'?new TextEncoder().encode(e.text).length:0),0)<=4*1024*1024
}
export function isReviewSummary(v:unknown):v is ReviewSummary {
 return record(v)&&['total_blocks','reviewed_blocks','unreviewed_blocks','accepted_blocks','corrected_blocks','unreadable_blocks'].every(k=>integer(v[k]))&&Number(v.total_blocks)===Number(v.reviewed_blocks)+Number(v.unreviewed_blocks)&&Number(v.reviewed_blocks)===Number(v.accepted_blocks)+Number(v.corrected_blocks)+Number(v.unreadable_blocks)&&Array.isArray(v.no_text_pages)&&v.no_text_pages.every(p=>integer(p)&&p>=1&&p<=100)&&new Set(v.no_text_pages).size===v.no_text_pages.length
}
