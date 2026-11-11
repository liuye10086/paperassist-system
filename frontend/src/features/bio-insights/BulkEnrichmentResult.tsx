import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import {BULK_ORA_ELIGIBLE_BACKGROUND, bulkEnrichmentContrast, type BulkPlanSeed} from './bulk'
import type {Config, EnrichmentResourceIdentity, EnrichmentSourceIdentity, Result} from './contracts'
import {BulkEnrichmentCompatibility, OraBackground, OraForeground} from './BulkEnrichmentSetup'
import {Field} from './InsightShared'
import {defaultConfig, text} from './state'

const statuses:Record<string,string> = {
 completed:'富集已完成',no_significant_terms:'无显著富集条目',not_applicable:'富集不适用',
}
const reasons:Record<string,string> = {
 empty_foreground:'固定筛选得到空前景。',
 insufficient_resource_background:'映射后与资源相交的背景不足。',
 empty_effective_foreground:'前景映射后与资源没有有效交集。',
 no_eligible_terms:'没有满足当前基因集大小范围的可计算条目。',
 ranking_all_equal:'所有可用排序分值相同，无法形成有意义的排序。',
 ranking_all_zero_or_insufficient:'可用有符号排序不足或分值全为零。',
 no_applicable_enrichment_families:'各比较或资源均不适用。',
}
export const bulkEnrichmentReason = (reason:string) => reasons[reason]??reason
type Counts = Partial<Record<'original_count'|'mapped_count'|'unmapped_count'|'ambiguous_count'|'invalid_count'|
 'many_to_one_collapse_count'|'many_to_one_conflict_count'|'out_of_resource_count'|'effective_count'|'tied_rank_count',number>>
type ScopeCounts = {resource_gene_count?:number;effective_count?:number;out_of_resource_count?:number;eligible_term_count?:number;not_applicable_reason?:string|null}
type Coverage = ScopeCounts&{
 result_source_id:string;contrast_id:string;resource_id:string
 background?:Counts;foreground?:Counts;ranking?:Counts;resources?:Record<string,ScopeCounts>
}
type BulkMethods = {
 source_reference:EnrichmentSourceIdentity;resource_references:Record<string,Omit<EnrichmentResourceIdentity,'resource_id'>>;coverage:Coverage[]
}
const methods = (result:Result) => result.methods.bulk_enrichment as BulkMethods
const countColumns = [
 ['original_count','输入 ID 数'],['mapped_count','映射目标数'],['unmapped_count','未映射数'],
 ['ambiguous_count','歧义数'],['invalid_count','无效 ID 数'],['out_of_resource_count','资源外 ID 数'],['effective_count','实际保留数'],
] as const
const ratio = (count?:number,total?:number) => count==null||!total?'—':`${(count*100/total).toFixed(1)}%`

export function bulkEnrichmentFigureSeed(result:Result,contrast:string,choice:{style:'dot'|'bar'}|{termRowKey:string}):BulkPlanSeed {
 const config:Config = {...defaultConfig('figure'),result_source_id:result.id,contrast_id:contrast,bulk_enrichment_render:true,
  ...('style' in choice?{figure_type:'enrichment',enrichment_style:choice.style,enrichment_order:'adjusted_metric_term_id'}
   :{figure_type:'gsea',term_row_key:choice.termRowKey})}
 return {config,source:{source_kind:'bio_insight_result_version',source_id:result.id,sha256:result.manifest_sha256,role:'result',locator:{kind:'object'}}}
}

export function bulkEnrichmentResultContrast(result:Result) {
 const config = result.methods?.config as Config|undefined
 return methods(result).coverage[0]?.contrast_id??(config?bulkEnrichmentContrast(config):'')
}

