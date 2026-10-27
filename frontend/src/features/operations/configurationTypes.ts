export const configurationDomains = ['models','prompts','ncbi','basic','journals','schools','review'] as const
export type ConfigDomain = typeof configurationDomains[number]
export const modelBusinesses = ['explanation','recommendation','plot','writing','literature'] as const
export type ModelBusiness = typeof modelBusinesses[number]
export const reviewCategories = ['experiment','statistics','figure','method','literature','format','structure','expression','uncategorized'] as const
export type ReviewCategory = typeof reviewCategories[number]
export type SecretReference = {alias:string;revision:string}
export type ConfigPrice = {version:string;currency:'USD';model:string;input_micro_usd_per_million:number;cached_input_micro_usd_per_million:number;output_micro_usd_per_million:number;cache_write_micro_usd_per_million:number|null}
export type ConfigPolicy = {model:string;prompt_version:string;max_output_tokens:number;timeout_seconds:number;tools:('code_interpreter')[];output_format:string;price:ConfigPrice}
export type ModelEntry = {execution:{policy:ConfigPolicy;input_token_allowance:number;task_limit_micro_usd:number;tool_reserve_micro_usd?:number;tool_reserve_version?:string};price_source:'installed_code'|'deployment_policy'|'synthetic_fixture';price_status:'unverified'|'synthetic';price_verified_on:string|null}
export type BasicConfiguration = {max_upload_bytes:number;max_uncompressed_bytes:number;max_sheets:number;max_rows:number;max_columns:number;max_cells:number;worker_concurrency:1|2}
export type ConfigBundle = {
 schema_version:1
 models:Record<ModelBusiness,ModelEntry|null>&{writing:ModelEntry;credential:SecretReference|null;real_calls_enabled:false;batch_max_posts:number;max_corrections:number;batch_cap_micro_usd:number}
 prompts:{writing_template:string;workflow:string;writing_instruction:string;explanation_instruction:string;recommendation_instruction:string;plot_instruction:string;literature_instruction:string}
 ncbi:{identity:SecretReference|null;enabled:false;interval_seconds:number;cache_ttl_seconds:number;timeout_seconds:number}
 basic:BasicConfiguration
 journals:{source_mode:'local_only';metrics_enabled:false;update_mode:'manual';recommendation_version:string;format_version:string;default_count:number;max_count:number;source_label:string;update_plan:string;update_result:'not_started'|'recorded'|'failed';update_note:string;require_verification:true}
 schools:{parser_version:string;quality_version:string;formats:['docx'];conflict_policy:'require_confirmation';heading_aliases:{text:string;role:'heading1'|'heading2'|'heading3'|'body'}[]}
 review:{category_order:ReviewCategory[];keywords:Record<ReviewCategory,string[]>;handling_notes:Record<ReviewCategory,string>;default_language:'zh-CN'|'en';document_version:string;require_confirmation:true}
}
export type ConfigurationValidation={id:string;version_id:string;sha256:string;validator_version:string;capability_version:string;status:'passed'|'failed';domains:Partial<Record<ConfigDomain,{status:'passed'|'failed';mode:'validated'|'reused';errors:string[];scope:string[]}>>;real_connectivity:'not_tested';checked:string[];not_checked:string[]}
export type ConfigurationVersion={id:string;parent_id:string|null;sha256:string;bundle:ConfigBundle;sources:Partial<Record<ConfigDomain,string>>;created_at:string;validations?:ConfigurationValidation[]}
export type VersionSummary=Omit<ConfigurationVersion,'bundle'|'validations'>
export type ConfigurationEvent={id:string;actor_user_id?:string;operation:'activate'|'rollback';reason:string;before_version_id:string|null;after_version_id:string;revision:number;created_at:string}
export type ConfigCatalog={default_bundle:ConfigBundle;sources:Partial<Record<ConfigDomain,string>>;schema:unknown;capability_version:string;validator_version:string;effects:Record<ConfigDomain,string>;field_effects:Record<string,string>;field_readonly:Record<string,boolean>;restart_required:Record<string,boolean>;effective_ranges:Record<string,{minimum:number;maximum:number;unit:string}>;installed:{journal_sources?:import('./JournalSourceVerification').JournalSource[];models:string[];tools:string[];workflows?:{id:string;editable:boolean;nodes:string[]}[];templates?:string[];business_constraints:Partial<Record<ModelBusiness,{model?:string;prompt_version?:string;output_format?:string;tools?:string[];policy_editable?:boolean}>>;supported_schools:string[];school_quality_rules:string[];school_support_status:string};real_connectivity:'not_tested'}
export type ConfigurationCurrent={revision:number;version:ConfigurationVersion|null}
export type ConfigDiff={version_id:string;against:string|null;changes:{path:string;before:unknown;after:unknown}[]}
export type ConfigBinding={status:'bound'|'legacy_unbound';version_id:string|null;sha256:string|null}
export const domainNames:Record<ConfigDomain,string>={models:'模型、工具与价格',prompts:'有限说明与工作流',ncbi:'NCBI',basic:'基础参数',journals:'期刊规则',schools:'学校模板规则',review:'审稿与评审规则'}
export const businessNames:Record<ModelBusiness,string>={explanation:'结果解释',recommendation:'分析建议',plot:'模型绘图',writing:'论文写作',literature:'文献辅助'}
export const categoryNames:Record<ReviewCategory,string>={experiment:'实验',statistics:'统计',figure:'图表',method:'方法',literature:'文献',format:'格式',structure:'结构',expression:'表达',uncategorized:'未分类'}
export const basicFields = [
 ['max_upload_bytes','上传文件上限（字节）',10485760],['max_uncompressed_bytes','解压后上限（字节）',67108864],['max_sheets','最大工作表数（张）',50],['max_rows','最大行数（行）',100000],['max_columns','最大列数（列）',256],['max_cells','最大单元格数（个）',1000000],
] as const
export const configurationFieldNames:Record<string,string>={model:'模型名称',prompt_version:'提示词版本',output_format:'输出格式',max_output_tokens:'输出 Token 上限',timeout_seconds:'请求超时（秒）',input_token_allowance:'输入 Token 预算',task_limit_micro_usd:'任务预算上限（微美元）',tool_reserve_micro_usd:'工具预留（微美元）',batch_max_posts:'批次提交上限（次）',max_corrections:'最多纠正次数',batch_cap_micro_usd:'批次预算上限（微美元）',input_micro_usd_per_million:'输入价格（微美元/百万 Token）',cached_input_micro_usd_per_million:'缓存输入价格（微美元/百万 Token）',output_micro_usd_per_million:'输出价格（微美元/百万 Token）',cache_write_micro_usd_per_million:'缓存写入价格（微美元/百万 Token）',price_status:'价格核实状态',price_source:'价格来源',price_verified_on:'价格核实日期',writing_instruction:'有限说明段',explanation_instruction:'有限说明段',recommendation_instruction:'有限说明段',plot_instruction:'有限说明段',literature_instruction:'有限说明段',interval_seconds:'请求间隔（秒）',cache_ttl_seconds:'缓存有效期（秒）',default_count:'默认建议数量',max_count:'最多建议数量',source_label:'来源安全标签',update_plan:'人工更新计划',update_result:'人工更新结果',update_note:'人工更新说明',heading_aliases:'字面标题映射',default_language:'默认文档语言',category_order:'审稿与评审规则',keywords:'字面关键词',handling_notes:'处理说明'}
export const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)
export function isBundle(value:unknown):value is ConfigBundle {
 if(!object(value)||value.schema_version!==1||!configurationDomains.every(k=>object(value[k])))return false
 const b=value as unknown as ConfigBundle
 return b.models.real_calls_enabled===false&&b.ncbi.enabled===false&&(b.basic.worker_concurrency===1||b.basic.worker_concurrency===2)&&basicFields.every(([k])=>Number.isSafeInteger(b.basic[k])&&b.basic[k]>0)
  &&b.journals.require_verification===true&&b.schools.conflict_policy==='require_confirmation'&&Array.isArray(b.schools.heading_aliases)
  &&b.review.require_confirmation===true&&Array.isArray(b.review.category_order)&&b.review.category_order.length===9&&new Set(b.review.category_order).size===9&&reviewCategories.every(k=>b.review.category_order.includes(k)&&Array.isArray(b.review.keywords?.[k])&&typeof b.review.handling_notes?.[k]==='string')
  &&modelBusinesses.every(k=>b.models[k]===null||object(b.models[k])&&object(b.models[k]?.execution)&&object(b.models[k]?.execution.policy)&&object(b.models[k]?.execution.policy.price))
}
export function isVersion(value:unknown):value is ConfigurationVersion {return object(value)&&typeof value.id==='string'&&typeof value.sha256==='string'&&typeof value.created_at==='string'&&(value.parent_id===null||typeof value.parent_id==='string')&&object(value.sources)&&isBundle(value.bundle)}
export function isCatalog(value:unknown):value is ConfigCatalog {return object(value)&&isBundle(value.default_bundle)&&typeof value.capability_version==='string'&&typeof value.validator_version==='string'&&object(value.effects)&&object(value.field_effects)&&object(value.field_readonly)&&object(value.effective_ranges)&&object(value.installed)&&Array.isArray(value.installed.models)&&Array.isArray(value.installed.tools)&&object(value.installed.business_constraints)&&Array.isArray(value.installed.supported_schools)}
export function validationMatches(v:ConfigurationValidation|undefined,version:ConfigurationVersion,catalog:ConfigCatalog){return !!v&&v.status==='passed'&&v.version_id===version.id&&v.sha256===version.sha256&&v.capability_version===catalog.capability_version&&v.validator_version===catalog.validator_version}

export function effectName(effect:string){return ({new_task:'对新任务生效',new_request:'对新请求生效',new_round:'对新轮次生效',new_preview_bundle:'对新预览包生效',readonly:'只读参数',worker_restart:'对 Worker 显式重启后生效'} as Record<string,string>)[effect]??'未知'}
