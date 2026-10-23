export type Mapping={input_section_id:string;chapter_id:string}
export type SchoolChange={
 id:string;kind:'template_migration'|'docx_return';manuscript_id:string;base_version_id:string;base_revision:number;created_at:string;input_sha256:string
 source:{target_confirmation_id?:string;file_id?:string;document_version_id?:string;base_export_id?:string|null;sha256?:string;filename?:string}
 original_download_url:string|null
 input_sections:{id:string;title:string;paragraphs:string[];suggested_chapter_id:string|null;match_method:'bookmark'|'title'|'none'|'ambiguous';candidate_chapter_ids:string[]}[]
 target_chapters:{id:string;title:string;level:number;purpose:string;output_language:string;result_group_ids:string[]}[]
 mappings:Mapping[];differences:{kind:string;location:string;message:string;before:string;after:string}[]
 issues:{code:string;severity:'error'|'warning';message:string;location:string}[];can_adopt:boolean;preview_sha256:string;adopted_revision:number|null
}
function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&!Array.isArray(v)}
const strings=(v:unknown):v is string[]=>Array.isArray(v)&&v.every(x=>typeof x==='string')
export function isSchoolChange(v:unknown):v is SchoolChange{
 return record(v)&&typeof v.id==='string'&&['template_migration','docx_return'].includes(String(v.kind))&&typeof v.manuscript_id==='string'&&typeof v.base_version_id==='string'&&Number.isSafeInteger(v.base_revision)&&typeof v.created_at==='string'&&typeof v.input_sha256==='string'&&record(v.source)&&(v.original_download_url===null||typeof v.original_download_url==='string')&&
 Array.isArray(v.input_sections)&&v.input_sections.every(s=>record(s)&&typeof s.id==='string'&&typeof s.title==='string'&&strings(s.paragraphs)&&strings(s.candidate_chapter_ids)&&['bookmark','title','none','ambiguous'].includes(String(s.match_method)))&&
 Array.isArray(v.target_chapters)&&v.target_chapters.every(c=>record(c)&&typeof c.id==='string'&&typeof c.title==='string')&&Array.isArray(v.mappings)&&v.mappings.every(m=>record(m)&&typeof m.input_section_id==='string'&&typeof m.chapter_id==='string')&&
 Array.isArray(v.differences)&&v.differences.every(d=>record(d)&&['kind','location','message','before','after'].every(k=>typeof d[k]==='string'))&&Array.isArray(v.issues)&&v.issues.every(i=>record(i)&&typeof i.code==='string'&&typeof i.message==='string'&&['error','warning'].includes(String(i.severity)))&&typeof v.can_adopt==='boolean'&&typeof v.preview_sha256==='string'&&/^[a-f0-9]{64}$/.test(v.preview_sha256)&&(v.adopted_revision===null||Number.isSafeInteger(v.adopted_revision))
}
export const isChangeList=(v:unknown):v is {items:SchoolChange[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(isSchoolChange)
