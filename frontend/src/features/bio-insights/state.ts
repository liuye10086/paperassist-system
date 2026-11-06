import type {CandidateStep,Config,Contrast,InsightKind,Observation,PlanBody,Source,ResourceBody} from './contracts'
export const strings=(v:unknown):string[]=>Array.isArray(v)?v.filter((s):s is string=>typeof s==='string'):[]
export const text=(v:unknown)=>typeof v==='string'?v:''
export const number=(v:unknown,fallback=0)=>typeof v==='number'?v:fallback
export const split=(v:string)=>v.split(/[\n,，]+/).map(s=>s.trim()).filter(Boolean)
export function displayRaw(v:unknown):string{return v===null||v===undefined?'NA（空值）':typeof v==='object'?JSON.stringify(v):String(v)}
export function selectObservations(rows:Observation[],field:string,value:string){return rows.filter(r=>r.retained!==false&&String(r[field]??'')===value).map(r=>({processed_version_id:r.processed_version_id,barcode:r.barcode}))}
export function defaultConfig(kind:InsightKind):Config{
 const common={kind,output_language:'zh-CN' as const}
 switch(kind){
 case 'integration':return{...common,processed_source_ids:[],sample_mapping_source_id:null,object_mapping_source_id:null,pairs:[],concordances:[],mode:'descriptive',method:'pearson',analysis_layer:'analysis',missing_rule:'pairwise_complete_finite',transform:'none',alternative:'two-sided',correction:'BH',seed:1729,mapping_confirmed:false,partial_subset_confirmed:false,independence_confirmed:false,independence_basis:''}
 case 'feature_extract':return{...common,resource_source_ids:[],structure_selections:[],steps:[],rank_field:null,rank_direction:'descending'}
 case 'comparison':return{...common,mode:'spot_exploratory',contrasts:[{contrast_id:'contrast_1',name:'区域 A 相对区域 B',numerator:{label:'A',observation_keys:[]},denominator:{label:'B',observation_keys:[]}}],family_contrast_ids:['contrast_1'],species_taxon_id:9606,namespace:'ensembl_gene_id',reference_version:'',mapping_confirmed:false,independence_confirmed:false,independence_basis:'',batch_adjustment:false,data_driven_grouping:true,excluded_observations:[],excluded_donors:[],minimum_total_counts:10,purpose:''}
 case 'result_import':return{...common,file_source_id:'',parse_version_id:'',species_taxon_id:9606,namespace:'ensembl_gene_id',reference_version:'',columns:{feature_id:'feature_id',effect:'effect_value',p_value:'p_value',q_value:'q_value'},contrast_id:'contrast_1',numerator:'A',denominator:'B',effect_name:'external_effect',effect_unit:'',observation_level:'unknown',inference_scope:'external_result',original_method:'',original_correction_scope:'',complete_tested_universe:false,recompute_q:false,duplicate_policy:'error',na_values:['','NA','N/A','null']}
 case 'ora':return{...common,result_source_ids:[],resource_source_ids:[],mapping_source_ids:[],contrast_ids:['contrast_1'],direction:'both',q_column:'q_within_contrast',q_threshold:0.05,minimum_absolute_effect:1,min_size:15,max_size:500,merge_collections:false}
 case 'gsea_prerank':return{...common,result_source_id:'',resource_source_ids:[],mapping_source_ids:[],contrast_id:'contrast_1',ranking_column:'statistic',complete_ranking:true,signed_ranking:true,min_size:15,max_size:500,permutation_num:1000,weight:1,seed:0}
 case 'candidate':return{...common,result_source_ids:[],mapping_source_ids:[],annotation_source_ids:[],primary_result_source_id:'',source_contrasts:{},steps:[{operation:'threshold',source_ids:[],q_column:'q_within_contrast',q_threshold:0.05,minimum_absolute_effect:1}],ranking_mode:'lexicographic',weights:[]}
 case 'figure':return{...common,result_source_id:'',result_source_ids:[],figure_type:'volcano',contrast_id:'contrast_1',title:'',top_n:30,width_inches:7,height_inches:5,dpi:300,formats:['png','tiff','svg'],palette:['#2563eb','#dc2626']}
 }
}
export function buildPlan(name:string,config:Config,sources:Source[],revision:number,decision:PlanBody['decision']):PlanBody{
 const normalized={...config};for(const key of ['sheet','foreground_member_key','background_source_id','background_member_key','processed_source_id','member_key','contrast_id','x_column','y_column','q_column','term_row_key','figure_stratum'])if(normalized[key]==='')delete normalized[key]
 if(config.kind==='comparison'&&config.schema_version!==5)normalized.family_contrast_ids=(Array.isArray(config.contrasts)?config.contrasts as Contrast[]:[]).map(c=>c.contrast_id)
 if(config.kind==='candidate'&&config.schema_version!==2){if(config.ranking_mode==='lexicographic')normalized.weights=[];const ids=strings(config.result_source_ids),contrasts=config.source_contrasts as Record<string,string>|undefined;normalized.source_contrasts=Object.fromEntries(ids.map(id=>[id,contrasts?.[id]??'']))}
 return{name,kind:config.kind,decision,expected_revision:revision,sources:sources.map(s=>({source_kind:s.source_kind,source_id:s.source_id,sha256:s.sha256,role:s.role,locator:s.locator})),config:normalized}
}
export function validateRecipe(config:{result_source_ids:unknown;primary_result_source_id:unknown;steps:unknown}){
 const ids=strings(config.result_source_ids),steps=(Array.isArray(config.steps)?config.steps:[]) as CandidateStep[],issues:string[]=[]
 if(ids.length>10||steps.length>20)issues.push('最多选择 10 个来源、20 个顺序步骤。')
 if(steps.some(s=>s.source_ids?.some(id=>!ids.includes(id))))issues.push('步骤引用了未选择的结果来源。')
 if(!ids.includes(text(config.primary_result_source_id)))issues.push('请选择已加入的主比较结果。')
 return issues
}
export function planIssues(config:Config):string[]{
 const issues:string[]=[]
 if(config.kind==='comparison'&&config.schema_version===5){if(!text(config.processed_source_id)||!text(config.annotation_source_id)||!strings(config.label_ids).length)issues.push('请选择固定单细胞处理版本、人工注释版本和标签。');if(!text(config.numerator)||!text(config.denominator)||(config.mode!=='descriptive'&&config.numerator===config.denominator))issues.push('请选择两个不同的条件。')}
 else if(config.kind==='comparison'&&config.schema_version===4){if(!text(config.processed_source_id)||!text(config.measurement_pipeline)||!text(config.classification_database)||!text(config.classification_version)||!text(config.host_identity)||!text(config.feature_identity))issues.push('微生物组需要固定处理版本、测量流程、分类数据库版本和宿主／特征身份。');if(!Array.isArray(config.contrasts)||!strings(config.alpha_metrics).length)issues.push('微生物组需要有效预设对比与 alpha 指标。')}
 else if(config.kind==='comparison'&&config.schema_version===3){if(!text(config.file_source_id)||!text(config.parse_version_id)||!text(config.reference_version)||!text(config.reference_basis)||config.independence_confirmed!==true)issues.push('qPCR 需要原始长表、解析版本、assay 参考版本、内参依据与生物学单位确认。');if(config.quantification==='delta_delta_cq'&&(config.equal_efficiency_confirmed!==true||!text(config.equal_efficiency_basis)))issues.push('qPCR 等效率方法需要明确适用性确认与依据。');if(!Array.isArray(config.excluded_wells)||!Array.isArray(config.original_checks))issues.push('qPCR 排除和原报告核对必须是有效 JSON 数组。')}
 else if(config.kind==='comparison'&&config.schema_version===2){if(!text(config.reference_version).trim()||!text(config.namespace).trim())issues.push('请显式填写特征命名空间和参考版本。')}
 else if(['comparison','result_import'].includes(config.kind)&&(!text(config.reference_version).trim()||!text(config.namespace).trim()||number(config.species_taxon_id)<1))issues.push('请显式填写物种、特征命名空间和参考版本；系统不会按基因名猜测。')
 if(config.kind==='comparison'&&config.single_cell_selection){const selection=config.single_cell_selection as Record<string,unknown>;if(!text(selection.processed_source_id)||!text(selection.annotation_source_id)||!strings(selection.label_ids).length)issues.push('请选择固定单细胞处理版本、人工注释版本和标签。')}
 if(config.kind==='integration'&&config.schema_version===2){
  if(!text(config.processed_source_id))issues.push('请选择固定单细胞处理版本。')
  if(config.method==='slingshot'&&(!text(config.root_cluster)||!text(config.root_basis).trim()))issues.push('请填写根聚类与选择依据。')
  if(config.method==='genie3'&&(!strings(config.tf_ids).length||strings(config.gene_ids).length<2||!text(config.tf_basis).trim()||strings(config.tf_ids).some(id=>!strings(config.gene_ids).includes(id))||config.seed===config.stability_seed))issues.push('请填写匹配的基因与TF、来源依据和两个不同种子。')
  if(config.method==='cellchat'&&(!text(config.annotation_source_id)||strings(config.label_ids).length<2||config.communication_mode!=='per_donor'&&strings(config.condition_values).length!==2))issues.push('通讯需要匹配标签；供者比较需要两个条件。')
  if(config.method==='cellchat'&&config.species_taxon_id!=null&&!text(config.species_basis).trim())issues.push('补充物种时请填写原始样本资料依据。')
 }
 if(config.kind==='integration'&&config.schema_version!==2){if(!Array.isArray(config.pairs)||!Array.isArray(config.concordances)||!config.pairs.length&&!config.concordances.length)issues.push('请预声明特征对或一致性对象。');if(config.mapping_confirmed!==true)issues.push('请核对并确认冻结对应资源。')}
 if(config.kind==='candidate'&&config.schema_version===2&&(!Array.isArray(config.candidates)||!config.candidates.length||!strings(config.evidence_source_ids).length))issues.push('请添加固定轴候选对象和类型化外部证据版本。')
 if(config.kind==='feature_extract'&&!strings(config.resource_source_ids).length)issues.push('请选择已冻结的序列或结构资源。')
 if(config.kind==='candidate'&&config.schema_version!==2){issues.push(...validateRecipe({result_source_ids:config.result_source_ids,primary_result_source_id:config.primary_result_source_id,steps:config.steps}));const contrasts=config.source_contrasts as Record<string,string>|undefined;if(strings(config.result_source_ids).some(id=>!contrasts?.[id]))issues.push('请为每个候选来源选择一个实际比较。')}
 if(config.kind==='result_import'){const columns=config.columns as Record<string,string>;if(!text(config.file_source_id)||!text(config.parse_version_id))issues.push('请明确选择外部文件和成功解析版本。');if(config.recompute_q===true&&(config.complete_tested_universe!==true||!columns.p_value))issues.push('重算 q 需要确认完整受检全集并提供有效 P 列；Top 表禁止直接重算。')}
 if(config.kind==='figure'){if(strings(config.formats).includes('pdf'))issues.push('PDF 图件不再支持，请移除 PDF 后继续；其他草稿内容保留。');if(!text(config.result_source_id))issues.push('请选择主结果版本。');if(config.figure_type==='gsea'&&!text(config.term_row_key))issues.push('GSEA 曲线必须选择实际 term 稳定行。');if(['venn','upset'].includes(text(config.figure_type))){const sets=(config.selected_sets??[]) as unknown[];if(sets.length<2||sets.length>(config.figure_type==='venn'?3:8))issues.push('Venn 需 2–3 集，UpSet 需 2–8 集，并逐集确认比较与阈值。')}}
 return issues
}
export const insightViews=['bio-insights','bio-insight-plan','bio-insight-result','bio-resources','bio-candidates'] as const
export const isInsightView=(view:string)=>(insightViews as readonly string[]).includes(view)

export const qOptions={q_within_contrast:'每比较 BH q',q_global_family:'冻结比较族 BH q',original_q:'外部原始 q',system_recomputed_q:'系统另算 q'}

export const defaultResource=():ResourceBody=>({kind:'gene_sets',title:'',species_taxon_id:9606,namespace:'ensembl_gene_id',release:'',output_language:'zh-CN',expected_revision:0,source:{institution:'',name:'',description:''},usage:{basis:'',redistribution_allowed:false,scope:'project'},files:[],strip_ensembl_version:false,propagation_relations:['is_a','part_of'],exclude_not:true,exclude_obsolete:true,exclude_root_terms:true,evidence_codes:[]})
