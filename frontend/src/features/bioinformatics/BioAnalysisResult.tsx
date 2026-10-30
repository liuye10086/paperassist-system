import BioQcSummary from './BioQcSummary'
import BioMatrixPreview from './BioMatrixPreview'
import {useBioRead} from './spatialHooks'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {bioResultTabs,type AnalysisNavigation,type BioResultTab} from '../projects/analysisViews'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import {BioJson,BioMemberImage,BioSource,BioSpatialMembers} from './BioSpatialShared'
import {isProcessedBioSource,type BioProcessed} from './spatialContracts'
import BioResultTable from './BioResultTable'
import BioReproducibility from './BioReproducibility'
import BioSpatialResult from './BioSpatialResult'
import {BioFigureComposer} from './BioFigureDetail'
const labels={qc:'QC 与过滤',embedding:'PCA / UMAP',clusters:'聚类',markers:'探索性 marker',spatial:'空间与人工注释',methods:'方法与复现'}
export default function BioAnalysisResult({projectId,processedId,tab,onNavigate,registerLeaveGuard}:{projectId:string;processedId:string;tab:BioResultTab;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n(),read=useBioRead<BioProcessed>(`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(processedId)}`),data=read.value,[tableKey,setTableKey]=useState('')
 if(!data)return <section className="bio-workspace"><h2>{t('空间分析处理结果')}</h2><p role={read.error?'alert':'status'}>{t(read.error||'正在读取固定版本……')}</p><button onClick={read.reload}>{t('重新读取')}</button></section>
 if(data.id!==processedId||!isProcessedBioSource(data.source,projectId)||data.source.processed_dataset_version_id!==processedId)return <p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>
 const relevant=(key:string)=>tab==='qc'?/qc|filter|observation|mapping/.test(key):tab==='embedding'?/pca|umap|embedding|hvg/.test(key):tab==='clusters'?/cluster/.test(key):tab==='markers'?/marker|feature/.test(key):false
 const tables=data.tables?.filter(v=>relevant(v.key))??[],selected=tables.find(v=>v.key===tableKey)??tables[0]
 return <section className="bio-workspace"><h2>{t('空间分析处理结果')}</h2><BioSource source={data.source.raw_source}/><dl className="bio-source"><dt>{t('正式处理版本')}</dt><dd>{data.id}</dd><dt>{t('计算引擎')}</dt><dd>{data.source.engine_version}</dd></dl><p className="warning-panel">{t('spot 或组织片段不代表独立供体；marker 仅为探索性区域或 cluster 关联。')}</p><nav className="intake-actions" aria-label={t('生信结果标签页')}>{bioResultTabs.map(v=><button type="button" key={v} aria-current={v===tab?'page':undefined} onClick={()=>onNavigate({view:'bio-result',fileId:'',processedId,tab:v})}>{t(labels[v])}</button>)}</nav><details><summary>{t('实际步骤状态和缺口')}</summary><ul>{data.steps.map(step=><li key={step.key}>{step.key}: {t(step.status==='completed'?'已完成':step.status==='not_computable'?'不可计算':'未请求')}{step.reason&&<> · <span>{step.reason}</span></>}</li>)}</ul></details>
 {tab==='methods'?<BioReproducibility projectId={projectId} result={data}/>:tab==='spatial'?<BioSpatialResult projectId={projectId} result={data} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/>:<><BioJson value={data.shape}/>{tab==='qc'&&<><BioQcSummary summary={data.manifest.summary&&typeof data.manifest.summary==='object'?data.manifest.summary as Record<string,unknown>:{}}/><BioMatrixPreview projectId={projectId} processedId={processedId}/></>}{data.figures.filter(f=>relevant(f.config.kind)).map(f=><section key={f.id}><h3>{f.config.title||f.config.kind}</h3>{f.members.filter(m=>m.format==='png').map(m=><BioMemberImage key={m.id} projectId={projectId} member={m}/>)}<button type="button" onClick={()=>onNavigate({view:'bio-figure',fileId:'',figureId:f.id})}>{t('打开固定单图版本')}</button></section>)}{tables.length?<><label>{t('结果表')}<select value={selected?.key??''} onChange={e=>setTableKey(e.target.value)}>{tables.map(v=><option key={v.key} value={v.key}>{v.label}</option>)}</select></label>{selected?.status==='not_computable'?<p>{t('不可计算')} · {selected.reason}</p>:selected&&<BioResultTable key={selected.key} projectId={projectId} processedId={processedId} tableKey={selected.key}/>}</>:<p>{t('此标签页无可用结果表，请查看步骤状态和下载清单。')}</p>}<BioSpatialMembers projectId={projectId} members={data.members.filter(m=>relevant(m.key))}/><BioFigureComposer projectId={projectId} result={data} onNavigate={onNavigate} registerLeaveGuard={registerLeaveGuard}/></>}
 </section>
}
