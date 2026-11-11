import {useI18n} from '../../shared/i18n'
import {bulkComparisonLabel, bulkEnrichmentContrast, bulkQColumns, fixedBulkEnrichmentIdentity, type BulkQColumn} from './bulk'
import type {Config, EnrichmentCompatibility, Result, Source} from './contracts'
import FigurePresentation from './FigurePresentation'
import {ConfigField, Field, Toggle, type ConfigProps} from './InsightShared'
import InsightSources from './InsightSources'
import {strings, text} from './state'
import TaxonField from './TaxonField'

const directions = {both:'双向 DEG',up:'上调 DEG',down:'下调 DEG'} as const
const referenceStatuses:Record<string,string> = {
 declared_reference_matches:'声明的参考版本一致',
 declared_reference_mismatch:'声明的参考版本不一致',
 stable_id_resource_no_assembly_declared:'稳定 ID 资源未声明组装版本',
 resource_reference_not_declared:'资源未声明参考版本',
}
const taxonOrigins:Record<string,string> = {
 fixed_result:'沿用固定结果登记的物种',
 explicit_plan_declaration:'使用本计划明确补充的物种',
}

export function OraForeground({direction,qColumn,qThreshold,effect}:{direction:unknown;qColumn:unknown;qThreshold:unknown;effect:unknown}) {
 const {t} = useI18n()
 const q = text(qColumn)
 const label = directions[direction as keyof typeof directions]
 if (!q||!label) return null
 return <p>{t(label)} · {t(bulkQColumns[q as BulkQColumn]??q)} ({q}) · q ≤ {String(qThreshold)} · |log2FC| ≥ {String(effect)}</p>
}

export function BulkEnrichmentBinding({config,source,result}:{config:Config;source?:Source;result:Result|null}) {
 const {t} = useI18n()
 const gsea = config.kind==='gsea_prerank'
 const saved = result?.methods.config as {contrasts?:{contrast_id:string;groups?:{label:string}[]}[]}|undefined
 const contrasts = gsea?[bulkEnrichmentContrast(config)]:strings(config.contrast_ids)
 return <>
  {source&&<p>{t('固定来源版本')} <code>{source.source_id}</code></p>}
  <p>{t('固定比较')} {contrasts.map((id,index)=>{
   const groups = saved?.contrasts?.find(contrast=>contrast.contrast_id===id)?.groups
   return <span key={id}>{index>0&&' · '}{groups?.[0]&&groups[1]
    ?bulkComparisonLabel({contrast_id:id,numerator:groups[0].label,denominator:groups[1].label}):<code>{id}</code>}</span>
  })}</p>
  {gsea?<p>{t('排序统计量')} <code>wald_statistic</code> · {t('完整排名使用检验状态为可计算的全部有限有符号 Wald 统计量。Cook 过滤等不可计算行保留在映射审计。')}</p>
   :<OraForeground direction={config.direction} qColumn={config.q_column} qThreshold={config.q_threshold} effect={config.minimum_absolute_effect}/>}
 </>
}

