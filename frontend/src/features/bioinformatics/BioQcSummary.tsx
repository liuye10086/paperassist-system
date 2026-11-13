import {useI18n} from '../../shared/i18n'
export default function BioQcSummary({summary,observationLabel='spot',featureLabel='基因'}:{summary:Record<string,unknown>;observationLabel?:string;featureLabel?:string}){
 const {t,locale}=useI18n(),value=(key:string)=>typeof summary[key]==='number'?Number(summary[key]).toLocaleString(locale):'NA'
 const reasons=summary.exclusion_reason_counts&&typeof summary.exclusion_reason_counts==='object'?Object.entries(summary.exclusion_reason_counts):[]
 return <section className="bio-workspace">
  <div className="bio-table-scroll"><table><caption>{t('原始、保留与排除数量对账')}</caption>
   <thead><tr>{['维度','原始','保留','排除'].map(label=><th key={label} scope="col">{t(label)}</th>)}</tr></thead>
   <tbody><tr><th scope="row">{t(observationLabel)}</th><td>{value('raw_observations')}</td><td>{value('retained_observations')}</td><td>{value('excluded_observations')}</td></tr>
    <tr><th scope="row">{t(featureLabel)}</th><td>{value('raw_features')}</td><td>{value('retained_features')}</td><td>{value('excluded_features')}</td></tr></tbody>
  </table></div>
  {reasons.length>0&&<><p>{t('排除原因可能重叠；最终排除数按原因并集计算。')} {t('并集数量')}: {value('exclusion_union_count')}</p>
   <ul>{reasons.map(([reason,count])=><li key={reason}>{reason}: {typeof count==='number'?count:'NA'}</li>)}</ul></>}
  {typeof summary.mitochondrial_reason==='string'&&<p className="bio-result-note">{t('线粒体状态')}：{t(summary.mitochondrial_reason==='mitochondrial_rule_unconfirmed'
   ?'规则尚未确认，未按线粒体比例过滤。':summary.mitochondrial_reason)}</p>}
 </section>
}
