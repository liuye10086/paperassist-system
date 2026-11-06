import {useI18n} from '../../shared/i18n'
import type {BioRecipeParameters, HarmonyParameters, TechnicalCovariate} from './spatialContracts'

export default function SingleCellIntegrationFields({params,onChange}:{params:BioRecipeParameters;onChange:(value:BioRecipeParameters)=>void}){
 const {t}=useI18n()
 const harmony=params.harmony??{enabled:false,batch_key:'batch',theta:2,lambda:1,max_iter:10}
 const covariates=params.technical_covariates??[]
 const changeHarmony=(value:Partial<HarmonyParameters>)=>onChange({...params,harmony:{...harmony,...value}})
 const toggle=(key:TechnicalCovariate,enabled:boolean)=>onChange({...params,technical_covariates:enabled?[...covariates.filter(v=>v!==key),key]:covariates.filter(v=>v!==key)})
 const batchOptions=<><option value="batch">{t('批次（batch）')}</option><option value="library_id">{t('捕获文库（library_id）')}</option></>
 return <section aria-label={t('多样本整合与技术协变量')}>
  <h4>{t('批次感知 HVG')}</h4>
  <label>{t('HVG 批次分组')}<select value={params.hvg_batch_key??''} onChange={e=>onChange({...params,hvg_batch_key:(e.target.value||null) as BioRecipeParameters['hvg_batch_key']})}><option value="">{t('不按批次分组')}</option>{batchOptions}</select></label>
  <p>{t('按批次选择高变基因；缺少完整批次或只有一个批次时，使用全局 HVG，并在结果中说明。')}</p>
  <h4>{t('技术协变量处理')}</h4>
  <label className="intake-check"><input type="checkbox" checked={covariates.includes('log1p_total_counts')} onChange={e=>toggle('log1p_total_counts',e.target.checked)}/>{t('处理测序深度（log1p total counts）')}</label>
  <label className="intake-check"><input type="checkbox" disabled={!params.mt_rule.confirmed&&!covariates.includes('mt_fraction')} checked={covariates.includes('mt_fraction')} onChange={e=>toggle('mt_fraction',e.target.checked)}/>{t('处理线粒体比例')}</label>
  <p>{t('仅调整用于降维的高变基因副本；原始 counts、normalized 和 log1p 保留。协变量缺失、恒定或共线时不应用，并说明原因。线粒体比例需先确认规则。')}</p>
  <h4>{t('Harmony 批次整合')}</h4>
  <label className="intake-check"><input type="checkbox" checked={harmony.enabled} onChange={e=>changeHarmony({enabled:e.target.checked})}/>{t('运行 Harmony 批次整合')}</label>
  {harmony.enabled&&<>
   <label>{t('Harmony 批次分组')}<select value={harmony.batch_key} onChange={e=>changeHarmony({batch_key:e.target.value as HarmonyParameters['batch_key']})}>{batchOptions}</select></label>
   <div className="intake-rows">
    <label>Harmony theta<input required type="number" min={0} max={20} step="any" value={harmony.theta} onChange={e=>changeHarmony({theta:Number(e.target.value)})}/></label>
    <label>Harmony lambda<input required type="number" min={0.01} max={100} step="any" value={harmony.lambda} onChange={e=>changeHarmony({lambda:Number(e.target.value)})}/></label>
    <label>{t('Harmony 最大迭代次数')}<input required type="number" min={1} max={100} step={1} value={harmony.max_iter} onChange={e=>changeHarmony({max_iter:Number(e.target.value)})}/></label>
   </div>
  </>}
  <p>{t('保留 PCA 和成功生成的整合表示；邻居、UMAP 与聚类使用实际选定表示。缺少批次、只有一个批次或批次与研究组完全混杂时不运行整合。批次混合更充分不等于生物学结果更准确。')}</p>
 </section>
}
