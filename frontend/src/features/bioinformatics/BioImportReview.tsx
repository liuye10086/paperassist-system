import BioRepresentation from './BioRepresentation'
import BioDesignLinks from './BioDesignLinks'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {projectBase} from './api'
import type {BioImport} from './contracts'
import {canConfirmCandidate} from './contracts'
import {BioChecks,BioCounts,BioMembers} from './BioDetails'
import {BioWriteStatus} from './BioSpatialShared'
import {useBioRead} from './spatialHooks'
import useBioWrite from './useBioWrite'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import type {AnalysisNavigation} from '../projects/analysisViews'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import './bioLayout.css'

function importProgress(task:BioImport['task']) {
 switch(task.status){
  case 'succeeded':return {tone:'success',label:'数据集版本已发布'}
  case 'failed':return {tone:'error',label:'导入失败；原件和已有数据集保留。'}
  case 'waiting_confirmation':return {tone:'warning',label:'候选已生成，待明确确认'}
  case 'queued':return {tone:'info',label:task.phase==='verify'?'已确认，等待发布数据集版本。':'排队中，轮到此任务后核对矩阵。'}
  case 'running':return {tone:'info',label:task.phase==='verify'?'正在发布数据集版本。':'正在核对矩阵与样本信息。'}
  case 'cancelled':return {tone:'neutral',label:'导入已取消，上传文件保留。'}
  default:return {tone:'neutral',label:'正在核对任务状态，请稍后重新读取。'}
 }
}

export default function BioImportReview({projectId,importId,onNavigate,registerLeaveGuard}:{projectId:string;importId:string;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n(),read=useBioRead<BioImport>(`${projectBase(projectId)}/bio-imports/${encodeURIComponent(importId)}`,v=>['queued','running'].includes(v.task.status)),data=read.value
 const signature=data?.candidate?JSON.stringify([data.candidate.sha256,data.checkpoint_id,data.wait_id,data.task.revision,data.expected_dataset_revision]):null
 const [accepted,setAccepted]=useState<string|null>(null),accept=!!signature&&accepted===signature
 const writer=useBioWrite<unknown>(projectId,'import_confirmation',()=>{setAccepted(null);read.reload()},()=>{setAccepted(null);read.reload()})
 const progress=data&&importProgress(data.task)
 useDraftLeaveGuard(registerLeaveGuard,false,writer.busy||writer.unknown)
 function confirm(){if(!data||!accept||!canConfirmCandidate(data))return;void writer.submit(`${projectBase(projectId)}/bio-imports/${encodeURIComponent(importId)}/confirm`,{task_revision:data.task.revision,checkpoint_id:data.checkpoint_id,wait_id:data.wait_id,candidate_sha256:data.candidate!.sha256,expected_dataset_revision:data.expected_dataset_revision??0})}
 return <section className="bio-workspace bio-module-workspace bio-import-review">
  <header className="bio-workspace-header">
   <div className="bio-import-review-heading"><h2>{t('生信导入核对')}</h2>
    {progress&&<p role="status" className="status-badge" data-tone={progress.tone}>{t(progress.label)}</p>}
   </div>
   <div className="bio-import-review-actions">
    {data&&<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(data.task.id)}`}>{t('查看项目任务')}</a>}
    <button type="button" disabled={writer.busy||!read.valid} onClick={read.reload}>{t('重新读取导入')}</button>
   </div>
  </header>
  {read.error&&<p role="alert" className="error-panel">{t(read.error)}</p>}
  {data&&<>
   {data.candidate?<>
    <ModuleViews label={t('导入核对模块')}>
     <ModuleView id="structure" title={t('文件结构')}><BioCounts summary={data.candidate.summary}/><BioChecks layout="table" checks={data.candidate.checks}/><BioRepresentation summary={data.candidate.summary} checks={data.candidate.checks}/></ModuleView>
     <ModuleView id="members" title={t('文件成员')}><BioMembers members={data.candidate.members} projectId={projectId}/></ModuleView>
     <ModuleView id="design" title={t('研究设计')}><p>{t('结构核对不自动确认生物独立性；请结合冻结样本表与实验设计核对供体和重复关系。')}</p><BioDesignLinks projectId={projectId}/></ModuleView>
    </ModuleViews>
    {canConfirmCandidate(data)&&<div className="bio-confirmation-actions"><label className="intake-check"><input type="checkbox" checked={accept} onChange={e=>setAccepted(e.target.checked?signature:null)} disabled={writer.busy||writer.unknown}/>{t('接受此数据集及结构核对结果；后续设计、质控和方法须另行确认。')}</label><button type="button" className="button-primary" disabled={writer.busy||writer.unknown||!writer.valid||!accept} onClick={confirm}>{t('确认并发布数据集版本')}</button></div>}
   </>:<p className="bio-import-review-empty">{t('候选尚未就绪，请查看任务状态。')}</p>}
   {data.result_source&&data.task.status==='succeeded'&&<div className="bio-import-review-next"><button type="button" className="button-primary" onClick={()=>onNavigate({view:'bio-dataset',fileId:'',datasetId:data.result_source!.dataset_id,versionId:data.result_source!.dataset_version_id})}>{t('下一步：查看矩阵并配置分析')}</button></div>}
  </>}<BioWriteStatus writer={writer}/>
 </section>
}
