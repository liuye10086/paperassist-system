import SingleCellRobustness,{type RepeatContext} from './SingleCellRobustness'
import SingleCellDirectStart from './SingleCellDirectStart'
import SingleCellAnnotationWorkspace from './SingleCellAnnotationWorkspace'
import SingleCellIntegrationResult from './SingleCellIntegrationResult'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import NativeDeliveryArtifact,{type NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import TabularAnalysisResult from './TabularAnalysisResult'
import type {TabularProcessed} from './tabularContracts'
import BioQcSummary from './BioQcSummary'
import SingleCellQcResult from './SingleCellQcResult'
import BioMatrixPreview from './BioMatrixPreview'
import {useBioRead} from './spatialHooks'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {bioResultTabs,type AnalysisEntryContext,type AnalysisNavigation,type BioResultTab} from '../projects/analysisViews'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import {BioJson,BioSource} from './BioSpatialShared'
import {isProcessedBioSource,type BioProcessed} from './spatialContracts'
import BioResultTable from './BioResultTable'
import BioSpatialResult from './BioSpatialResult'
import {BioFigureComposer} from './BioFigureDetail'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import {BioResultDownloads,BioResultFigures,BioResultSteps} from './BioResultPanels'
import {isTechnicalResultFile,resultTableLabels} from './bioPresentation'
import './bioResults.css'

const labels={qc:'QC 与过滤',embedding:'PCA / UMAP',clusters:'聚类',markers:'探索性 marker',spatial:'空间与人工注释',methods:'方法与复现'}
const resultKeys={
 qc:/qc|filter|observation|mapping|library_|single_cell_tool|decontx/,
 embedding:/pca|umap|embedding|hvg|integration_/,
 clusters:/cluster|cell_label|cell_sample|pseudobulk/,
 markers:/marker|feature/,
}
export default function BioAnalysisResult({projectId,processedId,tab,onNavigate,registerLeaveGuard,qualityMode=false,allowNewAnalysis=true,deliveryTarget,entry}:{projectId:string;processedId:string;entry?:AnalysisEntryContext;deliveryTarget?:NativeDeliveryTarget;tab:BioResultTab;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard;qualityMode?:boolean;allowNewAnalysis?:boolean}){
 const {t}=useI18n(),read=useBioRead<BioProcessed|TabularProcessed>(`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(processedId)}`),data=read.value
 const [repeat,setRepeat]=useState<RepeatContext|null>(null)
 if(!data)return <section className="bio-workspace"><h2>{t('生信分析处理结果')}</h2><p role={read.error?'alert':'status'}>{t(read.error||'正在读取固定版本……')}</p><button onClick={read.reload}>{t('重新读取')}</button></section>
 if(data.id===processedId&&data.source.schema_version===2)return <TabularAnalysisResult qualityMode={qualityMode} projectId={projectId} result={data as TabularProcessed} tab={tab} onNavigate={onNavigate}/>
 if(data.id!==processedId||!isProcessedBioSource(data.source,projectId)||data.source.processed_dataset_version_id!==processedId)return <p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>
 const singleCell=data.manifest.assay==='single_cell'
 const result=data as BioProcessed
 const summary=data.manifest.summary&&typeof data.manifest.summary==='object'?data.manifest.summary as Record<string,unknown>:{}
 return <section className="bio-workspace bio-fixed-result">
  <header className="bio-fixed-result-heading">
   <div><h2>{t(singleCell?'单细胞分析处理结果':'空间分析处理结果')}</h2>
    <p>{t('基于已导入的研究资料')}</p>
   </div>
   {singleCell&&<div className="bio-result-toolbar" aria-label={t('分析结果与 Word')}>
    <ProjectDownloadLink href={`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(processedId)}/report.docx`} filename={t('单细胞分析报告')+'.docx'}>{t('下载 Word 分析报告')}</ProjectDownloadLink>
    <NativeDeliveryArtifact {...{projectId,deliveryTarget}} source={{kind:'single_cell_word',version_id:processedId}} name={t('单细胞分析报告')+'.docx'}/>
   </div>}
  </header>
  {!allowNewAnalysis&&<p role="status">{t('新分析条件尚未就绪；已有结果仍可查看下载，请先核对材料并保存需求。')}</p>}
  <p className="bio-result-scope">{t(singleCell?'cell 不代表独立 donor；marker 和人工标签是探索性结果，技术重复不会增加 n。':'spot 或组织片段不代表独立供体；marker 仅为探索性区域或 cluster 关联。')}</p>
  {!qualityMode&&singleCell&&entry?.scopeItemId==='customer.analysis.single_cell.pseudotime'&&
   <RequestedTrajectory {...{projectId,allowNewAnalysis,onNavigate}} result={result}/>}
  <nav className="bio-fixed-result-nav" aria-label={t('生信结果标签页')}>
   {bioResultTabs.map(v=><button type="button" key={v} aria-current={v===tab?'page':undefined}
    onClick={()=>{if(v!==tab)onNavigate({view:'bio-result',fileId:'',processedId,tab:v})}}>{t(singleCell&&v==='spatial'?'细胞注释与亚群':labels[v])}</button>)}
  </nav>
  {tab==='methods'?<ModuleViews lazy key={tab} label={t('方法与复现')}>
   <ModuleView id="steps" title={t('处理步骤')}><BioResultSteps steps={result.steps}/></ModuleView>
   <ModuleView id="advanced" title={t('高级数据')}>
    <section className="bio-result-block bio-result-records">
     <h3>{t('查看高级数据结构')}</h3><BioJson value={result.shape}/>
     <h3>{t('方法记录')}</h3><BioSource source={result.source.raw_source}/>
     {Boolean(result.manifest.methods)&&<BioJson value={result.manifest.methods}/>}
     {Boolean(result.manifest.resources)&&<><h3>{t('实际资源记录')}</h3><BioJson value={result.manifest.resources}/></>}
    </section>
   </ModuleView>
   <ModuleView id="files" title={t('结果文件')}><BioResultDownloads {...{projectId,singleCell,processedId,deliveryTarget}} members={result.members}/></ModuleView>
   {singleCell&&<ModuleView id="robustness" title={t('稳健性与重复计算')}>
    <SingleCellRobustness key={data.id} projectId={projectId} result={result} onRepeat={repeat?undefined:setRepeat} allowNewAnalysis={allowNewAnalysis}/>
    {repeat&&<SingleCellDirectStart allowNewAnalysis={allowNewAnalysis} key={data.id+':'+repeat.params.seed} projectId={projectId} source={data.source.raw_source}
     initialParams={repeat.params} observationMapVersionId={repeat.observation_map_version_id} designVersionId={repeat.design_version_id} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/>}
   </ModuleView>}
   {!qualityMode&&<ModuleView id="next" title={t('继续分析')}>
    <section className="bio-result-block"><h3>{t('继续深入分析（可选）')}</h3><div className="bio-result-toolbar">
     <button type="button" onClick={()=>onNavigate({view:'research-findings',fileId:'',processedId:data.id})}>{t('整理研究发现与报告')}</button>
     <button type="button" onClick={()=>onNavigate({view:'bio-insights',fileId:'',processedId:data.id})}>{t('差异与功能分析')}</button>
     {singleCell&&<>
      <button type="button" onClick={()=>onNavigate({view:'bio-insights',fileId:'',processedId:data.id,intent:'single_cell_topic'})}>{t('轨迹／调控／通讯专题')}</button>
      <button type="button" onClick={()=>onNavigate({view:'bio-candidates',fileId:'',processedId:data.id,intent:'evidence'})}>{t('关联本地证据与实验材料')}</button>
     </>}
    </div></section>
   </ModuleView>}
  </ModuleViews>:tab==='spatial'&&singleCell?<SingleCellAnnotationWorkspace allowNewAnalysis={allowNewAnalysis} deliveryTarget={deliveryTarget} key={data.id} projectId={projectId} result={result} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/>
   :tab==='spatial'?<BioSpatialResult allowNewAnalysis={allowNewAnalysis} projectId={projectId} result={result} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/>
   :<ModuleViews lazy key={tab} label={t(labels[tab])}>
    {tab==='qc'&&<ModuleView id="summary" title={t('QC 概况')}>
     <div className="bio-result-block"><BioQcSummary observationLabel={singleCell?'cell':'spot'} summary={summary}/></div>
    </ModuleView>}
    <ModuleView id="figures" title={t('图表预览')}>
     {singleCell&&tab==='embedding'&&<SingleCellIntegrationResult summary={summary}/>}
     <BioResultFigures projectId={projectId} figures={result.figures.filter(f=>resultKeys[tab].test(f.config.kind))} onNavigate={onNavigate}/>
    </ModuleView>
    <ModuleView id="tables" title={t('结果表')}><BioResultTables projectId={projectId} processedId={processedId}
     tables={result.tables.filter(table=>resultKeys[tab].test(table.key)&&!isTechnicalResultFile(table.key))}/></ModuleView>
    {tab==='qc'&&<ModuleView id="matrix" title={t('矩阵预览')}>
     <BioMatrixPreview projectId={projectId} processedId={processedId}
      layers={data.manifest.layers&&typeof data.manifest.layers==='object'&&'decontx_counts' in data.manifest.layers?['counts','normalized','log1p','decontx_counts']:undefined}/>
    </ModuleView>}
    {tab==='qc'&&singleCell&&Boolean(summary.single_cell_algorithms)&&<ModuleView id="quality-models" title={t('质控模型')}>
     <SingleCellQcResult summary={summary}/>
    </ModuleView>}
    <ModuleView id="files" title={t('结果文件')}><BioResultDownloads {...{projectId,singleCell,processedId,deliveryTarget}}
     members={result.members.filter(member=>resultKeys[tab].test(member.key))}/></ModuleView>
    {allowNewAnalysis&&<ModuleView id="figure-config" title={t('绘图设置')}><BioFigureComposer
     projectId={projectId} result={result} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/></ModuleView>}
   </ModuleViews>}
 </section>
}

function BioResultTables({projectId,processedId,tables}:{projectId:string;processedId:string;tables:BioProcessed['tables']}){
 const {t}=useI18n(),[tableKey,setTableKey]=useState('')
 const table=tables.find(value=>value.key===tableKey)??tables[0]
 if(!table)return <p className="bio-result-note">{t('此标签页无可用结果表，请查看步骤状态和下载清单。')}</p>
 const title=(value:typeof table)=>t(resultTableLabels[value.key]??value.label)
 return <section className="bio-result-block">
  <div className="bio-result-toolbar"><label>{t('结果表')}<select value={table.key} onChange={e=>setTableKey(e.target.value)}>
   {tables.map(value=><option key={value.key} value={value.key}>{title(value)}</option>)}
  </select></label></div>
  {table.status==='not_computable'?<p>{t('条件不足，未计算此结果表。')}</p>
   :<BioResultTable key={table.key} {...{projectId,processedId}} tableKey={table.key} title={title(table)}/>}
 </section>
}

function RequestedTrajectory({projectId,allowNewAnalysis,onNavigate,result}:{
 projectId:string;allowNewAnalysis:boolean;onNavigate:(n:AnalysisNavigation)=>void;result:BioProcessed
}){
 const {t}=useI18n()
 const summary=result.manifest.summary as {clusters?:number;retained_observations?:number}|undefined
 const compatible=(summary?.clusters??0)>=2&&(summary?.retained_observations??0)>=4&&result.members.some(member=>member.key==='pca')
 const capability=useBioRead<{single_cell_topic_runtimes?:{slingshot?:{available:boolean}}}>(
  compatible&&allowNewAnalysis?`${projectBase(projectId)}/bio-insights/capabilities`:'')
 if(!compatible)return <p>{t('拟时分析需要至少两个固定聚类和可用的 PCA。')}</p>
 if(!allowNewAnalysis)return null
 if(capability.error)return <p role="alert">{t('拟时分析能力读取失败。')} <button type="button" onClick={capability.reload}>{t('重新读取')}</button></p>
 if(!capability.value)return <p role="status">{t('正在核对 Slingshot 运行环境……')}</p>
 if(!capability.value.single_cell_topic_runtimes?.slingshot?.available)return <p>{t('当前环境未验证 Slingshot，可继续查看已有结果。')}</p>
 return <button type="button" onClick={()=>onNavigate({view:'bio-insights',fileId:'',processedId:result.id,intent:'single_cell_topic'})}>{t('配置 Slingshot 拟时分析')}</button>
}
