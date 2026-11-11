export type InsightKind='comparison'|'result_import'|'ora'|'gsea_prerank'|'candidate'|'figure'|'feature_extract'|'integration'
export const kindLabels:Record<InsightKind,string>={integration:'多组学与跨数据整合',feature_extract:'序列／结构实际特征提取',comparison:'固定设计差异比较',result_import:'导入外部差异表',ora:'ORA 过度富集',gsea_prerank:'GSEA 完整排序',candidate:'候选筛选配方',figure:'结果单图'}
export const sourceLabels={external_evidence_version:'类型化外部证据版本',bio_processed_dataset_version:'固定处理数据',bio_observation_map_version:'观测对应表',bio_annotation_version:'区域／细胞人工注释',research_design_version:'研究设计',bio_resource_version:'功能／映射／注释资源',bio_insight_result_version:'差异与功能结果',original_file:'已有原始文件'}
export type SourceKind=keyof typeof sourceLabels
export type Locator={kind:'object'|'table'|'row'|'field';member_key?:string|null;table?:string|null;row_key?:Record<string,string>|null;field?:string|null;parse_version_id?:string|null}
export type Source={title?:string;assay?:string;species_taxon_id?:number|null;source_kind:SourceKind;source_id:string;sha256:string;role:string;locator:Locator}
export type SourceItem={source_kind:SourceKind;source_id:string;sha256:string|null;title:string;assay?:string;parse_version_id?:string|null;filename?:string;file_type?:string;kind?:string;status?:string;release?:string;version?:number;species_taxon_id?:number|null}
export type Observation={processed_version_id:string;barcode:string;retained?:boolean;cluster?:string|null;region?:string|null;condition?:string|null;group?:string|null;donor?:string|null;batch?:string|null;[key:string]:unknown}
export type ObservationKey={processed_version_id:string;barcode:string}
export type Group={label:string;observation_keys:ObservationKey[]}
export type Contrast={contrast_id:string;name:string;numerator:Group;denominator:Group}
export type CandidateStep={operation:'threshold'|'union'|'intersection'|'at_least_k'|'same_direction'|'include'|'exclude'|'annotation';source_ids?:string[];q_column?:string;q_threshold?:number;minimum_absolute_effect?:number;k?:number;feature_ids?:string[];annotation_field?:string;annotation_operator?:string;annotation_value?:string|number|boolean|null}
export type BulkEnrichmentDeclaration={source_taxon_id?:number|null;taxon_evidence?:string|null}
export type Config=Record<string,unknown>&{kind:InsightKind;output_language:'zh-CN'|'en';bulk_enrichment?:BulkEnrichmentDeclaration|null;bulk_enrichment_render?:boolean|null}
export type PlanBody={name:string;kind:InsightKind;decision:'draft'|'confirmed';expected_revision:number;sources:Source[];config:Config}
export type BulkModelPreview={
 formula:string
 condition_reference:string
 condition_levels:string[]
 terms:{field:string;term:string;kind:string;name?:string;reference_level?:string|null}[]
 contrasts:{contrast_id:string;numerator:string;denominator:string}[]
 filter:{minimum_total_counts:number;minimum_sample_counts:number;minimum_expressing_samples:number;eligible_feature_count:number}
 size_factor_method:string
 samples:{processed_version_id:string;sample_id:string;condition:string;donor:string;batch:string;biological_unit_id:string;covariates:Record<string,unknown>}[]
}
export type EnrichmentIdentity={species_taxon_id:number|null;namespace:string|null;reference_version:string|null}
export type EnrichmentSourceIdentity=EnrichmentIdentity&{taxon_origin?:string|null;taxon_evidence?:string|null;original_namespace?:string|null}
export type EnrichmentResourceIdentity=EnrichmentIdentity&{
 resource_id:string;release:string;reference_status?:string|null;mapping_source_id?:string|null;title?:string
}
export type EnrichmentCompatibility={source:EnrichmentSourceIdentity|null;resources:EnrichmentResourceIdentity[];note?:string}
export type Design={executable:boolean;blocking_reasons:({code?:string;message?:string;detail?:unknown}|string)[];warnings?:string[];source_digest?:string;reviewed_design_sha256?:string;bulk_model?:BulkModelPreview;enrichment_compatibility?:EnrichmentCompatibility|null;exclusions?:{processed_version_id:string;sample_id:string;reason:string}[];[key:string]:unknown}
export type Plan={id:string;plan_id:string;version:number;revision:number;current_revision:number;parent_id:string|null;kind:InsightKind;name:string;decision:'draft'|'confirmed';config:Config;config_sha256:string;sources:Source[];source_digest:string;design:Design;design_checks?:Design}
export type Task={id:string;status:string;phase?:string;display_status?:string;reason_code?:string|null;error_code?:string|null;revision?:number}
export type Run={id:string;run_id:string;kind:InsightKind;plan_id?:string;plan_version_id:string;source_digest:string;result_version_id:string|null;task_id:string;task:Task}
export type Member={id:string;key:string;role:string;format:string;sha256:string;size_bytes:number;shape?:Record<string,unknown>;download_url:string}
export type Result={id:string;run_id:string;plan_version_id:string;kind:InsightKind;provenance:string;inference_scope:string;summary:Record<string,unknown>;methods:Record<string,unknown>;manifest:Record<string,unknown>;manifest_sha256:string;task_id:string;task:Task;members:Member[]}
export type Page<T>={items:T[];page:number;page_size:number;total:number}
export type TablePage=Page<Record<string,unknown>>&{key:string;columns:string[];matched_total:number;sha256:string;raw_text_values:boolean}
export type ResourceBody={kind:'gene_sets'|'id_mapping'|'feature_annotation'|'sequence'|'structure'|'sample_correspondence'|'object_correspondence';sequence_type?:'dna'|'rna'|'protein'|null;nucleotide_encoding?:'T'|'U'|null;structure_origin?:'experimental'|'predicted'|'unknown'|null;title:string;species_taxon_id:number;namespace:string;release:string;reference_version?:string|null;offline_enrichment?:boolean|null;output_language:'zh-CN'|'en';expected_revision:number;source:{institution:string;name:string;description:string;url?:string;release_date?:string};usage:{basis:string;redistribution_allowed:boolean;scope:'project'|'internal'|'redistributable'};files:ResourceFile[];mapping_source_namespace?:string;mapping_target_namespace?:string;strip_ensembl_version:boolean;propagation_relations:('is_a'|'part_of')[];exclude_not:true;exclude_obsolete:true;exclude_root_terms:true;evidence_codes:string[]}
export type ResourceFile={file_id:string;sha256:string;role:'obo'|'gaf'|'gmt'|'term_gene'|'id_mapping'|'feature_annotation'|'fasta'|'pdb'|'mmcif'|'sample_correspondence'|'object_correspondence';format:string;parse_version_id?:string|null;sheet?:string;columns:Record<string,string>}
export type Resource={id:string;root_id:string;version:number;revision:number;parent_id:string|null;kind:ResourceBody['kind'];title:string;release:string;namespace:string;species_taxon_id:number;source:ResourceBody['source'];usage:ResourceBody['usage'];config:ResourceBody;task_id:string;task:Task;manifest:Record<string,unknown>|null;manifest_sha256:string|null;members:Member[]}
export type Uploaded={file_id:string;filename:string;sha256:string;size_bytes:number;parse_status:string;parse_version_id:string|null}
