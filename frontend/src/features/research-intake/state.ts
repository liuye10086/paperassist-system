import type { Content, Declaration, MaterialRef } from './contracts'
export function declared(state:Declaration['state'],value:string):Declaration{return {state,value:state==='known'?value:null}}
export function updateServices<T extends {services:unknown}>(content:T,services:string[]):T{return {...content,services}}
export const emptyRequirement=():Content=>({schema_version:1,services:['analysis'],contact:{},progress:{stages:[],notes:''},scope_items:[],schedule:{},analysis_request:{},figure_request:{},sci_request:{},thesis_request:{},material_checklist:[],notes:''})
export const emptyDesign=():Content=>({schema_version:1,experiments:[],groups:[],samples:[],observation:{},comparisons:[],exclusions:[],cross_dataset_links:[],declarations:{}})

export const materialPurposes=[['protocol','实验方案'],['sample_sheet','样本信息表'],['raw_data','原始数据'],['existing_results','已有结果'],['figures','已有图表'],['other','其他材料']]
export function cleanMaterialRefs(refs:MaterialRef[]):MaterialRef[]{return refs.map(r=>({delivery_id:r.delivery_id??null,file_id:r.file_id??null,bio_dataset_version_id:r.bio_dataset_version_id??null,locator:r.locator??null,availability:r.availability,purpose:r.purpose,note:r.note??''}))}
