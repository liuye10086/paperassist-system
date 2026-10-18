import {object,exact,validComparisonGroup,groupIdentity,type ComparisonGroup} from './analysisSelection'
import type {PreparedDatasetAnalysisSource} from './datasetSource'
export type GroupOptions={dataset_id:string;sheet_name:string;group_column:string;row_count:number;missing_count:number;options:(ComparisonGroup&{label:string;count:number})[]}
export function isGroupOptions(v:unknown,source:PreparedDatasetAnalysisSource,column:string):v is GroupOptions {
 const int=(n:unknown)=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0
 return object(v)&&exact(v,['dataset_id','sheet_name','group_column','row_count','missing_count','options'])&&v.dataset_id===source.dataset_id&&v.sheet_name===source.sheet_name&&v.group_column===column&&int(v.row_count)&&int(v.missing_count)&&Array.isArray(v.options)&&v.options.every(g=>object(g)&&exact(g,['kind','value','label','count'])&&validComparisonGroup({kind:g.kind,value:g.value})&&typeof g.label==='string'&&int(g.count)&&Number(g.count)>0)&&new Set(v.options.map(g=>groupIdentity(g as ComparisonGroup))).size===v.options.length&&v.options.reduce((n,g)=>n+Number(g.count),Number(v.missing_count))===v.row_count
}
