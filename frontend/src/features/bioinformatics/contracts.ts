import type { TaskView } from '../tasks/taskTypes'
export type {RawBioSource,ProcessedBioSource,BioRecipeParameters,BioCapabilities,BioRecipe,BioSetup,BioRun,BioProcessed,BioFigure,BioAnnotation,BioMapRequest,BioMapPreviewRequest,BioSetupRequest,BioRunRequest,BioConfirmationRequest,BioFigureRequest,BioAnnotationRequest} from './spatialContracts'
export type BioCheck={code?:string;name?:string;status?:string;message?:string;blocking?:boolean;[key:string]:unknown}
export type BioMember={id:string;role:string;filename:string;verification_state:string;sha256?:string;size_bytes?:number;download_url?:string}
export type BioCandidate={sha256:string;summary:Record<string,unknown>;checks:BioCheck[];members:BioMember[];images?:unknown[]}
export type BioImport={id:string;dataset_id:string;task:TaskView;candidate:BioCandidate|null;checkpoint_id:string|null;wait_id:string|null;result_source?:{dataset_id:string;dataset_version_id:string}|null;expected_dataset_revision?:number}
export type BioVersion={id:string;dataset_id:string;version:number;manifest_sha256:string;shape:{features:number;observations:number;stored_entries:number};checks:BioCheck[];source:unknown;members:BioMember[];summary:Record<string,unknown>}
export type BioDataset={id:string;name:string;revision:number;current_version_id?:string|null;current_version?:{id:string;version:number}|null}
export function canConfirmCandidate(value:{task:{status:string;revision:number|null};candidate:{sha256:string;checks:BioCheck[]}|null;checkpoint_id:string|null;wait_id:string|null}):boolean{
 return value.task.status==='waiting_confirmation'&&Number.isSafeInteger(value.task.revision)&&!!value.checkpoint_id&&!!value.wait_id&&!!value.candidate&&/^[a-f0-9]{64}$/.test(value.candidate.sha256)&&!value.candidate.checks.some(c=>c.blocking===true&&(c.status==='failed'||c.status==='error'||c.status==='blocked')||c.code==='representation_equivalence'&&c.value&&typeof c.value==='object'&&'status' in c.value&&c.value.status==='mismatch')
}

export const roleLabels:Record<string,string>={derived_representation:'派生表示（非原件）',matrix:'原始矩阵',features:'特征表',barcodes:'条码表',positions:'位置表',scalefactors:'缩放参数',alternate_matrix:'H5 备选矩阵',tissue_image:'组织图像',qc_image:'质控图像',geo_metadata:'GEO 元数据',package_listing:'数据包清单',supplementary:'补充材料',matrix_data:'矩阵计数',matrix_indices:'矩阵特征索引',matrix_indptr:'矩阵观测索引',features_index:'特征索引',barcodes_index:'条码索引',positions_index:'坐标索引'}
export const checkLabels:Record<string,string>={representation_equivalence:'矩阵表示等价核对',structure:'文件结构',duplicate_symbol_groups:'重复基因符号组数',positions_count:'坐标数量',in_tissue_count:'组织内观测数',matrix_matches_in_tissue:'矩阵与组织内条码一致性',matrix_barcodes_in_positions:'矩阵条码具备位置',alternate_h5:'H5 备选矩阵',empty_series_matrix:'GEO 空表达矩阵识别',source_accessions:'来源登记号',warnings:'核对提示'}
