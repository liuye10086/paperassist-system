import type {Config,Observation} from './contracts'
import {defaultConfig,strings} from './state'
export type SingleCellSelection={processed_source_id:string;annotation_source_id?:string;label_ids:string[];labels_confirmed?:boolean;label_basis?:string}
export function defaultSingleCellComposition():Config{return{kind:'comparison',schema_version:5,method:'single_cell_composition',output_language:'zh-CN',processed_source_id:'',annotation_source_id:'',label_ids:[],labels_confirmed:false,label_basis:'',mode:'descriptive',numerator:'',denominator:'',mapping_confirmed:false,independence_confirmed:false,independence_basis:'',batch_adjustment:false,transform:'asin',purpose:''}}
export function defaultSingleCellDE():Config{return{...defaultConfig('comparison'),mode:'donor_unpaired',single_cell_selection:{processed_source_id:'',annotation_source_id:'',label_ids:[],labels_confirmed:false,label_basis:''}}}
export function selectedSingleCellRows(rows:Observation[],selection:SingleCellSelection,condition:string){return rows.filter(r=>r.retained!==false&&r.processed_version_id===selection.processed_source_id&&r.annotation_status==='assigned'&&strings(selection.label_ids).includes(String(r.label_id??''))&&r.condition===condition)}
export function compositionOverview(rows:Observation[],processedId:string,conditions:string[],labels:string[]){
 const selected=rows.filter(r=>r.retained!==false&&r.processed_version_id===processedId&&conditions.includes(String(r.condition??''))),categories={label:0,other:0,unknown:0,uncertain:0,conflict:0,unlabeled:0}
 for(const r of selected){const status=r.annotation_status;const category=status==='assigned'?(labels.includes(String(r.label_id??''))?'label':'other'):status==='unknown'?'unknown':status==='uncertain'?'uncertain':status==='ambiguous'||status==='conflict'?'conflict':'unlabeled';categories[category]++}
 return{totalCells:selected.length,donors:new Set(selected.map(r=>r.donor).filter(Boolean)).size,unknownDonorCells:selected.filter(r=>!r.donor).length,categories}
}
