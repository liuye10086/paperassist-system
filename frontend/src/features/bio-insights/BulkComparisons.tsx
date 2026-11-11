import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {projectBase} from './api'
import {
  bulkComparisonLabel, bulkFigureLabels, bulkQColumns, validBulkSelection,
  type BulkComparisonPage, type BulkFigureType, type BulkPlanSeed, type BulkQColumn,
  type BulkSelection, type BulkSubset,
} from './bulk'
import type {Config, Result, Source} from './contracts'
import {useInsightRead} from './hooks'
import {Field, Paging, ReadState} from './InsightShared'
import {defaultConfig, displayRaw} from './state'

const subsetLabels = {all:'全量',deg:'全部 DEG',up:'上调 DEG',down:'下调 DEG'}
const plotTypes = ['bulk_volcano','bulk_ma','bulk_heatmap','bulk_variable_heatmap','bulk_summary'] as const
const summaryColumns = [
  ['total','总行数'], ['tested','已尝试检验'], ['excluded','未进入检验'],
  ['not_computable','不可计算'], ['missing_metric','所选指标缺失'],
  ['deg','DEG'], ['up','上调'], ['down','下调'],
] as const
const readerColumns = [
  'feature_id','symbol','contrast_id','effect_value','base_mean','statistic','p_value',
  'q_within_contrast','q_global_family','original_method_adjustment','test_status','reason',
]
const pageSize = 50
const defaults = {subset:'all' as BulkSubset,qColumn:'q_within_contrast' as BulkQColumn,q:'0.05',effect:'1',search:''}