export default function BulkEnrichmentResult({result,onPlan,onNavigate}:{
 result:Result;onPlan?:(seed:BulkPlanSeed)=>void;onNavigate?:(navigation:AnalysisNavigation)=>void
}) {
 const {t} = useI18n()
 const [selection,setSelection] = useState('')
 const gsea = result.kind==='gsea_prerank'
 const eligibleBackground = result.methods.background===BULK_ORA_ELIGIBLE_BACKGROUND
 const audit = methods(result)
 const {enrichment_status,not_applicable_reason,significant_terms} = result.summary
 const status = text(enrichment_status)
 const reason = text(not_applicable_reason)
 const scope = audit.coverage[0]
 const contrasts = [...new Set(audit.coverage.map(item=>item.contrast_id))]
 const plotContrasts = gsea?contrasts:[...new Set(audit.coverage.filter(item=>item.eligible_term_count==null
  ?!item.not_applicable_reason:item.eligible_term_count>0).map(item=>item.contrast_id))]
 const contrast = plotContrasts.includes(selection)?selection:plotContrasts[0]??(gsea?bulkEnrichmentResultContrast(result):'')
 const hasTerms = status!=='not_applicable'&&result.members.some(member=>member.key==='enrichment_results')
 const resources = Object.entries(audit.resource_references).map(([resource_id,identity])=>({...identity,resource_id}))
 return <section className="analysis-detail" aria-label={t('固定 Bulk 富集结果')}>
  <h3>{t(gsea?'固定 Bulk GSEA':'固定 Bulk ORA')}</h3>
  {status&&<p role="status"><strong>{t(statuses[status]??status)}</strong></p>}
  {reason&&<p>{t(reasons[reason]??reason)}</p>}
  {typeof significant_terms==='number'&&status!=='not_applicable'&&<p>{t('显著条目 {count} 项（调整指标 ≤ 0.05）。',{count:significant_terms})}</p>}
  <p><strong>{gsea?'GSEA FDR':'ORA BH q'}</strong> · {t(gsea?'置换联合零分布校正。':'固定富集检验族内的 BH 校正。')}</p>
  {gsea?<p>{t('NES 为正表示基因集富集在分子组方向，NES 为负表示富集在分母组方向。0 保留为经验置换估计值，精度由置换次数限定。')}</p>
   :<><OraForeground direction={result.methods.direction} qColumn={result.methods.q_column}
    qThreshold={result.methods.q_threshold} effect={result.methods.minimum_absolute_effect}/>
    <OraBackground eligible={eligibleBackground}/></>}
  {gsea&&status!=='not_applicable'&&!!scope?.ranking?.tied_rank_count&&<p>{t('相同分值按稳定基因 ID 排序。')}</p>}
  {scope&&<p>{t('固定来源版本')} <code>{scope.result_source_id}</code> · {t('固定比较')} {contrasts.join(' · ')}</p>}
  <div className="intake-actions">
   {scope&&onNavigate&&<button type="button" onClick={()=>onNavigate({view:'bio-insight-result',fileId:'',resultVersionId:scope.result_source_id})}>{t('打开此版本的固定来源')}</button>}
   {onPlan&&hasTerms&&contrast&&<>
    {plotContrasts.length>1&&<Field label="绘图固定比较" value={contrast} onChange={setSelection}>
     {plotContrasts.map(id=><option key={id} value={id}>{id}</option>)}
    </Field>}
    <button type="button" onClick={()=>onPlan(bulkEnrichmentFigureSeed(result,contrast,{style:'dot'}))}>{t('绘制富集点图')}</button>
    <button type="button" onClick={()=>onPlan(bulkEnrichmentFigureSeed(result,contrast,{style:'bar'}))}>{t('绘制富集条图')}</button>
   </>}
  </div>
  <BulkEnrichmentCompatibility value={{source:audit.source_reference,resources}}/>
  <MappingCoverage coverage={audit.coverage} resources={resources} eligibleBackground={eligibleBackground}/>
 </section>
}

