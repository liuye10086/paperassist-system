import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import NativeDeliveryArtifact,{type NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import type {Source as ResearchSource} from '../research-results/contracts'
import {projectBase} from './api'
import {bulkComparisonLabel, bulkFigureLabels, bulkPanels, bulkPanelTab, bulkQColumns, isBulkEnrichmentResult, isBulkFigureType, isBulkPanel, isBulkProcessedFigure, isReviewedBulkComparison, validBulkSelection, type BulkPlanSeed, type BulkSelection} from './bulk'
import {kindLabels,type Result,type TablePage} from './contracts'
import {figureName,resultFileName,resultTableLabels} from '../bioinformatics/bioPresentation'
import {useInsightRead} from './hooks'
import BulkComparisons from './BulkComparisons'
import BulkEnrichmentResult,{BulkEnrichmentFigureResult,bulkEnrichmentFigureSeed,bulkEnrichmentResultContrast} from './BulkEnrichmentResult'
import InsightDelivery from './InsightDelivery'
import InsightImpact from './InsightImpact'
import {DataDetails, Field, Members, Paging, ReadState, TaskStatus} from './InsightShared'
import SingleCellInsightSummary from './SingleCellInsightSummary'
import SingleCellTopicSummary from './SingleCellTopicSummary'
import {displayRaw} from './state'
import {bulkRoute} from './bulkWorkflow'

const analysisScopeLabels:Record<string,string>={sample_inference:'按独立样本推断',sample_exploratory:'样本探索',spot_exploratory:'区域探索',donor_inference:'按供者推断',external_result:'外部结果'}
export default function InsightResults({projectId,resultId,active,onResearch,onNavigate,onBulkPlan,allowNewAnalysis,resultRead,deliveryTarget}: {
 projectId:string
 resultId:string
 active:boolean
 onResearch:(source:ResearchSource)=>void
 onNavigate?:(navigation:AnalysisNavigation)=>void
 onBulkPlan?:(seed:BulkPlanSeed)=>void
 allowNewAnalysis?:boolean
 resultRead?:ReturnType<typeof useInsightRead<Result>>
 deliveryTarget?:NativeDeliveryTarget
}) {
 const {t} = useI18n()
 const fallback = useInsightRead<Result>(`${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(resultId)}`,active&&!resultRead,true)
 const result = resultRead??fallback
 const data = result.data
 const reviewedBulk = isReviewedBulkComparison(data)
 const bulkEnrichment = isBulkEnrichmentResult(data)
 const [fullOpen,setFullOpen] = useState(false)
 return <section>
  <h3>{t('固定分析结果详情')}</h3><ReadState {...result}/>
  {data&&<>
   <p>{t(kindLabels[data.kind])} · <strong>{t(analysisScopeLabels[data.inference_scope]??'推断范围待核对')}</strong></p>
   <p className="warning-panel">{t('技术重复不增加独立样本量。解读结果前请核对研究设计与来源。')}</p>
   {data.summary.synthetic===true&&<p className="warning-panel">{t('合成工程样例，不代表真实客户供体验证或生物学验证。')}</p>}
   {reviewedBulk&&onNavigate&&<div className="intake-actions">
    <button type="button" onClick={()=>onNavigate(bulkRoute('differential',data.id))}>{t('查看稳健性对照设置')}</button>
    <button type="button" onClick={()=>onNavigate(bulkRoute('delivery',data.id))}>{t('以此固定比较准备交付')}</button>
   </div>}
   {reviewedBulk&&<BulkComparisons key={'bulk:'+data.id} {...{projectId,result:data,active,allowNewAnalysis}} onPlan={onBulkPlan}/>}
   {bulkEnrichment&&<BulkEnrichmentResult key={'enrichment:'+data.id} result={data} onNavigate={onNavigate} onPlan={allowNewAnalysis===false?undefined:onBulkPlan}/>}
   <BulkEnrichmentFigureResult result={data} onNavigate={onNavigate}/>
   <BulkPublishedDetails result={data} onNavigate={onNavigate}/>
   <SingleCellInsightSummary result={data}/><SingleCellTopicSummary result={data}/>
   <InsightDelivery key={'delivery:'+data.id} projectId={projectId} result={data}/>
   <DataDetails title="结果概况与样例标记" value={data.summary}/><TaskStatus projectId={projectId} task={data.task}/>
   <button type="button" onClick={()=>onResearch({source_kind:'bio_insight_result_version',source_id:resultId,sha256:data.manifest_sha256,locator:{kind:'object'}})}>{t('将此固定结果送入研究发现')}</button>
   <LazyResultDetails key={'methods:'+projectId+':'+data.id} title="方法、统计单位与校正族" expand="展开方法详情" collapse="收起方法详情" value={data.methods}/>
   <LazyResultDetails key={'manifest:'+projectId+':'+data.id} title="完整来源、环境、限制与清单" expand="展开完整来源与清单" collapse="收起完整来源与清单" value={data.manifest}/>
   <InsightImpact key={'impact:'+data.id} projectId={projectId} id={data.id}/>
   {reviewedBulk&&<button type="button" aria-expanded={fullOpen} onClick={()=>setFullOpen(value=>!value)}>{t(fullOpen?'收起完整结果表预览':'打开完整结果表预览')}</button>}
   {(!reviewedBulk||fullOpen)&&<ResultTables key={'tables:'+data.id} {...{projectId,data,active,onResearch}}
    onCurve={bulkEnrichment&&data.kind==='gsea_prerank'&&allowNewAnalysis!==false&&onBulkPlan&&data.members.some(member=>member.key==='gsea_curves')
     ?(key,contrast)=>onBulkPlan(bulkEnrichmentFigureSeed(data,contrast||bulkEnrichmentResultContrast(data),{termRowKey:key}))
     :undefined}/>}
   {data.members.filter(member=>member.format==='png').map(member=><div className="intake-actions" key={member.id}>
    <button type="button" onClick={()=>onResearch({source_kind:'bio_insight_result_member',source_id:member.id,sha256:member.sha256,locator:{kind:'image'}})}>{t('引用图件')} · {figureName(member.key,t,String(data.summary.figure_type??''))}</button>
    {data.id===resultId&&data.task.status==='succeeded'&&<NativeDeliveryArtifact {...{projectId,deliveryTarget}}
     source={{kind:'bio_insight_png',version_id:data.id,member_id:member.id}} name={resultFileName(member,t,String(data.summary.figure_type??''))}/>}
   </div>)}
   <Members projectId={projectId} members={data.members} figureKind={String(data.summary.figure_type??'')}/>
  </>}
 </section>
}

function BulkPublishedDetails({result,onNavigate}:{result:Result;onNavigate?:(navigation:AnalysisNavigation)=>void}) {
 const {t} = useI18n()
 const kind = result.summary.figure_type
 const figure = result.kind==='figure'&&isBulkFigureType(kind)?kind:null
 const candidate = result.kind==='candidate'&&validBulkSelection(result.methods.bulk_selection)
  ?result.methods.bulk_selection as BulkSelection & Record<string,unknown>:null
 if (!figure&&!candidate) return null
 const config = result.methods.config as Record<string,unknown>|undefined
 const selection = candidate??(validBulkSelection(config?.bulk_selection)?config.bulk_selection:null)
 const axes = result.methods.axes as {x?:string;y?:string}|undefined
 const processed = isBulkProcessedFigure(figure)
 const panel = config?.bulk_panel
 const sourceId = candidate?.source_result_version_id??result.methods.source_id
 const {candidate_count,displayed_count,displayed_feature_count,top_n} = result.summary
 const actualTop = figure?displayed_feature_count:displayed_count
 const requestedTop = result.summary.requested_top_n??top_n
 const numerator = candidate?.numerator??result.summary.numerator
 const denominator = candidate?.denominator??result.summary.denominator
 return <section className="analysis-detail" aria-label={t(figure?'固定 Bulk 图件':'固定 Bulk 候选')}>
  <h3>{t(figure?bulkFigureLabels[figure]:'固定 Bulk 候选')}</h3>
  {processed&&isBulkPanel(panel)&&<p>{t(bulkPanels[panel])} · {t('复用已保存的 B03 数值。')}</p>}
  {selection&&<p>{typeof numerator==='string'&&typeof denominator==='string'
   ?bulkComparisonLabel({contrast_id:selection.contrast_id,numerator,denominator})
   :selection.contrast_id} · {t(bulkQColumns[selection.q_column])} ({selection.q_column}) · q ≤ {selection.q_threshold} · |log2FC| ≥ {selection.minimum_absolute_effect} · {t(selection.direction==='both'?'双向 DEG':selection.direction==='up'?'上调 DEG':'下调 DEG')}</p>}
  {figure&&<>
   {axes&&<p>X · {axes.x} / Y · {axes.y}</p>}
   {config?.z_score===true&&<p>{t('图上使用行 z-score，固定表达值可在图数据中核对。')}</p>}
   {result.summary.empty_result===true&&<p role="status">{t('此图的实际绘制范围为空，原因见图数据与方法。')}</p>}
  </>}
  {typeof actualTop==='number'&&typeof requestedTop==='number'&&<p>{t(
   figure==='bulk_volcano'||figure==='bulk_ma'?'实际标注 {actual} 个基因，设定 Top N 为 {requested}。':'实际展示 {actual} 项，设定 Top N 为 {requested}。',
   {actual:actualTop,requested:requestedTop},
  )}</p>}
  {typeof candidate_count==='number'&&<p>{t('完整候选共 {count} 项。',{count:candidate_count})}</p>}
  {onNavigate&&<div className="intake-actions">
   {result.run_id&&<button type="button" onClick={()=>onNavigate({view:'bio-insight-plan',fileId:'',runId:result.run_id})}>{t(figure?'打开固定计划修改样式':'打开候选的固定计划')}</button>}
   {typeof sourceId==='string'&&(!processed||isBulkPanel(panel))&&<button type="button" onClick={()=>{
    if (processed&&isBulkPanel(panel)) onNavigate({view:'bio-result',fileId:'',processedId:sourceId,tab:bulkPanelTab(panel)})
    else onNavigate({view:'bio-insight-result',fileId:'',resultVersionId:sourceId})
   }}>{t('打开此版本的固定来源')}</button>}
  </div>}
 </section>
}

function ResultTables({projectId,data,active,onResearch,onCurve}:{projectId:string;data:Result;active:boolean;onResearch:(source:ResearchSource)=>void;onCurve?:(rowKey:string,contrast:string)=>void}) {
 const {t} = useI18n()
 const [key,setKey] = useState(''),[page,setPage] = useState(1),[search,setSearch] = useState(''),[query,setQuery] = useState(''),[column,setColumn] = useState('')
 const tables = data.members.filter(member=>['tsv','csv'].includes(member.format))
 const candidate = data.kind==='candidate'&&validBulkSelection(data.methods.bulk_selection)
 const enrichment = isBulkEnrichmentResult(data)
 const label = candidate?'候选结果表':'完整结果表'
 const defaultTable = candidate?'bulk_candidate_top':enrichment?'enrichment_results':undefined
 const selected = tables.find(member=>member.key===key)??tables.find(member=>member.key===defaultTable)??tables[0]
 const curve = selected?.key==='enrichment_results'?onCurve:undefined
 const table = useInsightRead<TablePage>(selected?`${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(data.id)}/tables/${encodeURIComponent(selected.key)}?page=${page}&page_size=50${query?'&search='+encodeURIComponent(query):''}`:'',active&&!!selected,true)
 const resultColumn = column||table.data?.columns.find(name=>!['row_key','contrast_id','feature_id'].includes(name))||table.data?.columns[0]||''
 const rowKey = (row:Record<string,unknown>) => {
  const identity:Record<string,string> = {row_key:String(row.row_key)}
  const config = data.methods.config
  if(data.kind==='comparison'&&['sample_inference','sample_exploratory'].includes(data.inference_scope)&&config!==null&&typeof config==='object'&&'schema_version' in config&&config.schema_version===2) {
   for(const field of ['feature_id','contrast_id']) if(typeof row[field]==='string'&&row[field]) identity[field]=row[field] as string
  }
  return identity
 }
 if (!selected) return <p>{t('此结果没有可分页表；请查看方法、空结果说明及完整成员。')}</p>
 return <>
  <Field label={label} value={selected.key} onChange={value=>{setKey(value);setPage(1);setSearch('');setQuery('');setColumn('')}}>
   {tables.map(member=><option key={member.id} value={member.key}>{candidate&&member.key==='bulk_candidate_top'
    ?t('候选 Top N 预览'):candidate&&member.key==='candidate_results'?t('完整候选表'):t(resultTableLabels[member.key]??'分析结果表')}</option>)}
  </Field>
  <form onSubmit={event=>{event.preventDefault();setPage(1);setQuery(search)}}>
   <Field label="搜索完整结果" value={search} onChange={setSearch}/><button type="submit">{t('搜索')}</button>
  </form>
  <ReadState {...table}/>
  {table.data&&<>
   <p>{t('完整文件总行数')} {table.data.total} · {t('搜索匹配')} {table.data.matched_total} · {t('原始文本值保持，0 与 NA 不互换。')}</p>
   <Field label="引用到研究发现的结果列" value={resultColumn} onChange={setColumn}>{table.data.columns.map(name=><option key={name}>{name}</option>)}</Field>
   <div className="field-table-scroll"><table className="field-table" aria-label={t(label)}>
    <thead><tr>{curve&&<th>{t('GSEA 曲线')}</th>}{table.data.columns.map(name=><th key={name}>{name}</th>)}<th>{t('研究引用')}</th></tr></thead>
    <tbody>{table.data.items.map((row,index)=><tr key={String(row.row_key??index)}>
     {curve&&<td>{typeof row.row_key==='string'&&row.row_key&&<button type="button"
      aria-label={t('绘制已保存 GSEA 曲线 · {term}',{term:String(row.term_id??row.row_key)})}
      onClick={()=>curve(String(row.row_key),typeof row.contrast_id==='string'?row.contrast_id:'')}>{t('绘制已保存 GSEA 曲线')}</button>}</td>}
     {table.data!.columns.map(name=><td key={name}>{displayRaw(row[name])}</td>)}
     <td><button type="button" disabled={row.row_key==null} onClick={()=>onResearch({source_kind:'bio_insight_result_member',source_id:selected.id,sha256:selected.sha256,locator:{kind:'row',table:selected.key,row_key:rowKey(row),column:resultColumn}})}>{t('引用此行到研究发现')}</button></td>
    </tr>)}</tbody>
   </table></div>
   {!table.data.items.length&&<p>{t('没有匹配行或没有候选；这不会改写完整结果，方法和完整文件仍可下载。')}</p>}
   <Paging page={page} size={50} total={table.data.matched_total} onPage={setPage}/>
  </>}
 </>
}

function LazyResultDetails({title,expand,collapse,value}:{title:string;expand:string;collapse:string;value:unknown}) {
 const {t} = useI18n(),[open,setOpen] = useState(false)
 return <section><button type="button" aria-expanded={open} onClick={()=>setOpen(value=>!value)}>{t(open?collapse:expand)}</button>{open&&<DataDetails title={title} value={value}/>}</section>
}