export default function BulkEnrichmentSetup({config,onChange,sources,projectId,active,result,onResources}:ConfigProps&{
 projectId:string;active:boolean;result:Result|null;onResources:(resources:Source[])=>void
}) {
 const {t} = useI18n()
 const gsea = config.kind==='gsea_prerank'
 const source = sources.find(item=>item.role==='result')
 const resources = sources.filter(item=>item.role==='gene_sets'||item.role==='resource'||item.role==='id_mapping')
 const declaration = config.bulk_enrichment??{}
 const identity = fixedBulkEnrichmentIdentity(result)
 const params = {config,onChange}
 return <section>
  <h3>{t(gsea?'固定 Bulk GSEA':'固定 Bulk ORA')}</h3>
  <BulkEnrichmentBinding {...{config,source,result}}/>
  {!gsea&&<p>{t('背景为该比较完整的受检基因。空前景会记录为不适用。')}</p>}
  {result&&<div className="analysis-detail">
   <dl>
    <dt>{t('来源命名空间')}</dt><dd>{identity.namespace??t('未登记')}</dd>
    <dt>{t('来源参考版本')}</dt><dd>{identity.reference_version??t('未登记')}</dd>
    <dt>{t('来源物种 taxonomy ID')}</dt><dd>{identity.species_taxon_id??t('未登记')}</dd>
   </dl>
   {identity.species_taxon_id===null&&<>
    <p>{t('固定结果未登记物种。请按原始样本资料填写 taxonomy ID 与物种依据。')}</p>
    <TaxonField label="补充来源物种 taxonomy ID" value={declaration.source_taxon_id}
     registered={resources.flatMap(resource=>resource.species_taxon_id==null?[]:[resource.species_taxon_id])}
     onChange={source_taxon_id=>onChange({...config,bulk_enrichment:{...declaration,source_taxon_id}})}/>
    <Field label="物种依据" type="textarea" value={declaration.taxon_evidence??''}
     onChange={taxon_evidence=>onChange({...config,bulk_enrichment:{...declaration,taxon_evidence}})}/>
   </>}
  </div>}
  <InsightSources projectId={projectId} active={active} value={resources} onChange={onResources} bulkResources/>
  <p className="muted">{t('使用已发布的本地基因集。命名空间不同时请选择方向匹配的固定 ID 映射。')}</p>
  <div className="insight-grid">
   <ConfigField {...params} name="min_size" label="映射并与背景相交后最小集合大小" type="number" min={1} max={1000000}/>
   <ConfigField {...params} name="max_size" label="最大集合大小" type="number" min={1} max={1000000}/>
   {gsea&&<>
    <ConfigField {...params} name="permutation_num" label="置换次数" type="number" min={100} max={10000}/>
    <ConfigField {...params} name="seed" label="固定 seed" type="number" min={0} max={2147483647}/>
    <ConfigField {...params} name="weight" label="GSEA 排名权重" type="number" min={0} max={10} step={0.1}/>
   </>}
  </div>
  {!gsea&&<Toggle label="合并 collection 后统一校正" value={config.merge_collections===true}
   onChange={merge_collections=>onChange({...config,merge_collections})}/>}
 </section>
}

export function BulkEnrichmentCompatibility({value}:{value:EnrichmentCompatibility|null|undefined}) {
 const {t} = useI18n()
 if (!value) return null
 const {source,resources,note} = value
 return <section className="analysis-detail">
  <h3>{t('固定来源与资源兼容性')}</h3>
  {source&&<dl>
   <dt>{t('来源物种 taxonomy ID')}</dt><dd>{source.species_taxon_id??t('未登记')} {source.taxon_origin&&t(taxonOrigins[source.taxon_origin]??source.taxon_origin)}</dd>
   {source.taxon_evidence&&<><dt>{t('物种依据')}</dt><dd>{source.taxon_evidence}</dd></>}
   <dt>{t('来源命名空间')}</dt><dd>{source.namespace??t('未登记')}</dd>
   <dt>{t('来源参考版本')}</dt><dd>{source.reference_version??t('未登记')}</dd>
  </dl>}
  {resources.length>0&&<div className="field-table-scroll"><table className="field-table" aria-label={t('固定资源兼容性')}>
   <thead><tr>{['固定资源版本','资源物种 taxonomy ID','资源命名空间','资源 release','参考版本','参考兼容性','ID 映射'].map(label=><th key={label}>{t(label)}</th>)}</tr></thead>
   <tbody>{resources.map(resource=><tr key={resource.resource_id}>
    <th scope="row">{resource.title??resource.resource_id}</th>
    <td>{resource.species_taxon_id??t('未登记')}</td><td>{resource.namespace??t('未登记')}</td>
    <td>{resource.release}</td><td>{resource.reference_version??t('未登记')}</td>
    <td>{resource.reference_status?t(referenceStatuses[resource.reference_status]??resource.reference_status):'—'}</td>
    <td>{resource.mapping_source_id??'—'}</td>
   </tr>)}</tbody>
  </table></div>}
  {note&&<p>{t(note)}</p>}
 </section>
}

export function BulkEnrichmentFigureSetup({config,onChange,sources}:ConfigProps) {
 const {t} = useI18n()
 const curve = config.figure_type==='gsea'
 return <section>
  <h3>{t(curve?'固定 GSEA 曲线':'固定富集图')}</h3>
  <p>{t('固定来源版本')} <code>{sources[0]?.source_id}</code> · {t('固定比较')} <code>{text(config.contrast_id)}</code></p>
  {curve?<p>{t('GSEA 稳定条目行')} <code>{text(config.term_row_key)}</code></p>
   :<ConfigField {...{config,onChange}} name="enrichment_style" label="富集图样式" options={{dot:'富集点图',bar:'富集条图'}}/>}
  <p>{t('图件使用已发布的富集表或 GSEA 曲线数据。调整外观会保存新的图件版本。')}</p>
  <FigurePresentation {...{config,onChange}} topLabel={curve?undefined:'富集条目 Top N'}/>
 </section>
}
