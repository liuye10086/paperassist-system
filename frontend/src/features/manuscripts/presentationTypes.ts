import type {Paragraph,Snapshot} from './manuscriptTypes'
import type {SchoolExportOptions} from './schoolExportTypes'
import type {ItemDecision} from './WritingLanguageReview'
import type {InventoryItem} from './writingLiveTypes'
export type PresentationLanguageReview={source_export_id:string;source_sha256:string;language_view:PresentationBinding['language_view'];review_mode:PresentationBinding['review_mode'];decisions:(Omit<ItemDecision,'decision'>&{decision:Exclude<ItemDecision['decision'],''>;location:string;content_sha256:string})[]}
export type PresentationItemConfirmation=Omit<PresentationLanguageReview['decisions'][number],'location'>&{status:'confirmed_for_exact_output';source_export_id:string;source_sha256:string}
export type PresentationLanguageItem=InventoryItem&{kind:'export_text'|'image'|'figure_text';target_language:'zh-CN'|'en';protected_identity?:boolean;language_known?:boolean;no_text?:boolean;verification?:'pending_manual_review';finite_check?:{status:'passed'|'pending'|'conflict';message:string};confirmation?:PresentationItemConfirmation}
export type PresentationCheck={code:string;status:'passed'|'pending'|'conflict';message:string;group_id?:string}
export const statementLabels={funding:'基金资助',ethics:'伦理',registration:'研究注册',conflict:'利益冲突',data_availability:'数据可用性'} as const
export type PresentationConfig={
 guide_version_id?:string|null
 language_review?:PresentationLanguageReview|null
 paragraph_groups:{id:string;zh_ids:string[];en_ids:string[];status:'paired'|'missing'|'unpaired'}[]
 terminology:{zh:string;en:string;variants:string[];source:string;state:'known'|'pending'}[]
 figure_pairs:{figure_id:string;zh_figure_id:string;en_figure_id:string;caption_identity:string;source:string;language_status:'known'|'pending'}[]
 authors:{name:string;order:number;corresponding:boolean;affiliation_ids:string[];source:string}[]
 affiliations:{id:string;name:string;source:string}[]
 statements:{kind:keyof typeof statementLabels;state:'known'|'pending'|'not_applicable';text:string;source:string;reason:string}[]
 school:null|{options:SchoolExportOptions;supplements:{chapter_id:string;purpose:'abbreviations'|'appendix'|'achievements'|'acknowledgements';required:boolean;source:string}[];include_chapter_ids:string[];exclude_chapter_ids:string[];length_requirements:{kind:'minimum'|'maximum';value:number;scope:'body'|'abstract'|'whole';language:'zh-CN'|'en';unit:'words'|'characters';source:string}[];guide_version_id:string|null}
 blind:{identity_terms:string[];hidden_chapter_ids:string[];exceptions:{term:string;reason:string}[];manual_image_review:boolean}
}
export type PresentationPreview={schema_version:1;base_version_id:string;peer_version_id:string|null;config:PresentationConfig;checks:PresentationCheck[];journal_check?:{guide_id:string;guide_sha256:string;requirements_version:string};paragraph_groups:{id:string;zh:Paragraph[];en:Paragraph[];status:string}[];quality:{scientific_semantic:'pending';word_wps:'pending';real_compliance:'pending'};can_export:boolean}
export type SavedPresentation=PresentationPreview&{id:string;manuscript_id:string;revision:number;created_at:string;stale:boolean;stale_version_ids:string[]}
export type PresentationBinding={presentation_version_id:string;language_view:'zh-CN'|'en'|'zh-CN-en';review_mode:'identified'|'blind'}
export type BlindReceipt={known_identity_check:'passed'|'pending';remaining:{part:string;terms:string[]}[];images:'pending_manual_review'|'user_confirmed'|'not_present';exceptions:unknown[];anonymity_verified:false}
export type PresentationExport={binding:PresentationBinding&Record<string,unknown>;checks:PresentationCheck[];quality?:Record<string,unknown>;blind?:BlindReceipt|null;language_inventory?:PresentationLanguageItem[];language_review?:(PresentationLanguageReview&{status?:'confirmed';inventory_sha256?:string;decision_count?:number;source_checks?:PresentationCheck[]})|null}
export type PresentationOutputPreview={binding:PresentationBinding&Record<string,unknown>;checks:PresentationCheck[];quality:Record<string,unknown>;preview_paragraphs:{id:string;text:string;target_language:string}[];notice:string}
export function validPresentationExport(v:unknown):v is PresentationExport{if(!v||typeof v!=='object')return false;const r=v as PresentationExport;return !!r.binding&&typeof r.binding.presentation_version_id==='string'&&['zh-CN','en','zh-CN-en'].includes(r.binding.language_view)&&['identified','blind'].includes(r.binding.review_mode)&&Array.isArray(r.checks)&&r.checks.every(c=>typeof c.code==='string'&&typeof c.message==='string'&&['passed','pending','conflict'].includes(c.status))}
export function emptyPresentation():PresentationConfig{return {paragraph_groups:[],terminology:[],figure_pairs:[],authors:[],affiliations:[],statements:(Object.keys(statementLabels) as (keyof typeof statementLabels)[]).map(kind=>({kind,state:'pending',text:'',source:'',reason:''})),school:null,blind:{identity_terms:[],hidden_chapter_ids:[],exceptions:[],manual_image_review:false}}}
export function normalizePresentationConfig(config:PresentationConfig){const fixed=structuredClone(config);fixed.terminology=fixed.terminology.map(term=>({...term,variants:term.variants.map(value=>value.trim()).filter(Boolean)}));fixed.blind.identity_terms=fixed.blind.identity_terms.map(value=>value.trim()).filter(Boolean);return fixed}
export function snapshotParagraphs(snapshot:Snapshot){const found=new Map<string,{id:string;text:string;chapter:string}>();for(const section of snapshot.sections??[])for(const p of section.paragraphs)found.set(p.id,{...p,chapter:section.title??section.id});for(const p of snapshot.methods)if(!found.has(p.id))found.set(p.id,{...p,chapter:'materials_and_methods'});for(const group of snapshot.results_groups)for(const p of group.paragraphs)if(!found.has(p.id))found.set(p.id,{...p,chapter:group.title});return [...found.values()]}
export function validPresentation(v:unknown,baseId?:string):v is PresentationPreview{
 if(!v||typeof v!=='object')return false;const r=v as PresentationPreview
 return r.schema_version===1&&typeof r.base_version_id==='string'&&(!baseId||r.base_version_id===baseId)&&(r.peer_version_id===null||typeof r.peer_version_id==='string')&&!!r.config&&Array.isArray(r.config.paragraph_groups)&&Array.isArray(r.config.statements)&&!!r.config.blind&&Array.isArray(r.checks)&&r.checks.every(c=>typeof c.code==='string'&&typeof c.message==='string'&&['passed','pending','conflict'].includes(c.status))&&Array.isArray(r.paragraph_groups)&&r.paragraph_groups.every(g=>typeof g.id==='string'&&Array.isArray(g.zh)&&Array.isArray(g.en))&&typeof r.can_export==='boolean'&&r.quality?.scientific_semantic==='pending'&&r.quality.word_wps==='pending'&&r.quality.real_compliance==='pending'
}
export function validSavedPresentation(v:unknown,manuscriptId:string):v is SavedPresentation{if(!validPresentation(v))return false;const r=v as SavedPresentation;return typeof r.id==='string'&&r.manuscript_id===manuscriptId&&Number.isInteger(r.revision)&&r.revision>0&&typeof r.stale==='boolean'&&Array.isArray(r.stale_version_ids)}
