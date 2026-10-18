import {useI18n} from '../../shared/i18n'
import ModelResults from './ModelResults'
import CorrelationResults from './CorrelationResults'
import ComparisonResults from './ComparisonResults'
import type {Result} from './StatisticsResults'

export default function StatisticsTaskArtifact({result}:{result:Result}){
 const {t,locale}=useI18n()
 if(result.result_type==='correlation')return <CorrelationResults result={result}/>
 if(result.result_type==='group_comparison')return <ComparisonResults result={result}/>
 if(result.result_type==='regression'||result.result_type==='roc'||result.result_type==='survival')return <ModelResults result={result}/>
 if(result.result_type!==undefined)return null
 return <article aria-label={t('此任务的统计结果')}><h4>{t('描述统计结果')}</h4>
  <p>{result.filename} · {result.selection.sheet_name} · {new Date(result.completed_at).toLocaleString(locale)}</p>
  <div className="field-table-scroll"><table className="field-table"><thead><tr>{['范围 / 分组','样本数 n','均值','样本标准差','中位数'].map(label=><th key={label} scope="col">{t(label)}</th>)}</tr></thead>
  <tbody>{[{label:t('总体（完整记录）'),statistics:result.overall},...result.groups].map((group,index)=><tr key={index}><th scope="row">{group.label}</th><td>{group.statistics.n}</td>{(['mean','std','median'] as const).map(key=><td key={key}>{group.statistics[key]===null?'—':new Intl.NumberFormat(locale,{maximumSignificantDigits:6}).format(group.statistics[key]!)}</td>)}</tr>)}</tbody></table></div>
 </article>
}
