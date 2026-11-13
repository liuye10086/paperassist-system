import {useI18n} from '../../shared/i18n'
import {projectBase} from './api'
import {
  bulkComparisonLabel, bulkFigureLabels, bulkPanels, bulkQColumns, isBulkFigureType, isBulkHeatmap,
  isBulkPanel, isBulkProcessedFigure, validBulkSelection,
} from './bulk'
import type {Result} from './contracts'
import {useInsightRead} from './hooks'
import {ConfigField, ReadState, Toggle, type ConfigProps} from './InsightShared'
import {strings} from './state'
import FigurePresentation from './FigurePresentation'

const directionLabels = {both:'双向 DEG',up:'上调 DEG',down:'下调 DEG'}
const figureNotes = {
  bulk_volcano:'X 为 MLE log2FC，Y 为 −log10(所选调整值)。q = 0 仅在图上显示为裁剪值。',
  bulk_ma:'X 为模型保存的标准化均值（对数轴），Y 为 MLE log2FC。所选调整值与效应量用于标记 DEG。',
  bulk_heatmap:'从所选 DEG 按 q 升序、绝对效应降序、稳定 ID 排序，读取固定的模型标准化表达。',
  bulk_variable_heatmap:'从模型标准化表达按行 z-score 前的样本方差降序选基因，方差相同按稳定 ID 排序。高变基因是单独的显示集合。',
  bulk_expression:'使用同一固定模型的标准化 counts，按实际样本分组显示。',
  bulk_summary:'按冻结的 q 和效应量汇总已保存差异结果与上调、下调数量。',
} as const

export default function BulkPlanSettings({projectId,active,config,onChange,sources}:ConfigProps&{
  projectId:string
  active:boolean
}) {
  const {t} = useI18n()
  const figureType = isBulkFigureType(config.figure_type)?config.figure_type:null
  const panel = isBulkPanel(config.bulk_panel)?config.bulk_panel:null
  const selection = validBulkSelection(config.bulk_selection)?config.bulk_selection:null
  const source = sources[0]
  const result = useInsightRead<Result>(
    selection&&source?`${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(source.source_id)}`:'',
    active&&!!selection,true,
  )
  const resultConfig = result.data?.methods?.config as {contrasts?:{contrast_id:string;groups?:{label:string}[]}[]}|undefined
  const contrast = resultConfig?.contrasts?.find(item=>item.contrast_id===selection?.contrast_id)
  const groups = contrast?.groups
  const comparison = contrast&&groups?.[0]&&groups[1]
    ?bulkComparisonLabel({contrast_id:contrast.contrast_id,numerator:groups[0].label,denominator:groups[1].label})
    :selection?.contrast_id
  const heatmap = isBulkHeatmap(figureType)
  const topLabel = figureType==='bulk_variable_heatmap'?'高变基因展示 Top N'
    :figureType==='bulk_heatmap'?'DEG 热图展示 Top N'
    :figureType==='bulk_volcano'||figureType==='bulk_ma'?'DEG 标注 Top N':undefined
  return <section>
    <h3>{t(panel?bulkPanels[panel]:figureType?bulkFigureLabels[figureType]:'冻结 Bulk 候选')}</h3>
    {selection&&<>
      <ReadState {...result}/>
      <p><strong>{comparison}</strong> · {t(directionLabels[selection.direction])} · {t(bulkQColumns[selection.q_column])} ({selection.q_column}) · q ≤ {selection.q_threshold} · |log2FC| ≥ {selection.minimum_absolute_effect}</p>
    </>}
    {figureType?<><p>{t(isBulkProcessedFigure(figureType)
      ?'直接使用 B03 已保存的图数据或 PCA 得分与方差。'
      :figureNotes[figureType as keyof typeof figureNotes])}</p>
      {figureType==='bulk_expression'&&<p>{t('稳定特征 ID')} <code>{strings(config.feature_ids)[0]}</code></p>}
      {heatmap&&<Toggle label="行 z-score（仅图上展示）" value={config.z_score===true} onChange={value=>onChange({...config,z_score:value})}/>}
      {topLabel&&<p className="muted">{t(heatmap
        ?'可用基因不足 N 时展示实际数量。行 z-score 只改变图上展示，固定表达层可追溯。'
        :'Top N 只控制 DEG 标签，全部可绘制点保留。可标注基因不足 N 时展示实际数量。')}</p>}
      <FigurePresentation {...{config,onChange,topLabel}} topMax={heatmap?100:500}/>
    </>:<>
      <ConfigField {...{config,onChange}} name="bulk_top_n" label="候选展示 Top N" type="number" min={1} max={500}/>
      <p>{t('固定范围内的全部 DEG 都会保存。候选按所选 q 升序、绝对效应降序、稳定 ID 排序。Top N 只影响展示，不足 N 时显示实际数量。')}</p>
    </>}
  </section>
}
