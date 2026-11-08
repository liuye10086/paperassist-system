import type { Content, Declaration, MaterialRef } from './contracts'
export function declared(state:Declaration['state'],value:string):Declaration{return {state,value:state==='known'?value:null}}
export function updateServices<T extends {services:unknown}>(content:T,services:string[]):T{return {...content,services}}
export const emptyRequirement=():Content=>({schema_version:1,services:['analysis'],contact:{},progress:{stages:[],notes:''},scope_items:[],schedule:{},analysis_request:{},figure_request:{},sci_request:{},thesis_request:{},material_checklist:[],notes:''})
export const emptyDesign=():Content=>({schema_version:1,experiments:[],groups:[],samples:[],observation:{},comparisons:[],exclusions:[],cross_dataset_links:[],declarations:{}})

export const materialPurposes=[['protocol','实验方案'],['sample_sheet','样本信息表'],['raw_data','原始数据'],['existing_results','已有结果'],['figures','已有图表'],['other','其他材料']]
export function linkSelectedFigureRefs(refs:MaterialRef[],ids:string[]):MaterialRef[]{
 const next=[...refs]
 for(const id of ids){
  if(next.some(ref=>ref.file_id===id&&ref.purpose==='figures'&&ref.availability==='provided'))continue
  const empty=next.findIndex(ref=>ref.purpose==='figures'&&ref.availability==='provided'&&!ref.file_id&&!ref.bio_dataset_version_id)
  if(empty>=0)next[empty]={...next[empty],file_id:id}
  else next.push({file_id:id,availability:'provided',purpose:'figures'})
 }
 return next
}
export function prepareMaterialRefs(content:Content,refs:MaterialRef[]):MaterialRef[]{
 const checklist=(content.material_checklist??[]) as {purpose:string;availability:MaterialRef['availability']}[]
 const next=refs.map(ref=>{const item=checklist.find(item=>item.purpose===ref.purpose);return item&&item.availability!=='provided'&&ref.availability==='provided'&&!ref.file_id&&!ref.bio_dataset_version_id?{...ref,availability:item.availability}:ref})
 for(const item of checklist.filter(item=>item.availability==='provided')){
  if(next.some(ref=>ref.purpose===item.purpose&&ref.availability==='provided'))continue
  const empty=next.findIndex(ref=>ref.purpose===item.purpose&&!ref.file_id&&!ref.bio_dataset_version_id)
  if(empty>=0)next[empty]={...next[empty],availability:'provided'}
  else next.push({purpose:item.purpose,availability:'provided',note:''})
 }
 return next
}
export function hasMissingMaterialSource(content:Content,refs:MaterialRef[]):boolean{
 return refs.some(ref=>ref.availability==='provided'&&!ref.file_id&&!ref.bio_dataset_version_id)||((content.material_checklist??[]) as {purpose:string;availability:string}[]).some(item=>item.availability==='provided'&&!refs.some(ref=>ref.purpose===item.purpose&&ref.availability==='provided'&&(ref.file_id||ref.bio_dataset_version_id)))
}
export function cleanMaterialRefs(refs:MaterialRef[]):MaterialRef[]{return refs.map(r=>({delivery_id:r.delivery_id??null,file_id:r.file_id??null,bio_dataset_version_id:r.bio_dataset_version_id??null,locator:r.locator??null,availability:r.availability,purpose:r.purpose,note:r.note??''}))}

// Object key order and server-generated reference row order do not change the saved meaning.
function stableJson(value:unknown):string{return JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item)}
export function sameIntakeVersion(content:Content,refs:MaterialRef[],current:{content:Content;material_refs?:MaterialRef[]}|null|undefined):boolean{
 return !!current&&stableJson(content)===stableJson(current.content)&&JSON.stringify(cleanMaterialRefs(refs).map(stableJson).sort())===JSON.stringify(cleanMaterialRefs(current.material_refs??[]).map(stableJson).sort())
}
