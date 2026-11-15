import {useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import type {NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import BioReaderReport from '../bio-reader-reports/BioReaderReport'
import type {ReportLocation} from '../bio-reader-reports/navigation'
import {isBulkReportEnrichmentSource} from '../bio-reader-reports/contracts'
import {useBioReportContext} from '../bio-reader-reports/useBioReportContext'
import {projectBase} from './api'
import {useInsightRead} from './hooks'
import {isBulkEnrichmentResult,isReviewedBulkComparison} from './bulk'
import {ReadState} from './InsightShared'
import type {Result} from './contracts'
import {figureName} from '../bioinformatics/bioPresentation'

type FigureChoice={id:string;title:string;figure_type:string;manifest_sha256:string;source_id:string;source_sha256:string}
export default function InsightDelivery({projectId,result,active=true,location,deliveryTarget,reportContextId}:{
 projectId:string;result:Result;active?:boolean;location?:ReportLocation;deliveryTarget?:NativeDeliveryTarget;reportContextId?:string
}){
 const {t}=useI18n(),base=`${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(result.id)}`
 const topic=!!result.summary.topic_method,comparison=isReviewedBulkComparison(result),enrichment=isBulkEnrichmentResult(result)
 const external=result.kind==='result_import'&&result.provenance==='external_result'&&result.inference_scope==='external_result'
 const report=active&&result.task.status==='succeeded'&&(['comparison','ora','gsea_prerank'].includes(result.kind)||topic||external)
 const figures=useInsightRead<{items:FigureChoice[]}>(report?`${base}/figures`:'',report,true)
 const fixed=useBioReportContext(projectId,reportContextId,active,context=>{
  const value=context.selection
  if(value.kind==='insight')return value.result_version_id===result.id
  return value.kind==='bulk'&&(comparison?value.delivery.comparison_version_id===result.id:
   enrichment&&isBulkReportEnrichmentSource(context,result.id))
 })
 const available=figures.data?.items?.filter(figure=>figure.source_id===result.id&&figure.source_sha256===result.manifest_sha256)??[]
 const displayFigure=(figure:FigureChoice)=>figure.title&&figure.title!==figure.figure_type?figure.title:figureName(figure.figure_type,t)
 const title=comparison||enrichment?'Bulk RNA-seq 分析报告'
  :topic?({slingshot:'单细胞轨迹分析报告',genie3:'基因调控网络分析报告',cellchat:'细胞通讯分析报告'}[String(result.summary.topic_method)]??'单细胞专题报告')
  :external?'外部差异结果报告':result.kind==='comparison'?'差异表达分析报告':'功能富集分析报告'
 const restored=fixed.data??undefined
 return <section className="analysis-detail"><h3>{t('成果下载与复现')}</h3>
  {report&&<ReadState {...figures}/>}
  {fixed.error&&<p role="alert">{t(fixed.error)} <button type="button" onClick={fixed.refresh}>{t('重新读取')}</button></p>}
  {fixed.loading&&<p role="status">{t(fixed.loadingMessage)}</p>}
  {report&&(!reportContextId||restored)&&<BioReaderReport {...{projectId,active,title,location,deliveryTarget,restored}}
   figureLimit={enrichment?19:comparison?20:50}
   figures={available.map(figure=>({id:figure.id,title:displayFigure(figure)}))}
   selection={{kind:'insight',result_version_id:result.id}} renderSelection={ids=>!!ids.length&&<ul>{ids.map(id=>{
    const figure=available.find(value=>value.id===id)!
    return <li key={id}><ProjectDownloadLink href={`${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(id)}/reproducibility-package`}
     filename={figureName(figure.figure_type,t)+' - '+t('复现资料')+'.zip'} timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}>
     {t('{title}：下载重绘复现包',{title:displayFigure(figure)})}
    </ProjectDownloadLink></li>
   })}</ul>}/>}
  <div className="intake-actions"><ProjectDownloadLink href={`${base}/reproducibility-package`} filename={t('分析复现资料')+'.zip'}
   timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}>{t('下载原分析复现包')}</ProjectDownloadLink></div>
  {topic&&<p>{t('原计算复现包需要匹配原运行环境；若环境已变化，可下载保存的表、参数和日志。重绘复现包只重现所选图表，不重新计算专题。')}</p>}
  <p>{t('完整表、对象、参数和日志见下方文件；复现包需要匹配的计算环境，工程复现不等于独立队列或实验验证。')}</p>
 </section>
}
