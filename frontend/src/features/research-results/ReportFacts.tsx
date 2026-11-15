import {useI18n} from '../../shared/i18n'
import ReadableDetails from '../../shared/components/ReadableDetails'
import type {Fact, Locator, ReportDisclosureFact, ReportDisclosureMaterial} from './contracts'

const metrics:Record<string,string>={n:'样本数',count:'样本数',mean:'均值',median:'中位数',std:'标准差',sd:'标准差',min:'最小值',max:'最大值',q1:'第一四分位数',q3:'第三四分位数',iqr:'四分位距',row_count:'总行数',valid_count:'有效行数',excluded_count:'排除行数',ready:'数据检查通过',p_value:'P 值',pval:'P 值',p_val:'P 值',q_value:'Q 值',padj:'调整后 P 值',p_val_adj:'调整后 P 值',effect:'效应量',log2FoldChange:'log2 倍数变化',avg_log2FC:'log2 倍数变化',statistic:'检验统计量',coefficient:'系数',beta:'回归系数',se:'标准误',ci_low:'置信区间下限',ci_high:'置信区间上限',confidence_interval:'置信区间',low:'下限',high:'上限',estimate:'估计值',value:'数值',cluster:'细胞群',feature_id:'特征',sample_id:'样本',barcode:'条形码',component:'成分'}
const readable=(value:string)=>value.replaceAll('_',' ').replace(/\[(\d+)\]/g,(_,n)=>` ${Number(n)+1}`)
const levels:Record<string,string>={sample:'样本层级',cell:'细胞层级',spot:'空间点层级',donor:'供体层级'}

function factLocationLabel(locator:Locator|undefined, index:number, t:ReturnType<typeof useI18n>['t'], labels=metrics){
  const path=locator?.field_path??''
  if(path){
   const group=path.match(/(?:^|\.)groups\[(\d+)\]/)
   const scope=group?t('分组 {number}',{number:Number(group[1])+1}):path.startsWith('overall.')?t('总体'):''
   const parts=path.replace(/^(overall|statistics|check)\./,'').replace(/^groups\[\d+\]\./,'').split('.').filter(part=>part!=='statistics')
   return [scope,...parts.map(part=>labels[part]?t(labels[part]):readable(part))].filter(Boolean).join(' · ')
  }
  if(locator?.row_key)return [...Object.entries(locator.row_key).map(([key,value])=>`${t(labels[key]??readable(key))} ${value}`),t(labels[locator.column??'']??readable(locator.column??''))].filter(Boolean).join(' · ')
  if(locator?.cell)return [locator.sheet,locator.cell].filter(Boolean).join(' · ')
  return t('结果 {number}',{number:index+1})
}

export default function ReportFacts({facts}:{facts:Fact[]}){
 const{t}=useI18n()
 return <table className="report-fact-table"><thead><tr><th>{t('项目')}</th><th>{t('结果')}</th><th>{t('单位')}</th></tr></thead><tbody>{facts.map((f,i)=><tr key={f.id}><th scope="row">{factLocationLabel(f.locator,i,t)}{(levels[f.observation_level]||(f.comparison&&f.source_kind!=='analysis_run'))&&<small>{[levels[f.observation_level]?t(levels[f.observation_level]):'',f.source_kind!=='analysis_run'?f.comparison:''].filter(Boolean).join(' · ')}</small>}</th><td>{typeof f.raw_value==='boolean'?t(f.raw_value?'是':'否'):f.display_value}</td><td>{f.unit||'—'}</td></tr>)}</tbody></table>
}

const disclosureMetrics={...metrics,raw_features:'原始特征数',retained_features:'保留特征数',excluded_features:'排除特征数',
 raw_observations:'原始观测数',retained_observations:'保留观测数',excluded_observations:'排除观测数',
 n_features:'特征数',n_spots:'空间点数',clusters:'聚类数',hvg:'高变基因数',pca_components:'主成分数',nnz:'非零表达值数',
 target_sum:'标准化目标计数',seed:'随机种子',resolution:'聚类分辨率',neighbors:'近邻数',min_counts:'最低计数',
 min_genes:'最少检测基因数',min_gene_spots:'最少表达空间点数'}
const spatialMetrics={...disclosureMetrics,raw_observations:'原始空间点数',retained_observations:'保留空间点数',excluded_observations:'排除空间点数'}
const otherLevels:Record<string,string>={region:'区域层级',dataset:'数据集层级',unknown:'观察层级未明确'}
const checks:Record<string,string>={verified:'已核对',unverified:'未核对',conflict:'有冲突',missing:'缺失',transcribed:'已转录'}
const origins:Record<string,string>={system_computed:'系统计算',public_reanalysis:'公开数据再分析',external_result:'外部结果',manual_transcription:'人工转录',image_observation:'图像观察'}

export function ReportDisclosureFacts({facts}:{facts:ReportDisclosureFact[]}){
 const{t}=useI18n()
 return <table className="report-fact-table"><thead><tr>{['项目','事实原值','单位','观察层级','核对状态与来源'].map(text=><th key={text}>{t(text)}</th>)}</tr></thead><tbody>{facts.map((fact,index)=>{
  const measure=fact.locator??fact.measure
  const location=typeof measure==='object'&&measure?{...measure,field_path:measure.field_path?.replace(/^(summary|params)\./,'')}:undefined
  const label=typeof measure==='string'&&measure?measure:fact.label||factLocationLabel(location,index,t,fact.observation_level==='spot'?spatialMetrics:disclosureMetrics)
  const level=levels[fact.observation_level??'']??otherLevels[fact.observation_level??'']
  const check=checks[fact.verification_status??fact.verification??'']
  const origin=origins[fact.origin??'']
  const context=[check,origin].filter(Boolean).map(value=>t(value)).join(' · ')
  const value='raw_value' in fact?fact.raw_value:fact.value
  return <tr key={index}>
   <th scope="row"><ReadableDetails value={label} readerView/></th>
   <td>{value==null?t('未提供'):typeof value==='boolean'?t(value?'是':'否'):<ReadableDetails value={value} readerView/>}</td>
   <td>{fact.unit==='spots'?t('空间点'):fact.unit?<ReadableDetails value={fact.unit} readerView/>:'—'}</td>
   <td>{level?t(level):'—'}</td>
   <td>{context||'—'}
    {fact.source&&<small><ReadableDetails value={fact.source} readerView/></small>}
    {fact.comparison&&<small>{t('比较')} · <ReadableDetails value={fact.comparison} readerView/></small>}
    {fact.feature_names&&<ReadableDetails value={fact.feature_names} readerView/>}
    {!!fact.limitations?.length&&<ReadableDetails value={fact.limitations} readerView/>}
   </td>
  </tr>
 })}</tbody></table>
}

export function ReportDisclosureSummary({material}:{material:ReportDisclosureMaterial}){
 const{t}=useI18n()
 const{facts,inherited_findings,...other}=material
 return <>
  {!!facts?.length&&<ReportDisclosureFacts facts={facts}/>}
  {!!Object.keys(other).length&&<ReadableDetails value={other} readerView/>}
  {inherited_findings?.map((finding,index)=><section key={index}>
   <h5>{t('继承的研究发现 {number}',{number:index+1})}</h5><ReportDisclosureSummary material={finding}/>
  </section>)}
 </>
}
