import type { StructureCell } from '../datasets/datasetApi'
export type EvidenceKind='document_version'|'dataset_version'|'prepared_dataset_version'
export type EvidenceLocation={part?:string|null;path?:string|null;label?:string|null;page_number?:number|null;bbox?:number[]|null;polygon?:number[][]|null;coordinate_system?:string|null;sheet_index?:number|null;sheet_name?:string|null;coordinate?:string|null;row?:number|null;column?:number|null;container_id?:string|null}
export type EvidenceValue={kind:string;typed:string|boolean|null;raw_available:boolean;original_typed:string|boolean|null;raw_source_version_id:string|null;raw_type:string|null;raw:string|null;number_format:string|null;formula:StructureCell['formula'];unit:{status:'unconfirmed'|'confirmed';value:string|null}}
export type EvidenceItem={id:string;kind:'text'|'table'|'cell'|'field'|'row'|'image';location:EvidenceLocation;text:string|null;value:EvidenceValue|null;cells:{location:EvidenceLocation;value:EvidenceValue}[];rows:number|null;columns:number|null;image_id:string|null;preview_url:string|null;associations:{status:'candidate';basis:'adjacent_same_container'|'nearest_same_page';caption_id:string;caption_text:string;caption_source:EvidenceLocation;target_id:string;target_source:EvidenceLocation}[];uncertainties:string[]}
export type EvidenceWarning={code:string;message:string;count:number;scope:'document'|'page';pages:number[];location:EvidenceLocation|null}
export type Evidence={schema_version:1;source:{project_id:string;file_id:string;version_id:string;version:number;kind:EvidenceKind;filename:string;sha256:string;source_sha256:string;parent_version_id:string|null;parent_object_download_url:string|null;original_download_url:string;object_download_url:string};format:'docx'|'pdf'|'ocr'|'xlsx'|'prepared_xlsx';parser_version:string;scope:{kind:'document'|'sheet';sheet_index?:number|null;sheet_name?:string|null;stored_range?:string|null;content_range?:string|null;data_range?:string|null;pages:number[]};counts:Record<string,number>;count_semantics:'stored_evidence_not_research_n';pagination:{page:number;page_size:20;total:number;returned:number;has_more:boolean};items:EvidenceItem[];uncertainties:string[];warnings:EvidenceWarning[]}
export type EvidenceTarget={projectId:string;fileId:string;versionId:string;kind:EvidenceKind}
export function evidenceBase(target:EvidenceTarget) {
 const base=`/api/v1/projects/${encodeURIComponent(target.projectId)}/files/${encodeURIComponent(target.fileId)}`
 const suffix=target.kind==='document_version'?'document-versions':target.kind==='dataset_version'?'dataset-versions':'prepared-dataset-versions'
 return {base,version:`${base}/${suffix}/${encodeURIComponent(target.versionId)}`}
}
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const text=(v:unknown):v is string=>typeof v==='string'
const nullableText=(v:unknown)=>v===null||text(v)
const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0
const strings=(v:unknown)=>Array.isArray(v)&&v.every(text)
const finite=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)
function location(v:unknown) {
 return record(v)&&['part','path','label','sheet_name','coordinate','container_id','coordinate_system'].every(k=>v[k]===undefined||nullableText(v[k]))
 &&['page_number','sheet_index','row','column'].every(k=>v[k]===undefined||v[k]===null||integer(v[k]))
 &&(v.bbox===undefined||v.bbox===null||Array.isArray(v.bbox)&&v.bbox.length===4&&v.bbox.every(finite))
 &&(v.polygon===undefined||v.polygon===null||Array.isArray(v.polygon)&&v.polygon.length===4&&v.polygon.every(p=>Array.isArray(p)&&p.length===2&&p.every(finite)))
}
function value(v:unknown) {
 if(!record(v)||!text(v.kind)||!(v.typed===null||text(v.typed)||typeof v.typed==='boolean')||typeof v.raw_available!=='boolean'||!nullableText(v.raw_type)||!nullableText(v.raw)||!nullableText(v.number_format)||!record(v.unit))return false
 if(!nullableText(v.raw_source_version_id)||!(v.original_typed===null||text(v.original_typed)||typeof v.original_typed==='boolean'))return false
 if(!(v.unit.status==='unconfirmed'&&v.unit.value===null||v.unit.status==='confirmed'&&text(v.unit.value)))return false
 return v.formula===null||record(v.formula)&&nullableText(v.formula.text)&&record(v.formula.attributes)&&Object.values(v.formula.attributes).every(text)&&['missing','empty','present'].includes(String(v.formula.cache_state))&&nullableText(v.formula.cached_type)&&nullableText(v.formula.cached_value)&&v.formula.cache_validity==='unverified'
}
export function isEvidence(v:unknown,target:EvidenceTarget,page:number):v is Evidence {
 const {base,version}=evidenceBase(target)
 if(!record(v)||v.schema_version!==1||!record(v.source)||v.source.project_id!==target.projectId||v.source.file_id!==target.fileId||v.source.version_id!==target.versionId||v.source.kind!==target.kind||!integer(v.source.version)||v.source.version<1||!text(v.source.filename)||!text(v.source.sha256)||!/^[0-9a-f]{64}$/.test(v.source.sha256)||v.source.original_download_url!==base+'/download'||v.source.object_download_url!==version+'/download')return false
 if(!text(v.source.source_sha256)||!/^[0-9a-f]{64}$/.test(v.source.source_sha256)||!nullableText(v.source.parent_version_id)||(v.source.parent_version_id===null?v.source.parent_object_download_url!==null:v.source.parent_object_download_url!==base+'/dataset-versions/'+encodeURIComponent(v.source.parent_version_id)+'/download'))return false
 if(!['docx','pdf','ocr','xlsx','prepared_xlsx'].includes(String(v.format))||!text(v.parser_version)||!record(v.scope)||!['document','sheet'].includes(String(v.scope.kind))||!Array.isArray(v.scope.pages)||!v.scope.pages.every(integer)||!record(v.counts)||!Object.values(v.counts).every(integer)||v.count_semantics!=='stored_evidence_not_research_n'||!strings(v.uncertainties))return false
 if(!Array.isArray(v.warnings)||!v.warnings.every(w=>record(w)&&text(w.code)&&text(w.message)&&integer(w.count)&&['document','page'].includes(String(w.scope))&&Array.isArray(w.pages)&&w.pages.length<=100&&w.pages.every(n=>integer(n)&&n>0)&&(w.scope==='document'?w.location===null:w.pages.length===1&&location(w.location)&&record(w.location)&&w.location.page_number===w.pages[0])))return false
 const scope=v.scope
 if(!['sheet_name','stored_range','content_range','data_range'].every(k=>scope[k]===undefined||nullableText(scope[k]))||(scope.sheet_index!==undefined&&scope.sheet_index!==null&&!integer(scope.sheet_index)))return false
 if(!record(v.pagination)||v.pagination.page!==page||v.pagination.page_size!==20||!integer(v.pagination.total)||!integer(v.pagination.returned)||typeof v.pagination.has_more!=='boolean'||!Array.isArray(v.items)||v.items.length>20||v.items.length!==v.pagination.returned||v.pagination.has_more!==(page*20<v.pagination.total))return false
 return v.items.every(i=>record(i)&&text(i.id)&&['text','table','cell','field','row','image'].includes(String(i.kind))&&location(i.location)&&nullableText(i.text)&&(i.value===null||value(i.value))&&Array.isArray(i.cells)&&i.cells.length<=256&&i.cells.every(c=>record(c)&&location(c.location)&&value(c.value))&&[i.rows,i.columns].every(n=>n===null||integer(n))&&nullableText(i.image_id)&&(i.preview_url===null||text(i.preview_url)&&i.preview_url===version+'/images/'+encodeURIComponent(String(i.image_id)))&&strings(i.uncertainties)&&Array.isArray(i.associations)&&i.associations.every(a=>record(a)&&a.status==='candidate'&&['adjacent_same_container','nearest_same_page'].includes(String(a.basis))&&text(a.caption_id)&&text(a.caption_text)&&location(a.caption_source)&&a.target_id===i.id&&location(a.target_source)))
}