function MappingCoverage({coverage,resources,eligibleBackground}:{
 coverage:Coverage[];resources:EnrichmentResourceIdentity[];eligibleBackground:boolean
}) {
 const {t} = useI18n()
 const name = (id:string) => resources.find(resource=>resource.resource_id===id)?.release??id
 const scopes = coverage.flatMap(scope=>scope.ranking
  ?[{scope,role:'完整排序',counts:scope.ranking}]
  :[{scope,role:eligibleBackground?'可计算背景':'受检背景',counts:scope.background},{scope,role:'筛选前景',counts:scope.foreground}])
 const rankingResources = coverage.flatMap(scope=>Object.entries(scope.resources??{}).map(([id,counts])=>({scope,id,counts})))
 if (!scopes.length) return null
 return <section>
  <h3>{t('富集 ID 映射覆盖')}</h3>
  <div className="field-table-scroll"><table className="field-table" aria-label={t('富集 ID 映射覆盖')}>
   <thead><tr>{['固定比较','资源 release','映射范围',...countColumns.map(([,label])=>label),
    '未映射率','歧义率','多对一影响数','并列排名数与比例','不适用原因'].map(label=><th key={label}>{t(label)}</th>)}</tr></thead>
   <tbody>{scopes.map(({scope,role,counts})=><tr key={`${scope.contrast_id}:${scope.resource_id}:${role}`}>
    <th scope="row">{scope.contrast_id}</th><td>{scope.resource_id==='joint'?t('联合基因集'):name(scope.resource_id)}</td><td>{t(role)}</td>
    {countColumns.map(([key])=><td key={key}>{counts?.[key]??'—'}</td>)}
    <td>{ratio(counts?.unmapped_count,counts?.original_count)}</td><td>{ratio(counts?.ambiguous_count,counts?.original_count)}</td>
    <td>{counts?.many_to_one_collapse_count??counts?.many_to_one_conflict_count??'—'}</td>
    <td>{counts?.tied_rank_count==null?'—':`${counts.tied_rank_count} · ${ratio(counts.tied_rank_count,counts.effective_count)}`}</td>
    <td>{scope.not_applicable_reason?t(reasons[scope.not_applicable_reason]??scope.not_applicable_reason):'—'}</td>
   </tr>)}</tbody>
  </table></div>
  <p className="muted">{t('未映射率与歧义率以各行输入 ID 数为分母。原始 ID、目标 ID、排除原因和稳定行键见 mapping_rows 与 mapping_exclusions。')}</p>
  {rankingResources.length>0&&<div className="field-table-scroll"><table className="field-table" aria-label={t('GSEA 基因集覆盖')}>
   <thead><tr>{['资源 release','资源基因数','排名内资源基因数','排名中资源外基因数','可计算条目数','不适用原因'].map(label=><th key={label}>{t(label)}</th>)}</tr></thead>
   <tbody>{rankingResources.map(({scope,id,counts})=><tr key={`${scope.contrast_id}:${id}`}>
    <th scope="row">{name(id)}</th><td>{counts.resource_gene_count??'—'}</td><td>{counts.effective_count??'—'}</td>
    <td>{counts.out_of_resource_count??'—'}</td><td>{counts.eligible_term_count??'—'}</td>
    <td>{counts.not_applicable_reason?t(reasons[counts.not_applicable_reason]??counts.not_applicable_reason):'—'}</td>
   </tr>)}</tbody>
  </table></div>}
 </section>
}

export function BulkEnrichmentFigureResult({result,onNavigate}:{result:Result;onNavigate?:(navigation:AnalysisNavigation)=>void}) {
 const {t} = useI18n()
 const config = result.methods?.config as Config|undefined
 if (result.kind!=='figure'||config?.bulk_enrichment_render!==true) return null
 const curve = config.figure_type==='gsea'
 const source = text(config.result_source_id)
 return <section className="analysis-detail">
  <h3>{t(curve?'固定 GSEA 曲线':config.enrichment_style==='bar'?'富集条图':'富集点图')}</h3>
  <p>{t('固定来源版本')} <code>{source}</code> · {t('固定比较')} <code>{text(config.contrast_id)}</code></p>
  {curve&&<p>{t('GSEA 稳定条目行')} <code>{text(config.term_row_key)}</code></p>}
  {onNavigate&&<div className="intake-actions">
   <button type="button" onClick={()=>onNavigate({view:'bio-insight-plan',fileId:'',runId:result.run_id})}>{t('打开固定计划修改样式')}</button>
   <button type="button" onClick={()=>onNavigate({view:'bio-insight-result',fileId:'',resultVersionId:source})}>{t('打开此版本的固定来源')}</button>
  </div>}
 </section>
}
