import {object,exact,comparisonDesign,comparisonMethods,type ComparisonMethod} from '../../features/analysis/analysisSelection'
export type ArtifactDisclosure = {
  version: 1 | 2 | 3 | 4 | 5 | 6
  source?: { filename: string; sheet_name: string; dataset_version: number; parent_dataset_version?: number; dataset_kind?: 'prepared' }
  provider: 'openai'
  task_type: 'boxplot' | 'explanation'
  source_digest: string
  has_saved_result: boolean
  summary: { verification_scope?:'local_effect_projection'|'independent_curve_calculation';outbound_data?:'local_effects_and_intervals'|'necessary_anonymous_observations';valid_count: number; excluded_count: number; group_count: number; figure_kind?:'boxplot'|'scatter'|'correlation_heatmap'|'group_boxplot'|'paired_connected'|'forest'|'roc_curve'|'kaplan_meier';method?:'descriptive'|'pearson'|'spearman'|ComparisonMethod|'ols'|'logistic'|'roc_auc'|'kaplan_meier';mode?:'pair'|'matrix'|null;output_language?:'zh-CN'|'en';variable_count?:number;variables?:{column:string;name:string;unit:string}[];design?:'independent'|'paired'|'multiple';paired_direction?:'before_minus_after'|null;posthoc?:'none'|'all_pairs_holm';observation_basis?:'complete_pairs'|'independent_rows' }
  labels: { key: string; value: string }[]
}
export type ExternalProcessingConfirmation = {
  version: 1 | 2 | 3 | 4 | 5 | 6; confirmed: true; source_digest: string; labels: Record<string, string>
}
export type ArtifactReviewDraft = { disclosure: ArtifactDisclosure; body: Record<string, unknown> }

