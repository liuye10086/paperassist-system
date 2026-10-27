import {useLiteratureLeaveGuard} from './literatureActivityContext'
import ModelCallHistory from './ModelCallHistory'
import AssistanceResult from './AssistanceResult'
import {useState} from 'react'
import {translateForLocale,useI18n} from '../../shared/i18n'
import {isTask,taskDisplayName,type TaskView} from '../tasks/taskTypes'
import {basePath,type Page} from './literatureApi'
import {evidencePage,type Language} from './evidenceApi'
import {validAssistance,validAssistanceRequest,assistanceKindName,type Assistance,type AssistanceRequest} from './assistanceApi'
import {useEvidenceMutation,useEvidenceResource} from './evidenceHooks'
import {EvidencePagination} from './LiteratureMaterials'
import {type ClaimSelection} from './LiteratureClaims'
export default function LiteratureAssistance({projectId,researchTopic,outputLanguage,referenceId,selection,onDenied,onOpenTask}:{projectId:string;researchTopic:string;outputLanguage?:string;referenceId:string;selection:ClaimSelection|null;onDenied:()=>void;onOpenTask?:(id:string)=>void}){
 const {t,locale}=useI18n(),base=`${basePath(projectId)}/assistance`;const [topic,setTopic]=useState(researchTopic),[context,setContext]=useState(''),[language,setLanguage]=useState<Language>(outputLanguage==='en'?'en':'zh-CN'),[revision,setRevision]=useState(0),[page,setPage]=useState(1),[taskId,setTaskId]=useState(''),[saved,setSaved]=useState<TaskView|null>(null)
 const signature=JSON.stringify([topic,context,language]),[baseline,setBaseline]=useState(signature);useLiteratureLeaveGuard(signature!==baseline,false)
 const list=useEvidenceResource<Page<Assistance>>(`${base}/tasks?page=${page}`,v=>evidencePage(v,projectId,page,x=>validAssistance(x,projectId)),revision,onDenied)
 const detail=useEvidenceResource<Assistance>(taskId?`${base}/tasks/${encodeURIComponent(taskId)}`:null,(v):v is Assistance=>validAssistance(v,projectId)&&v.task.id===taskId,revision,onDenied)
 const mutation=useEvidenceMutation(onDenied),explain=(key:string)=>translateForLocale(key,detail.data?.input_version.output_language??language)
 const selectedEvidence=selection?.evidence.filter(e=>selection.evidenceIds.includes(e.id))??[]
 const evidenceIds=selectedEvidence.filter(e=>e.project_reference_id===referenceId).map(e=>e.id),comparisonIds=selectedEvidence.map(e=>e.id)
 const canCompare=!!selection?.isCurrent&&comparisonIds.length>=2&&comparisonIds.length<=20&&new Set(selectedEvidence.map(e=>e.project_reference_id)).size>=2
 async function create(kind:AssistanceRequest['kind']){const input:AssistanceRequest=kind==='search_plan'?{kind,research_topic:topic,source_context:context,output_language:language}:kind==='evidence_comparison'?{kind,claim_id:selection?.claim.id??'',claim_revision:selection?.claim.revision??0,evidence_ids:comparisonIds,output_language:language}:{kind,claim_id:selection?.claim.id??'',claim_revision:selection?.claim.revision??0,project_reference_id:referenceId,evidence_ids:evidenceIds,output_language:language}
 if(kind!=='search_plan'&&!selection?.isCurrent||kind==='evidence_comparison'&&!canCompare||!validAssistanceRequest(input))return
 const result=await mutation.post(`${base}/tasks`,input,(v):v is TaskView=>isTask(v,projectId)&&v.task_type==='literature_assistance')
 if(result){setBaseline(signature);setSaved(result);setTaskId(result.id);setRevision(v=>v+1)}
 }
 return <section className="literature-panel" aria-label={t('受限模型建议')}><div className="literature-actions"><h3>{t('受限模型建议')}</h3><button type="button" onClick={()=>setRevision(r=>r+1)}>{t('刷新模型任务')}</button></div><p className="warning-panel">{t('新模型任务默认等待授权；已保存调用与历史结果可在下方读取。')}</p><p>{t('模型建议与人工决定独立保存；历史建议只读，不能自动确认或改写新版本。')}</p>
 <fieldset disabled={mutation.busy}><legend>{t('生成检索方案建议')}</legend><label>{t('建议研究主题')}<textarea value={topic} maxLength={10000} onChange={e=>setTopic(e.target.value)}/></label><label>{t('建议来源语境')}<textarea value={context} maxLength={20000} onChange={e=>setContext(e.target.value)}/></label><label>{t('模型任务输出语言')}<select value={language} onChange={e=>setLanguage(e.target.value as Language)}><option value="zh-CN">{t('简体中文')}</option><option value="en">English</option></select></label><button type="button" disabled={!topic.trim()} onClick={()=>void create('search_plan')}>{t('保存检索方案建议任务')}</button><button type="button" disabled={!selection?.isCurrent||!referenceId||evidenceIds.length===0} onClick={()=>void create('evidence_review')}>{t('保存所选证据的核验建议任务')}</button><p>{t('比较同一论述当前版本的至少两篇文献；请核对人群、干预、终点与随访是否可比。')}</p><p className="muted">{t('比较建议不自动成为人工决定，也不解除引用门禁。')}</p><button type="button" disabled={!canCompare} onClick={()=>void create('evidence_comparison')}>{t('保存多来源比较建议任务')}</button></fieldset>
 {mutation.error&&<p role="alert">{t(mutation.error)}</p>}{saved&&<p role="status">{t('模型任务已保存，人工决定未改变。')}</p>}{list.error&&<p role="alert">{t(list.error)}</p>}
 {list.data&&<><ol>{list.data.items.map(item=><li key={item.task.id}><span>{t(assistanceKindName(item.kind))} · {t(taskDisplayName(item.task))} · {new Date(item.task.created_at).toLocaleString(locale)}</span><button type="button" onClick={()=>setTaskId(item.task.id)}>{t('查看建议与等待状态')}</button></li>)}</ol><EvidencePagination page={page} total={list.data.total} label="模型建议分页" onPage={setPage}/></>}
 {detail.error&&<p role="alert">{t(detail.error)}</p>}{detail.data&&<section aria-label={t('模型建议详情')}><h4>{t(assistanceKindName(detail.data.kind))}</h4><p>{explain(taskDisplayName(detail.data.task))} · {detail.data.input_version.output_language==='en'?'English':t('简体中文')}</p><p className="muted">{explain('建议绑定提交时的资料与论述版本，历史记录保留。')}</p>{!detail.data.result&&<p>{explain('当前任务尚无模型建议，请查看等待或失败状态。')}</p>}{detail.data.result&&<AssistanceResult key={detail.data.task.id} outputLanguage={detail.data.input_version.output_language} kind={detail.data.kind} result={detail.data.result}/>}<ModelCallHistory calls={detail.data.model_calls}/>{detail.data.task.status==='failed'&&<p className="warning-panel">{t('此建议任务失败，已保存调用与用量仍保留。')}</p>}{onOpenTask&&<button type="button" onClick={()=>onOpenTask(detail.data!.task.id)}>{t('查看模型任务')}</button>}</section>}
 </section>
}