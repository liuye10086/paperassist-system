import type {Config,Source,Page} from './contracts'
import {insightBase,insightRequest} from './api'
export type SampleKey={processed_version_id:string;sample_id:string}
export type SampleRow=SampleKey&{retained?:boolean;[key:string]:unknown}
export type SampleGroup={label:string;sample_keys:SampleKey[]}
export type SampleContrast={contrast_id:string;name:string;groups:SampleGroup[]}
export type SampleCovariate={field:string;kind:'categorical'|'continuous';name:string;reference_level?:string|null}
type SampleScale={namespace?:string;reference_version?:string;species_taxon_id?:number|null}
export const sampleKey=(s:SampleKey)=>JSON.stringify([s.processed_version_id,s.sample_id])
export const newSampleContrast=(id:string,count=2):SampleContrast=>({contrast_id:id,name:id,groups:Array.from({length:count},(_,i)=>({label:String.fromCharCode(65+i),sample_keys:[]}))})
export function defaultQuantitativeConfig():Config{return{kind:'comparison',schema_version:2,mode:'continuous',design:'independent',method:'welch_t',analysis_layer:'analysis',contrasts:[newSampleContrast('contrast_1')],family_contrast_ids:['contrast_1'],inference_unit:'biological',inference_goal:'exploratory',independence_confirmed:false,independence_basis:'',technical_exploration_confirmed:false,design_basis:'',data_driven_grouping:false,pairing_field:'pair_id',batch_adjustment:false,excluded_samples:[],minimum_total_counts:10,size_factor_method:'ratio',posthoc:'none',missing_policy:'complete_cases',namespace:'',reference_version:'',species_taxon_id:null,output_language:'zh-CN'}}
export const bulkModelDefaults={bulk_model:'shared_wald_v1',covariates:[],condition_reference:null,minimum_sample_counts:1}
export function defaultBulkConfig():Config{
 return {...defaultQuantitativeConfig(),...bulkModelDefaults,mode:'bulk_counts',method:'deseq2_wald',analysis_layer:'raw_counts'}
}
export async function readQuantitativeSamples(projectId:string,sources:Source[],signal:AbortSignal,onScale?:(scale:SampleScale)=>void){
 const result:SampleRow[]=[],seen=new Set<string>()
 const processed=sources.filter(s=>s.source_kind==='bio_processed_dataset_version')
 let scale:SampleScale|undefined
 for(const source of processed){
  let page=1,total=1,count=0
  while((page-1)*1000<total){
   const response=await insightRequest<Page<SampleRow>&{observation_level?:string;scale?:SampleScale}>(`${insightBase(projectId)}/sources/${source.source_kind}/${encodeURIComponent(source.source_id)}/observations?page=${page}&page_size=1000`,{signal},true)
   if(signal.aborted)throw new DOMException('Aborted','AbortError')
   if(!Number.isInteger(response.total)||response.total<0||response.total>100000||response.observation_level&&response.observation_level!=='sample')throw Error('请选择固定的样本级定量版本。')
   if(page>1&&response.total!==total)throw Error('固定样本分页总数不一致，请重新读取。')
   total=response.total
   if(page===1&&processed.length===1)scale=response.scale
   for(const row of response.items){if(typeof row.sample_id!=='string'||!row.sample_id)throw Error('请选择固定的样本级定量版本。');const next={...row,processed_version_id:source.source_id},key=sampleKey(next);if(seen.has(key))throw Error('固定样本键重复，请核对来源。');seen.add(key);result.push(next);count++}
   page++
  }
  if(count!==total)throw Error('固定样本分页总数不一致，请重新读取。')
 }
 if(scale)onScale?.(scale)
 return result
}
