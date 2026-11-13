import {isTabularRaw} from './tabularContracts'
import type {BioConfirmationRequest} from './spatialContracts'
import BioQcSummary from './BioQcSummary'
import {useBioRead} from './spatialHooks'
import {useState} from 'react'
import {apiError,useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import {BioChecks} from './BioDetails'
import {BioJson,BioMemberImage,BioSource,BioSpatialMembers,BioWriteStatus} from './BioSpatialShared'
import {hasCandidateConfirmation} from './contracts'
import type {BioRun} from './spatialContracts'
import {isRawBioSource} from './spatialContracts'
import useBioWrite from './useBioWrite'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import './bioLayout.css'
const qcCheckLabels:Record<string,string>={raw_hashes:'原始数据一致性',h5ad_roundtrip:'H5AD 读写核对'}
export default function BioAnalysisReview({projectId,runId,onNavigate,registerLeaveGuard}:{projectId:string;runId:string;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n(),base=projectBase(projectId),read=useBioRead<BioRun>(`${base}/bio-analysis-runs/${encodeURIComponent(runId)}`,v=>['queued','running'].includes(v.task.status)),data=read.value
 const tabular=!!data&&isTabularRaw(data.raw_source),singleCell=data?.raw_source.parser_version==='single_cell_import_v1'
 const signature=data?.candidate?JSON.stringify([data.candidate.sha256,data.checkpoint_id,data.wait_id,data.task.revision]):null
 const [acceptedDigest,setAcceptedDigest]=useState<string|null>(null),accept=!!signature&&acceptedDigest===signature,writer=useBioWrite<unknown>(projectId,'confirmation',()=>{setAcceptedDigest(null);read.reload()},()=>{setAcceptedDigest(null);read.reload()})
 useDraftLeaveGuard(registerLeaveGuard,false,writer.busy||writer.unknown)
 return <section className="bio-workspace bio-module-workspace">
  <header className="bio-workspace-header"><h2>{t(tabular?'定量分析运行与 QC 确认':singleCell?'单细胞分析运行':'空间分析运行与 QC 确认')}</h2><button type="button" disabled={writer.busy} onClick={read.reload}>{t('重新读取')}</button></header>
  {read.error&&<p role="alert">{t(read.error)}</p>}{!data&&!read.error&&<p role="status">{t('正在读取固定版本……')}</p>}
  {data&&(data.id!==runId||!isRawBioSource(data.raw_source,projectId))&&<p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>}
  {data&&data.id===runId&&isRawBioSource(data.raw_source,projectId)&&<>
   <div className="bio-workspace-status"><p role="status">{t(data.task.status==='waiting_confirmation'?'QC 候选待确认':data.task.status==='succeeded'&&data.result_source?'处理版本已发布':data.task.status==='failed'?'运行失败；原件和历史版本保留。':data.task.status==='queued'?'排队中，轮到此任务后开始分析。':data.task.status==='cancelled'?'分析已取消，原件和已有结果保留。':data.task.status==='running'?'正在分析，完成后可继续查看结果。':'正在核对任务状态，请稍后重新读取。')}</p><a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(data.task.id)}`}>{t('查看项目任务')}</a></div>
   {data.task.reason_code&&<p className="muted">{t('任务正在核对处理条件，请稍后刷新。')}</p>}{data.task.error_code&&<p role="alert">{t(apiError({code:data.task.error_code},'任务暂未完成，请查看处理说明。'))}</p>}
   {data.candidate&&<>
    <ModuleViews label={t('QC 核对模块')}>
     <ModuleView id="overview" title={t('QC 概况')}><BioQcSummary summary={data.candidate.summary} observationLabel={tabular?'样本':singleCell?'细胞':'空间位点'} featureLabel={tabular?'特征':'基因'}/><BioChecks layout="table" checks={Object.entries(data.candidate.checks).map(([code,state])=>({name:qcCheckLabels[code]??'质量核对',status:state==='verified'?'passed':state}))}/></ModuleView>
     <ModuleView id="parameters" title={t('有效参数')}><p>{t('参数已用于本次 QC 候选，完整记录可在高级详情中展开。')}</p><section className="customer-advanced-details"><h4>{t('查看完整参数与 QC 记录')}</h4><BioJson value={data.candidate.effective_params}/><h3>{t('固定来源')}</h3><BioSource source={data.raw_source}/><h3>{t('完整 QC 记录')}</h3><BioJson value={data.candidate.summary}/></section></ModuleView>
     <ModuleView id="images" title={t('QC 图像')}>{data.candidate.members.filter(m=>m.format==='png').map(m=><BioMemberImage key={m.id} projectId={projectId} member={m}/>)}</ModuleView>
     <ModuleView id="files" title={t('结果文件')}><BioSpatialMembers projectId={projectId} members={data.candidate.members}/></ModuleView>
    </ModuleViews>
    {hasCandidateConfirmation(data)&&<div className="bio-confirmation-actions"><label className="intake-check"><input type="checkbox" checked={accept} disabled={writer.busy||writer.unknown} onChange={e=>setAcceptedDigest(e.target.checked?signature:null)}/>{t('已核对过滤、未知设计与有效参数，接受此固定候选。')}</label><button type="button" className="button-primary" disabled={!accept||writer.busy||writer.unknown||!writer.valid} onClick={()=>void writer.submit(`${base}/bio-analysis-runs/${encodeURIComponent(runId)}/confirm`,{task_revision:data.task.revision!,checkpoint_id:data.checkpoint_id!,wait_id:data.wait_id!,candidate_sha256:data.candidate!.sha256,expected_setup_revision:data.expected_setup_revision} satisfies BioConfirmationRequest)}>{t('确认此 QC 候选并继续计算')}</button></div>}
   </>}
   {data.result_source&&data.task.status==='succeeded'&&<button type="button" className="button-primary" onClick={()=>onNavigate({view:'bio-result',fileId:'',processedId:data.result_source!.processed_dataset_version_id,tab:'qc'})}>{t(singleCell?'下一步：查看结果与 Word':'下一步：查看分析结果')}</button>}
  </>}<BioWriteStatus writer={writer}/>
 </section>
}
