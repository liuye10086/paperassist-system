import {expect,it} from 'vitest'
import {isTask,sameInputVersion} from './taskTypes'
const raw={kind:'bio_dataset_version',schema_version:1,project_id:'p1',dataset_id:'d1',dataset_version_id:'v1',version:1,manifest_sha256:'a'.repeat(64),parser_version:'tabular_assay_import_v1',source_file_ids:['matrix','samples']}
const input={schema_version:1,kind:'bio_analysis',run_id:'run1',recipe_version_id:'recipe1',raw_source:raw,workflow_version:'bio_analysis_v2',engine_version:'tabular_quantitative_v1.0.0',environment_digest:'b'.repeat(64),output_language:'zh-CN'}
const task={id:'t1',project_id:'p1',task_type:'bio_analysis',status:'waiting_confirmation',phase:'compute',display_status:'waiting_confirmation',reason_code:null,error_code:null,created_at:'2026-11-01T00:00:00Z',updated_at:'2026-11-01T00:00:00Z',revision:2,current_attempt:1,input_version:input,result_bio_processed_dataset_version_id:null,result_bio_figure_version_id:null}
it('accepts only the exact comparison V2 workflow while preserving the public eight-field identity',()=>{
 const insight={kind:'bio_comparison',schema_version:1,workflow_version:'bio_comparison_v2',source_sha256:'a'.repeat(64),source_digest:'b'.repeat(64),output_language:'zh-CN',real_model_calls:false,real_network_calls:false}
 const base={...task,task_type:'bio_comparison',status:'succeeded',display_status:'succeeded',result_bio_insight_result_version_id:'result1',input_version:insight}
 expect(isTask(base,'p1')).toBe(true);expect(isTask({...base,input_version:{...insight,workflow_version:'bio_candidate_v2'}},'p1')).toBe(false)
 expect(isTask({...base,task_type:'bio_candidate',input_version:{...insight,kind:'bio_candidate',workflow_version:'bio_candidate_v2'}},'p1')).toBe(false)
 expect(sameInputVersion(insight as never,{...insight,workflow_version:'bio_comparison_v1'} as never)).toBe(false)
})
it('accepts exactly the quantitative workflow and refuses mismatched spatial engine or raw parser',()=>{
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,input_version:{...input,engine_version:'visium_explore_v1.0.0'}},'p1')).toBe(false)
 expect(isTask({...task,input_version:{...input,raw_source:{...raw,parser_version:'geo_visium_import_v2'}}},'p1')).toBe(false)
 expect(isTask({...task,input_version:{...input,raw_source:{...raw,project_id:'p2'}}},'p1')).toBe(false)
 expect(sameInputVersion(input as never,{...input,workflow_version:'bio_analysis_v1'} as never)).toBe(false)
})
it('accepts a V3 import identity and compares its assay, code and environment identity',()=>{
 const imported={kind:'bio_import',import_id:'i1',dataset_id:'d1',source_file_ids:['matrix','samples'],workflow_version:'bio_import_v3',parser_version:'tabular_assay_import_v1',output_language:'en',engine_version:'tabular_quantitative_v1.0.0',environment_digest:'b'.repeat(64),code_digest:'c'.repeat(64),assay:'proteomics'}
 expect(isTask({...task,task_type:'bio_import',phase:'parse',input_version:imported},'p1')).toBe(true)
 expect(sameInputVersion(imported as never,{...imported} as never)).toBe(true)
 expect(sameInputVersion(imported as never,{...imported,assay:'metabolomics'} as never)).toBe(false)
 expect(sameInputVersion(imported as never,{...imported,code_digest:'d'.repeat(64)} as never)).toBe(false)
 expect(isTask({...task,task_type:'bio_import',phase:'parse',input_version:{...imported,assay:'visium'}},'p1')).toBe(false)
})
