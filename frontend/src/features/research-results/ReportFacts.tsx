import {useI18n} from '../../shared/i18n'
import type {Fact} from './contracts'

const metrics:Record<string,string>={n:'样本数',count:'样本数',mean:'均值',median:'中位数',std:'标准差',sd:'标准差',min:'最小值',max:'最大值',q1:'第一四分位数',q3:'第三四分位数',iqr:'四分位距',row_count:'总行数',valid_count:'有效行数',excluded_count:'排除行数',ready:'数据检查通过',p_value:'P 值',pval:'P 值',p_val:'P 值',q_value:'Q 值',padj:'调整后 P 值',p_val_adj:'调整后 P 值',effect:'效应量',log2FoldChange:'log2 倍数变化',avg_log2FC:'log2 倍数变化',statistic:'检验统计量',coefficient:'系数',beta:'回归系数',se:'标准误',ci_low:'置信区间下限',ci_high:'置信区间上限',confidence_interval:'置信区间',low:'下限',high:'上限',estimate:'估计值',value:'数值',cluster:'细胞群',feature_id:'特征',sample_id:'样本',barcode:'条形码',component:'成分'}
const readable=(value:string)=>value.replaceAll('_',' ').replace(/\[(\d+)\]/g,(_,n)=>` ${Number(n)+1}`)
export default function ReportFacts({facts}:{facts:Fact[]}){
 const{t}=useI18n()
 function label(f:Fact,index:number){
  const path=String(f.locator.field_path??'')
  if(path){
   const group=path.match(/(?:^|\.)groups\[(\d+)\]/)
   const scope=group?t('分组 {number}',{number:Number(group[1])+1}):path.startsWith('overall.')?t('总体'):''
   const parts=path.replace(/^(overall|statistics|check)\./,'').replace(/^groups\[\d+\]\./,'').split('.').filter(part=>part!=='statistics')
   return [scope,...parts.map(part=>metrics[part]?t(metrics[part]):readable(part))].filter(Boolean).join(' · ')
  }
  if(f.locator.row_key)return [...Object.entries(f.locator.row_key).map(([key,value])=>`${t(metrics[key]??readable(key))} ${value}`),t(metrics[f.locator.column??'']??readable(f.locator.column??''))].filter(Boolean).join(' · ')
  if(f.locator.cell)return [f.locator.sheet,f.locator.cell].filter(Boolean).join(' · ')
  return t('结果 {number}',{number:index+1})
 }
 const levels:Record<string,string>={sample:'样本层级',cell:'细胞层级',spot:'空间点层级',donor:'供体层级'}
 return <table className="report-fact-table"><thead><tr><th>{t('项目')}</th><th>{t('结果')}</th><th>{t('单位')}</th></tr></thead><tbody>{facts.map((f,i)=><tr key={f.id}><th scope="row">{label(f,i)}{(levels[f.observation_level]||(f.comparison&&f.source_kind!=='analysis_run'))&&<small>{[levels[f.observation_level]?t(levels[f.observation_level]):'',f.source_kind!=='analysis_run'?f.comparison:''].filter(Boolean).join(' · ')}</small>}</th><td>{typeof f.raw_value==='boolean'?t(f.raw_value?'是':'否'):f.display_value}</td><td>{f.unit||'—'}</td></tr>)}</tbody></table>
}