export default function BulkComparisons({projectId,result,active,onPlan,allowNewAnalysis=true}:{
  projectId:string
  result:Result
  active:boolean
  onPlan?:(seed:BulkPlanSeed)=>void
  allowNewAnalysis?:boolean
}) {
  const {t} = useI18n()
  const [draft,setDraft] = useState(defaults)
  const [filter,setFilter] = useState(defaults)
  const [requestedContrast,setRequestedContrast] = useState('')
  const [page,setPage] = useState(1)
  const [plot,setPlot] = useState<BulkFigureType>('bulk_volcano')
  const query = new URLSearchParams({
    subset:filter.subset, q_column:filter.qColumn, q_threshold:filter.q,
    minimum_absolute_effect:filter.effect, page:String(page), page_size:String(pageSize),
  })
  if (requestedContrast) query.set('contrast_id',requestedContrast)
  if (filter.search) query.set('search',filter.search)
  const read = useInsightRead<BulkComparisonPage>(
    `${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(result.id)}/bulk-comparisons?${query}`,
    active,true,
  )
  const data = read.data
  const [latest,setLatest] = useState<BulkComparisonPage|null>(null)
  if (data&&data!==latest) setLatest(data)
  const contrasts = (data??latest)?.contrasts??[]
  const contrastId = requestedContrast||(data??latest)?.contrast_id||''
  const selected = data?.contrasts.find(item=>item.contrast_id===data.contrast_id)
  const selection:BulkSelection = {
    contrast_id:data?.contrast_id??'', q_column:filter.qColumn, q_threshold:Number(filter.q),
    minimum_absolute_effect:Number(filter.effect),
    direction:filter.subset==='up'||filter.subset==='down'?filter.subset:'both',
  }
  const dirty = draft.subset!==filter.subset||draft.qColumn!==filter.qColumn||draft.q!==filter.q||draft.effect!==filter.effect
  const invalid = !draft.q||!draft.effect||!validBulkSelection({
    ...selection, contrast_id:contrastId||'default', q_column:draft.qColumn,
    q_threshold:Number(draft.q), minimum_absolute_effect:Number(draft.effect),
  })
  const comparisonReady = !!onPlan&&allowNewAnalysis&&!!selected&&!read.loading&&!read.error
  const actionsReady = comparisonReady&&!dirty
  const resultSource:Source = {
    source_kind:'bio_insight_result_version',source_id:result.id,sha256:result.manifest_sha256,
    role:'result',locator:{kind:'object'},title:selected?bulkComparisonLabel(selected):undefined,
  }
  const startFigure = (figureType:BulkFigureType,featureId?:string) => {
    if (!actionsReady) return
    const config:Config = {
      ...defaultConfig('figure'), result_source_id:result.id, figure_type:figureType, bulk_selection:selection,
      top_n:figureType==='bulk_variable_heatmap'?100:20,
      ...(featureId?{feature_ids:[featureId]}:{}),
    }
    delete config.contrast_id
    onPlan?.({source:resultSource,config})
  }
  const startCandidate = () => {
    if (!actionsReady) return
    onPlan?.({
      source:resultSource,
      config:{
        ...defaultConfig('candidate'), result_source_ids:[result.id], primary_result_source_id:result.id,
        source_contrasts:{[result.id]:selection.contrast_id}, steps:[], bulk_selection:selection, bulk_top_n:20,
      },
    })
  }
  const startEnrichment = (kind:'ora'|'gsea_prerank') => {
    if (!comparisonReady||kind==='ora'&&dirty) return
    const {contrast_id,...foreground} = selection
    const config:Config = kind==='ora'
      ?{...defaultConfig(kind),result_source_ids:[result.id],contrast_ids:[contrast_id],...foreground,bulk_enrichment:{}}
      :{...defaultConfig(kind),result_source_id:result.id,contrast_id,ranking_column:'wald_statistic',bulk_enrichment:{}}
    onPlan?.({source:resultSource,config})
  }
  const deg = selection.direction==='both'?selected?.deg:selected?.[selection.direction]
  const columns = data?readerColumns.filter(column=>data.columns.includes(column)):[]
  return <section className="analysis-detail" aria-label={t('Bulk 多比较查询')}>
    <h3>{t('Bulk 多比较查询')}</h3>
    <p>{t('正 log2FC 表示分子组表达较高。筛选使用已保存的 MLE log2FC 与所选调整指标，条件为 q ≤ 阈值且 |log2FC| ≥ 阈值。')}</p>
    <form onSubmit={event=>{
      event.preventDefault()
      if (invalid) return
      const next = {...draft,search:draft.search.trim()}
      setDraft(next)
      setFilter(next)
      setPage(1)
    }}>
      <div className="insight-grid">
        <Field label="固定比较" value={contrastId} onChange={value=>{setRequestedContrast(value);setPage(1)}}>
          {!contrasts.length&&<option value="">{t('读取默认比较')}</option>}
          {contrasts.map(item=><option key={item.contrast_id} value={item.contrast_id}>{bulkComparisonLabel(item)}</option>)}
        </Field>
        <Field label="结果范围" value={draft.subset} onChange={value=>setDraft({...draft,subset:value as BulkSubset})}>
          {Object.entries(subsetLabels).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}
        </Field>
        <Field label="q 值口径" value={draft.qColumn} onChange={value=>setDraft({...draft,qColumn:value as BulkQColumn})}>
          {Object.entries(bulkQColumns).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}
        </Field>
        <Field label="q 阈值" type="number" min={0} max={1} step="any" value={draft.q} onChange={q=>setDraft({...draft,q})}/>
        <Field label="最小绝对 log2FC" type="number" min={0} max={1000000} step="any" value={draft.effect} onChange={effect=>setDraft({...draft,effect})}/>
        <label>{t('特征搜索')}<input maxLength={200} value={draft.search} onChange={event=>setDraft({...draft,search:event.target.value})}/></label>
      </div>
      <button type="submit" disabled={invalid}>{t('应用筛选')}</button>
    </form>
    <p className="muted">{t('比较内 BH 使用单个比较的检验族。冻结比较族 BH 使用已声明的跨比较检验族。模型原生调整值可因独立过滤而缺失。')}</p>
    <p className="muted">{t('全量按原表顺序。DEG 按所选 q 升序、绝对效应降序、稳定 ID 排序。零效应归为无方向。')}</p>
    {invalid&&<p role="alert">{t('请输入 0–1 的 q 阈值与 0–1,000,000 的最小绝对效应。')}</p>}
    <ReadState {...read}/>
    {data&&selected&&<>
      <p><strong>{bulkComparisonLabel(selected)}</strong> · {t(bulkQColumns[selection.q_column])} ({selection.q_column}) · q ≤ {selection.q_threshold} · |log2FC| ≥ {selection.minimum_absolute_effect}</p>
      <div className="field-table-scroll"><table className="field-table" aria-label={t('Bulk 比较汇总')}>
        <thead><tr><th>{t('固定比较')}</th>{summaryColumns.map(([key,label])=><th key={key}>{t(label)}</th>)}</tr></thead>
        <tbody>{data.contrasts.map(item=><tr key={item.contrast_id} aria-current={item.contrast_id===data.contrast_id?'true':undefined}>
          <th scope="row">{bulkComparisonLabel(item)}</th>{summaryColumns.map(([key])=><td key={key}>{item[key]}</td>)}
        </tr>)}</tbody>
      </table></div>
      <p className="muted">{t('已尝试检验包含不可计算行。NA 为缺失或不可计算，0 为保存的数值。精确稳定 ID 可跨比较核对。')}</p>
      <p>{t('当前范围匹配 {matched} 行，当前比较全量 {total} 行。',{matched:data.matched_total,total:data.total})}</p>
      {deg===0&&<p role="status">{t('当前比较在此阈值和方向下有 0 个 DEG。')}</p>}
      {onPlan&&<section aria-label={t('使用当前固定比较')}>
        <div className="intake-actions">
          <Field label="Bulk 图型" value={plot} onChange={value=>setPlot(value as BulkFigureType)}>
            {plotTypes.map(kind=><option key={kind} value={kind}>{t(bulkFigureLabels[kind])}</option>)}
          </Field>
          <button type="button" disabled={!actionsReady} onClick={()=>startFigure(plot)}>{t('按当前筛选绘图')}</button>
          <button type="button" disabled={!actionsReady} onClick={startCandidate}>{t('保存当前筛选为候选计划')}</button>
        </div>
        <p className="muted">{t('图件和候选使用整个固定比较的阈值与方向。特征搜索和分页只影响此处浏览。')}</p>
        <div className="intake-actions">
          <button type="button" disabled={!actionsReady} onClick={()=>startEnrichment('ora')}>{t('用当前筛选配置 ORA')}</button>
          <button type="button" disabled={!comparisonReady} onClick={()=>startEnrichment('gsea_prerank')}>{t('用完整 Wald 排名配置 GSEA')}</button>
        </div>
        <p className="muted">{t('ORA 使用已应用的 DEG 阈值与方向。GSEA 使用所选比较的完整有符号 Wald 排名，包括未达 DEG 阈值的基因。')}</p>
      </section>}
      <BulkRows title="Bulk 比较结果" columns={columns} rows={data.items}
        onExpression={onPlan?featureId=>startFigure('bulk_expression',featureId):undefined} disabled={!actionsReady}/>
      {!data.items.length&&<p>{t('当前范围没有匹配行，完整结果仍可下载。')}</p>}
      <Paging page={page} size={pageSize} total={data.matched_total} onPage={setPage}/>
      {data.feature_matches.length>0&&<BulkRows title="同一稳定 ID 的跨比较结果" columns={columns} rows={data.feature_matches}/>}
    </>}
  </section>
}

function BulkRows({title,columns,rows,onExpression,disabled}:{title:string;columns:string[];rows:Record<string,unknown>[];onExpression?:(id:string)=>void;disabled?:boolean}) {
  const {t} = useI18n()
  return <div className="field-table-scroll"><table className="field-table" aria-label={t(title)}>
    <thead><tr>{columns.map(column=><th key={column}>{column}</th>)}{onExpression&&<th>{t('单基因表达')}</th>}</tr></thead>
    <tbody>{rows.map((row,index)=><tr key={String(row.row_key??index)}>
      {columns.map(column=><td key={column}>{displayRaw(row[column])}</td>)}
      {onExpression&&<td>{typeof row.feature_id==='string'&&row.feature_id&&<button type="button" disabled={disabled}
        aria-label={t('绘制表达 · {id}',{id:row.feature_id})}
        onClick={()=>onExpression(String(row.feature_id))}>{t('绘制表达')}</button>}</td>}
    </tr>)}</tbody>
  </table></div>
}
