import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'

type QcMetric = Record<string, number>
type BulkQcSummary = Record<string, unknown> & {
  qc_metrics?: {
    total_counts?: QcMetric
    detected_features?: QcMetric
    zero_fraction?: QcMetric
    expression_distribution?: Record<string, unknown>
  }
  outlier_advisories?: {sample_id: string; reasons?: string[]; advisory?: string; basis?: string}[]
  layers?: Record<string, string>
  analysis_object?: {format?: string; round_trip?: string}
}

function numericEntries(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>).filter(([, item]) => typeof item === 'number') as [string, number][]
}

export default function BulkQcDetails({summary, setupId, onNavigate, layers:manifestLayers, analysisObject:manifestObject, isBulk=false}:{summary: Record<string, unknown>;setupId?: string;onNavigate:(navigation: AnalysisNavigation)=>void;layers?:Record<string, unknown>;analysisObject?:unknown;isBulk?:boolean}) {
  const {t}=useI18n(), data=summary as BulkQcSummary, metrics=data.qc_metrics, advisories=data.outlier_advisories??[], layers=data.layers??Object.fromEntries(Object.entries(manifestLayers??{}).map(([key,value])=>[key,typeof value==='string'?value:key])), object=(data.analysis_object??manifestObject) as BulkQcSummary['analysis_object']
  const metricRows=[
    ['总计数',metrics?.total_counts],
    ['检测特征数',metrics?.detected_features],
    ['零比例',metrics?.zero_fraction],
  ] as const
  const hasMetrics=metricRows.some(([,value])=>numericEntries(value).length>0)
  return <>
    {hasMetrics&&<section className="analysis-detail" aria-label={t('Bulk 样本 QC 指标')}>
      <h3>{t('Bulk 样本 QC 指标')}</h3>
      <div className="bio-table-scroll"><table><caption>{t('样本 QC 指标')}</caption><thead><tr><th>{t('指标')}</th><th>{t('样本')}</th><th>{t('数值')}</th></tr></thead><tbody>{metricRows.flatMap(([label,value])=>numericEntries(value).map(([sample,number])=><tr key={label+sample}><th>{t(label)}</th><td>{sample}</td><td>{number.toLocaleString()}</td></tr>))}</tbody></table></div>
      {metrics?.expression_distribution&&<p role="status"><strong>{t('表达分布')}</strong>：<code>{JSON.stringify(metrics.expression_distribution)}</code></p>}
    </section>}
    {Object.keys(layers).length>0&&<section className="analysis-detail" aria-label={t('矩阵层语义')}><h3>{t('矩阵层语义')}</h3><ul>{Object.entries(layers).map(([key,label])=><li key={key}><strong>{key==='vst'?'VST':key}</strong> · {String(label)}</li>)}</ul><p>{isBulk?t('原始 counts、过滤后 counts、normalized counts 与 VST 保持不同层语义；展示变换不覆盖原始层。'):t('各处理层保持输入尺度和处理语义；展示变换不覆盖原始层。')}</p></section>}
    {object&&<section className="analysis-detail" aria-label={t('分析对象')}><h3>{t('分析对象')}</h3><p>{t('对象格式')}：{object.format??'NA'} · {t('往返状态')}：{object.round_trip??'NA'}</p><p>{t('对象轴、参数和来源版本已写入固定结果清单。')}</p></section>}
    {advisories.length>0&&<section className="warning-panel" aria-label={t('疑似异常样本')}><h3>{t('疑似异常样本')}</h3><p>{t('以下仅为检查提示，不会自动排除样本。')}</p><ul>{advisories.map(item=>{const reasons=item.reasons?.length?item.reasons:[item.advisory??item.basis??'review_required'];return <li key={item.sample_id}><strong>{item.sample_id}</strong>：{reasons.join('、')}</li>})}</ul><button type="button" disabled={!setupId} onClick={()=>setupId&&onNavigate({view:'bio-analysis-setup',fileId:'',setupId})}>{t('进入人工排除')}</button><p>{t('请在分析配置页勾选或填写样本后保存新配方；原始结果和原始 counts 不会被修改。')}</p>{!setupId&&<p>{t('当前结果没有可回到的分析配置，请在分析配置页手动建立排除样本的新配方。')}</p>}</section>}
  </>
}
