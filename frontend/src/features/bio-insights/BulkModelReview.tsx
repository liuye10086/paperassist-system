import {useI18n} from '../../shared/i18n'
import type {Design,Source} from './contracts'
import {DataDetails} from './InsightShared'

export default function BulkModelReview({design,sources}:{design:Design;sources:Source[]}){
 const {t}=useI18n(),model=design.bulk_model
 if(!model)return null
 const sourceName=(id:string)=>sources.find(source=>source.source_id===id)?.title??id
 const rules=model.filter
 const covariates=model.terms.filter(term=>term.term.startsWith('covariate_'))
 return <section className="analysis-detail" aria-label={t('Bulk 模型确认摘要')}>
  <p><strong>{t('模型公式')}</strong> <code>{model.formula}</code></p>
  <p>{t('模型参考组')} · {model.condition_reference} · {t('模型条件水平')} · {model.condition_levels.join(', ')}</p>
  <ul>{model.terms.map(term=><li key={term.term}>{term.term} · {term.name??term.field} ({term.field}) · {t(term.kind==='continuous'?'连续':'分类')}{term.reference_level&&<> · {t('参考水平')} {term.reference_level}</>}</li>)}</ul>
  <p>{t('所有指定比较共享一次拟合。')}</p>
  <ul>{model.contrasts.map(contrast=><li key={contrast.contrast_id}>{contrast.contrast_id} · <strong>{contrast.numerator} vs {contrast.denominator}</strong> · {t('参考（分母）')} {contrast.denominator}</li>)}</ul>
  <p>{t('DESeq2 size factor 方法')} · {model.size_factor_method}</p>
  <p>{t('总 counts 至少 {total}，且至少 {samples} 个样本的 counts 达到 {perSample}。候选特征 {features} 个。',{
   total:rules.minimum_total_counts,samples:rules.minimum_expressing_samples,perSample:rules.minimum_sample_counts,features:rules.eligible_feature_count,
  })}</p>
  <details open><summary>{t('最终纳入样本')} · {model.samples.length}</summary>
   <div className="field-table-scroll"><table className="field-table" aria-label={t('最终纳入样本')}>
    <thead><tr>{['固定处理数据','样本 ID','条件','生物学单位','配对键','批次'].map(label=><th key={label}>{t(label)}</th>)}{covariates.map(term=><th key={term.field}>{term.name??term.field}</th>)}</tr></thead>
    <tbody>{model.samples.map(sample=><tr key={JSON.stringify([sample.processed_version_id,sample.sample_id])}>
     <td title={sample.processed_version_id}>{sourceName(sample.processed_version_id)}</td><td>{sample.sample_id}</td><td>{sample.condition}</td>
     <td>{sample.biological_unit_id}</td><td>{sample.donor}</td><td>{sample.batch}</td>
     {covariates.map(term=><td key={term.field}>{String(sample.covariates[term.field]??'')}</td>)}
    </tr>)}</tbody>
   </table></div>
  </details>
  <DataDetails title="排除样本及原因" value={design.exclusions??[]}/>
 </section>
}
