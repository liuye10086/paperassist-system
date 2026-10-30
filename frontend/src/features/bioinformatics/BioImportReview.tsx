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
export default function BioImportReview({projectId,importId,onNavigate,registerLeaveGuard}:{projectId:string;importId:string;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n(),read=useBioRead<BioImport>(`${projectBase(projectId)}/bio-imports/${encodeURIComponent(importId)}`,v=>['queued','running'].includes(v.task.status)),data=read.value
 const signature=data?.candidate?JSON.stringify([data.candidate.sha256,data.checkpoint_id,data.wait_id,data.task.revision,data.expected_dataset_revision]):null
 const [accepted,setAccepted]=useState<string|null>(null),accept=!!signature&&accepted===signature
 const writer=useBioWrite<unknown>(projectId,'import_confirmation',()=>{setAccepted(null);read.reload()},()=>{setAccepted(null);read.reload()})
 useDraftLeaveGuard(registerLeaveGuard,false,writer.busy||writer.unknown)
 function confirm(){if(!data||!accept||!canConfirmCandidate(data))return;void writer.submit(`${projectBase(projectId)}/bio-imports/${encodeURIComponent(importId)}/confirm`,{task_revision:data.task.revision,checkpoint_id:data.checkpoint_id,wait_id:data.wait_id,candidate_sha256:data.candidate!.sha256,expected_dataset_revision:data.expected_dataset_revision??0})}
 return <section className="bio-workspace"><h2>{t('生信导入核对')}</h2>{read.error&&<p role="alert" className="error-panel">{t(read.error)}</p>}<button type="button" disabled={writer.busy||!read.valid} onClick={read.reload}>{t('重新读取导入')}</button>{data&&<><p>{t(data.task.status==='succeeded'?'数据集版本已发布':data.task.status==='failed'?'导入失败；原件和已有数据集保留。':data.task.status==='waiting_confirmation'?'候选已生成，待明确确认':'任务已提交，正在处理。')}</p><a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(data.task.id)}`}>{t('查看项目任务')}</a>{data.candidate?<><h3>{t('文件结构与配套关系')}</h3><BioCounts summary={data.candidate.summary}/><BioChecks checks={data.candidate.checks}/><BioRepresentation summary={data.candidate.summary} checks={data.candidate.checks}/><BioMembers members={data.candidate.members} projectId={projectId}/><h3>{t('研究设计缺口')}</h3><p>{t('结构核对不确认供体、切片或重复关系，请在实验设计中补充。')}</p><BioDesignLinks projectId={projectId}/><h3>{t('当前能力')}</h3><p>{t('导入核对与空间分析分别确认。H5 是否核对以此版本的实际检查记录为准。')}</p>{canConfirmCandidate(data)&&<><label className="intake-check"><input type="checkbox" checked={accept} onChange={e=>setAccepted(e.target.checked?signature:null)} disabled={writer.busy||writer.unknown}/>{t('接受此数据集及结构核对结果；后续设计、质控和方法须另行确认。')}</label><button type="button" className="button-primary" disabled={writer.busy||writer.unknown||!writer.valid||!accept} onClick={confirm}>{t('确认并发布数据集版本')}</button></>}</>:<p>{t('候选尚未就绪，请查看任务状态。')}</p>}{data.result_source&&<button type="button" onClick={()=>onNavigate({view:'bio-dataset',fileId:'',datasetId:data.result_source!.dataset_id,versionId:data.result_source!.dataset_version_id})}>{t('查看已发布数据集版本')}</button>}</>}<BioWriteStatus writer={writer}/></section>
}