export function isArtifactDisclosure(value: unknown, kind: ArtifactDisclosure['task_type']): value is ArtifactDisclosure {
  if (!value || typeof value !== 'object') return false
  const data = value as ArtifactDisclosure
  if (![1, 2, 3,4,5,6].includes(data.version) || data.provider !== 'openai' || data.task_type !== kind || typeof data.source_digest !== 'string'
    || !data.source_digest || typeof data.has_saved_result !== 'boolean' || !data.summary || !Array.isArray(data.labels)) return false
  if (![data.summary.valid_count, data.summary.excluded_count, data.summary.group_count].every(count => Number.isSafeInteger(count) && count >= 0)) return false
  if ([2, 3,4,5,6].includes(data.version) && (!data.source || Object.keys(data.source).length !== (data.version === 3 || data.version>=4&&data.source.dataset_kind==='prepared' ? 5 : 3) || typeof data.source.filename !== 'string' || !data.source.filename || typeof data.source.sheet_name !== 'string' || !data.source.sheet_name || !Number.isSafeInteger(data.source.dataset_version) || data.source.dataset_version < 1)) return false
  if (data.version === 3 && (!data.source || data.source.dataset_kind !== 'prepared' || !Number.isSafeInteger(data.source.parent_dataset_version) || (data.source.parent_dataset_version ?? 0) < 1)) return false
  if(data.version===6){
    const s=data.summary,regression=s.method==='ols'||s.method==='logistic',survival=s.method==='kaplan_meier'
    if(!object(value)||!exact(value,['version','provider','task_type','source_digest','has_saved_result','source','summary','labels'])||!object(s)||!exact(s,['valid_count','excluded_count','group_count','figure_kind','method','mode','output_language','variable_count','variables','verification_scope','outbound_data'])||!data.source||data.source.dataset_kind!=='prepared'||!Number.isSafeInteger(data.source.parent_dataset_version)||(data.source.parent_dataset_version??0)<1||!['ols','logistic','roc_auc','kaplan_meier'].includes(String(s.method))||s.figure_kind!==(regression?'forest':survival?'kaplan_meier':'roc_curve')||s.verification_scope!==(regression?'local_effect_projection':'independent_curve_calculation')||s.outbound_data!==(regression?'local_effects_and_intervals':'necessary_anonymous_observations')||s.mode!==null||!['zh-CN','en'].includes(String(s.output_language))||!Array.isArray(s.variables)||s.variable_count!==s.variables.length||s.variables.length<2||s.variables.length>10||!s.variables.every(v=>object(v)&&exact(v,['column','name','unit'])&&/^[A-Z]{1,3}$/.test(v.column)&&typeof v.name==='string'&&typeof v.unit==='string')||new Set(s.variables.map(v=>v.column)).size!==s.variables.length||(!survival&&s.group_count!==0)||survival&&(s.group_count<1||s.group_count>6))return false
    const effects=data.labels.filter(l=>l.key.startsWith('effect:'))
    if(regression?(effects.length<1||effects.length>20||!effects.every((l,i)=>l.key===`effect:${i+1}`)):effects.length!==0)return false
    const keys=[...s.variables.flatMap(v=>['field:'+v.column,'unit:'+v.column]),...effects.map(l=>l.key),...(survival?Array.from({length:s.group_count},(_,i)=>`group:${i}`):[]),...(kind==='explanation'?['figure_title','research_summary']:[])]
    return data.labels.length===keys.length&&keys.every(k=>data.labels.filter(l=>object(l)&&exact(l,['key','value'])&&l.key===k&&typeof l.value==='string').length===1)
  }
  if(data.version===5){
    const s=data.summary,paired=s.design==='paired'
    if(!object(value)||!exact(value,['version','provider','task_type','source_digest','has_saved_result','source','summary','labels'])||!object(s)||!exact(s,['valid_count','excluded_count','group_count','figure_kind','method','mode','output_language','variable_count','variables','design','paired_direction','posthoc','observation_basis'])||!data.source||data.source.dataset_kind!=='prepared'||!Number.isSafeInteger(data.source.parent_dataset_version)||(data.source.parent_dataset_version??0)<1||!Object.hasOwn(comparisonMethods,String(s.method))||s.design!==comparisonDesign(s.method as ComparisonMethod)||s.figure_kind!==(paired?'paired_connected':'group_boxplot')||s.paired_direction!==(paired?'before_minus_after':null)||s.observation_basis!==(paired?'complete_pairs':'independent_rows')||s.mode!==null||!['none','all_pairs_holm'].includes(String(s.posthoc))||s.design!=='multiple'&&s.posthoc!=='none'||!['zh-CN','en'].includes(String(s.output_language))||!Array.isArray(s.variables)||s.variable_count!==s.variables.length||s.variables.length!==(paired?2:1)||!s.variables.every(v=>object(v)&&exact(v,['column','name','unit'])&&/^[A-Z]{1,3}$/.test(v.column)&&typeof v.name==='string'&&typeof v.unit==='string')||new Set(s.variables.map(v=>v.column)).size!==s.variables.length||s.group_count<(s.design==='multiple'?3:2)||s.group_count>(s.design==='multiple'?6:2))return false
    const keys=[...s.variables.flatMap(v=>['field:'+v.column,'unit:'+v.column]),...Array.from({length:s.group_count},(_,i)=>`group:${i}`),...(kind==='explanation'?['figure_title','research_summary']:[])]
    return data.labels.length===keys.length&&keys.every(k=>data.labels.filter(l=>object(l)&&exact(l,['key','value'])&&l.key===k&&typeof l.value==='string').length===1)
  }
  if(data.version===4){
    const s=data.summary
    if(!['boxplot','scatter','correlation_heatmap'].includes(String(s.figure_kind))||!['zh-CN','en'].includes(String(s.output_language))||!Array.isArray(s.variables)||s.variable_count!==s.variables.length)return false
    if(s.figure_kind!=='boxplot'){
      if(!['pearson','spearman'].includes(String(s.method))||s.mode!==(s.figure_kind==='scatter'?'pair':'matrix')||s.variables.length<2||s.variables.length>(s.mode==='pair'?2:10)||new Set(s.variables.map(v=>v.column)).size!==s.variables.length||!s.variables.every(v=>v&&/^[A-Z]{1,3}$/.test(v.column)&&typeof v.name==='string'&&typeof v.unit==='string'))return false
      const keys=[...s.variables.flatMap(v=>['field:'+v.column,'unit:'+v.column]),...(kind==='explanation'?['figure_title','research_summary']:[])]
      return data.labels.length===keys.length&&keys.every(k=>data.labels.filter(l=>l?.key===k&&typeof l.value==='string').length===1)
    }
    if(s.method!=='descriptive'||s.mode!==null||s.variables.length!==0)return false
  }
  if (data.version === 1 && Object.hasOwn(data, 'source')) return false
  const keys = ['numeric_name', 'unit', ...(kind === 'explanation' ? ['figure_title',...(data.version===4?['research_summary']:[])] : [])]
  if (data.labels.some(label => label?.key === 'group_name')) {
    if (data.summary.group_count > data.labels.length) return false
    keys.push('group_name', ...Array.from({ length: data.summary.group_count }, (_, i) => `group:${i}`))
  }
  return data.labels.length === keys.length && keys.every(key => data.labels.filter(label => label?.key === key && typeof label.value === 'string').length === 1)
}
