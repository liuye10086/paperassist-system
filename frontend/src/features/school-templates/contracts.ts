export type TextDecisionOption={id:'latin_font'|'heading1_line_spacing';label:string;source_text:string|null;text_value:string|null;attribute_value:Record<string,unknown>;source_sha256:string;suggested_choice:'text'|'attributes'|null;changed:boolean;choices:('text'|'attributes')[]}
export type Profile = {revision:number;school:string;department:string;major:string;degree_type:string;education_level:string;applicable_version:string;bound_confirmation_id:string|null}
export type Source = {part?:string;path?:string;text?:string}
export type Chapter = {id:string;title:string;level:number;source?:Source}
export type Fact = {id?:string;label?:string;category?:string;value?:unknown;text?:string;message?:string;source?:Source;required?:boolean}
export type Section = {id:string;page:Record<string,number>;source?:Source;different_first_page:boolean;different_odd_even_pages:boolean;page_number:{format:string|null;start:string|null;mode:string};headers:{type:string;part:string|null;text:string;fields:string[];linked_to_previous:boolean;source?:Source}[];footers:Section['headers'];break_type:string|null}
export type Analysis = {rules:Fact[];chapters:Chapter[];sections:Section[];notes:(Fact|string)[];conflicts:{id:string;label?:string;options:{id:string;value:unknown;source?:Source}[]}[];missing:(Fact|string)[];unsupported:(Fact|string)[];identity_fields:(Fact|string)[]}
export type Template = {previous_version_id?:string|null;text_decision_options?:TextDecisionOption[];id:string;name:string;school:string;version_label:string;created_at:string;task:{id:string;status:string;error_code?:string|null};analysis:Analysis|null;analysis_sha256:string|null;confirmation:{id:string;text_decisions?:{id:string;choice:string;source_sha256:string}[];chapters?:Chapter[];decisions?:{conflict_id:string;option_id:string}[];rules?:Fact[];missing?:(Fact|string)[];unsupported?:(Fact|string)[]}|null;supplement_text?:string;sources:{id:string;role:string;file_id:string;filename:string;download_url:string;sha256?:string}[]}
export const emptyProfile:Profile = {revision:0,school:'',department:'',major:'',degree_type:'',education_level:'',applicable_version:'',bound_confirmation_id:null}
export function readable(value:unknown):string {
 if(value===null||value===undefined)return '—'
 if(typeof value==='string'||typeof value==='number')return String(value)
 if(typeof value==='boolean')return value?'✓':'—'
 if(Array.isArray(value))return value.map(readable).join('；')
 if(typeof value==='object')return Object.entries(value).filter(([key])=>!['id','sha256','analysis_sha256','source'].includes(key)).map(([key,item])=>`${key}: ${readable(item)}`).join('；')
 return '—'
}
function record(value:unknown):value is Record<string,unknown>{return !!value&&typeof value==='object'&&!Array.isArray(value)}
function source(value:unknown){return value===undefined||record(value)&&['part','path','text'].every(key=>value[key]===undefined||typeof value[key]==='string')}
function fact(value:unknown){return typeof value==='string'||record(value)&&['id','category','label','text','message'].every(key=>value[key]===undefined||typeof value[key]==='string')&&source(value.source)}
function chapters(value:unknown){return Array.isArray(value)&&value.every(chapter=>record(chapter)&&typeof chapter.id==='string'&&typeof chapter.title==='string'&&Number.isInteger(chapter.level)&&source(chapter.source))}
export function isProfile(value:unknown):value is Profile{return record(value)&&Number.isSafeInteger(value.revision)&&Number(value.revision)>=0&&['school','department','major','degree_type','education_level','applicable_version'].every(key=>typeof value[key]==='string')&&(value.bound_confirmation_id===null||typeof value.bound_confirmation_id==='string')}
export function isTemplateList(value:unknown):value is {items:Template[]}{
 if(!record(value)||!Array.isArray(value.items))return false
 return value.items.every(item=>{
  if(!record(item)||!['id','name','school','version_label'].every(key=>typeof item[key]==='string')||!record(item.task)||!['queued','running','succeeded','failed'].includes(String(item.task.status))||!Array.isArray(item.sources)||!item.sources.every(file=>record(file)&&['id','role','file_id','filename'].every(key=>typeof file[key]==='string')))return false
  const saved=item.confirmation
  if(saved!==null&&(!record(saved)||typeof saved.id!=='string'||saved.chapters!==undefined&&!chapters(saved.chapters)||saved.rules!==undefined&&(!Array.isArray(saved.rules)||!saved.rules.every(fact))||saved.decisions!==undefined&&(!Array.isArray(saved.decisions)||!saved.decisions.every(decision=>record(decision)&&typeof decision.conflict_id==='string'&&typeof decision.option_id==='string'))))return false
  const analysis=item.analysis
  if(analysis===null)return true
  return record(analysis)&&['rules','notes','missing','unsupported','identity_fields'].every(key=>Array.isArray(analysis[key])&&analysis[key].every(fact))&&chapters(analysis.chapters)&&Array.isArray(analysis.sections)&&analysis.sections.every(section=>record(section)&&source(section.source)&&record(section.page)&&Object.values(section.page).every(value=>typeof value==='number')&&record(section.page_number)&&['headers','footers'].every(key=>Array.isArray(section[key])&&section[key].every(part=>record(part)&&typeof part.type==='string'&&typeof part.text==='string'&&Array.isArray(part.fields)&&part.fields.every(field=>typeof field==='string')&&source(part.source))))&&Array.isArray(analysis.conflicts)&&analysis.conflicts.every(conflict=>record(conflict)&&typeof conflict.id==='string'&&(conflict.label===undefined||typeof conflict.label==='string')&&Array.isArray(conflict.options)&&conflict.options.every(option=>record(option)&&typeof option.id==='string'&&source(option.source)))&&(typeof item.analysis_sha256==='string'&&/^[a-f0-9]{64}$/.test(item.analysis_sha256))
 })&&new Set(value.items.map(item=>item.id)).size===value.items.length
}
