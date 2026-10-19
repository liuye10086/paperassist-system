import {useEffect,useRef,useState} from 'react'
import {translateForLocale,useI18n} from '../../shared/i18n'
import {isTask,type TaskView} from '../tasks/taskTypes'
import {evidenceBase,evidencePage,validClaim,validClaimDetail,validEvidence,validEvidencePage,validReview,validReviewInput,reviewStatuses,reviewName,readingScopeName,locationText,object,type Claim,type ClaimDetail,type Evidence,type Review,type ReviewInput,type Language} from './evidenceApi'
import {useEvidenceMutation,useEvidenceResource} from './evidenceHooks'
import {EvidencePagination,type SelectedSource} from './LiteratureMaterials'
import type {Page} from './literatureApi'
export type ClaimSelection={claim:ClaimDetail;evidence:Evidence[];evidenceIds:string[];isCurrent:boolean}
export default function LiteratureClaims({projectId,outputLanguage,referenceId,referenceTitles={},source,onDenied,onSelection,onOpenTask,onAddMaterials}:{projectId:string;outputLanguage?:string;referenceId:string;referenceTitles?:Record<string,string>;source:SelectedSource|null;onDenied:()=>void;onSelection:(v:ClaimSelection|null)=>void;onOpenTask?:(id:string)=>void;onAddMaterials?:()=>void}){
 const {t,locale}=useI18n(),base=evidenceBase(projectId);const [refresh,setRefresh]=useState(0),[page,setPage]=useState(1),[id,setId]=useState(''),[version,setVersion]=useState(0),[evidencePageNumber,setEvidencePage]=useState(1),[reviewPage,setReviewPage]=useState(1)
 const [content,setContent]=useState(''),[context,setContext]=useState(''),[language,setLanguage]=useState<Language>(outputLanguage==='en'?'en':'zh-CN'),[quote,setQuote]=useState(''),[selected,setSelected]=useState<Evidence[]>([])
 const [status,setStatus]=useState<ReviewInput['status']>('needs_review'),[relevance,setRelevance]=useState<ReviewInput['relevance']>('uncertain'),[reason,setReason]=useState(''),[narrow,setNarrow]=useState(''),[limitations,setLimitations]=useState(''),[query,setQuery]=useState(''),[supplementReason,setSupplementReason]=useState(''),[savedTask,setSavedTask]=useState<TaskView|null>(null)
 const mutation=useEvidenceMutation(onDenied)
 const claims=useEvidenceResource<Page<Claim>>(`${base}/claims?page=${page}`,v=>evidencePage(v,projectId,page,x=>validClaim(x,projectId)),refresh,onDenied)
 const detail=useEvidenceResource<ClaimDetail>(id?`${base}/claims/${encodeURIComponent(id)}?${version?`revision=${version}`:''}`:null,(v):v is ClaimDetail=>validClaimDetail(v,projectId,id)&&(!version||v.revision===version),refresh,onDenied)
 const contentField=useRef<HTMLTextAreaElement>(null),reviewField=useRef<HTMLTextAreaElement>(null),explain=(key:string)=>translateForLocale(key,detail.data?.output_language??language)
 const revision=detail.data?.revision??0,isCurrent=!!detail.data?.is_current&&(version===0||version===detail.data.revision)
 const evidence=useEvidenceResource<Page<Evidence>>(id&&revision?`${base}/claims/${encodeURIComponent(id)}/evidence?revision=${revision}&page=${evidencePageNumber}`:null,v=>validEvidencePage(v,projectId,id,revision,evidencePageNumber),refresh,onDenied)
 const reviews=useEvidenceResource<Page<Review>>(id&&revision?`${base}/claims/${encodeURIComponent(id)}/reviews?revision=${revision}&page=${reviewPage}`:null,v=>evidencePage(v,projectId,reviewPage,x=>validReview(x,id,revision)),refresh,onDenied)
 // Reconcile the manual draft when its frozen server identity or selected reference changes.
 // oxlint-disable-next-line react/set-state-in-effect
 useEffect(()=>{setReason('');setNarrow('');setLimitations('');setStatus('needs_review');setRelevance('uncertain');setSavedTask(null)},[id,revision,referenceId])
 // Selections belong to one saved claim revision and may span evidence pages.
 // oxlint-disable-next-line react/set-state-in-effect
 useEffect(()=>{setSelected([])},[id,revision])
 // A new saved source invalidates the previous quote draft.
 // oxlint-disable-next-line react/set-state-in-effect
 useEffect(()=>{setQuote('')},[source])
 // Initialize the editable draft from a newly loaded immutable server revision.
 // oxlint-disable-next-line react/set-state-in-effect
 useEffect(()=>{if(detail.data){setContent(detail.data.content);setContext(detail.data.context);setLanguage(detail.data.output_language)}},[detail.data])
 useEffect(()=>{onSelection(detail.data?{claim:detail.data,evidence:[...new Map([...(evidence.data?.items??[]),...selected].map(e=>[e.id,e])).values()],evidenceIds:selected.map(e=>e.id),isCurrent}:null)},[detail.data,evidence.data,selected,isCurrent,onSelection,referenceId])
 const actualSelected=selected.filter(e=>e.project_reference_id===referenceId).map(e=>e.id)
 const bibliography=(e:Evidence)=>e.bibliography?`${e.bibliography.title||t('题名未提供')} · PMID ${e.bibliography.pmid}`:referenceTitles[e.project_reference_id]??e.source.filename??(typeof e.source.pmcid==='string'?e.source.pmcid:t('项目保存文献'))
 const review:ReviewInput={claim_revision:revision,project_reference_id:referenceId,evidence_ids:actualSelected,status,relevance,reason,narrowed_statement:narrow,limitations}
 async function saveClaim(revise=false){if(!content.trim())return
 const body={content,context,output_language:language,...(revise?{expected_revision:revision}:{})}
 const result=await mutation.post(revise?`${base}/claims/${encodeURIComponent(id)}/versions`:`${base}/claims`,body,v=>validClaim(v,projectId))
 if(result){setId(result.id);setVersion(0);setRefresh(r=>r+1);setSelected([]);setSavedTask(null)}
 }
 async function attach(){if(!source||!id||!isCurrent||!referenceId||!quote.trim()||!source.text.includes(quote))return
 const {text:unused,project_reference_id:sourceReference,...origin}=source;void unused
 if(sourceReference&&sourceReference!==referenceId)return
 const result=await mutation.post(`${base}/claims/${encodeURIComponent(id)}/evidence`,{claim_revision:revision,project_reference_id:referenceId,...origin,quote},v=>validEvidence(v,id,revision))
 if(result){setQuote('');setEvidencePage(1);setRefresh(r=>r+1)}
 }
 async function saveReview(){if(!isCurrent||!validReviewInput(review))return
 if(await mutation.post(`${base}/claims/${encodeURIComponent(id)}/reviews`,review,v=>validReview(v,id,revision))){setReviewPage(1);setRefresh(r=>r+1)}
 }
 async function supplement(){if(!id||!isCurrent||detail.data?.supplement||!query.trim()||!supplementReason.trim())return
 const result=await mutation.post(`${base}/claims/${encodeURIComponent(id)}/supplement`,{claim_revision:revision,query,reason:supplementReason},(v):v is {task:TaskView;round:1;limit:20}=>object(v)&&v.round===1&&v.limit===20&&isTask(v.task,projectId)&&v.task.task_type==='literature_search')
 if(result){setSavedTask(result.task);setRefresh(r=>r+1)}
 }
 function chooseClaim(value:string){setId(value);setVersion(0);setEvidencePage(1);setReviewPage(1);if(!value){setContent('');setContext('')}}
 return <section className="literature-panel" aria-label={t('论述与人工核验')}><h3>{t('论述与人工核验')}</h3><p className="warning-panel">{explain('仅摘要证据不能证明全文细节；解析成功不代表支持论述。')}</p>
 {claims.error&&<p role="alert">{t(claims.error)}</p>}{detail.error&&<p role="alert">{t(detail.error)}</p>}{mutation.error&&<p role="alert">{t(mutation.error)}</p>}
 <label>{t('选择论述')}<select value={id} onChange={e=>chooseClaim(e.target.value)}><option value="">{t('新建论述')}</option>{claims.data?.items.map(c=><option key={c.id} value={c.id}>{c.content}</option>)}</select></label>
 {claims.data&&<EvidencePagination page={page} total={claims.data.total} label="论述分页" onPage={p=>{setPage(p);chooseClaim('')}}/>}
 {detail.data&&<><label>{t('查看论述版本')}<select value={version||detail.data.revision} onChange={e=>{setVersion(Number(e.target.value));setEvidencePage(1);setReviewPage(1)}}>{detail.data.versions.map(v=><option key={v.revision} value={v.revision}>{t('版本')} {v.revision} · {v.content}</option>)}</select></label>{!isCurrent&&<p className="warning-panel">{explain('历史版本只读；旧判定和模型建议不能确认新论述。')}</p>}<p>{t('论述版本：{revision}',{revision})}</p></>}
 <fieldset disabled={mutation.busy||!!id&&!isCurrent}><legend>{t(id?'修订论述':'新建论述')}</legend><label>{t('论述文本')}<textarea ref={contentField} value={content} maxLength={6000} onChange={e=>setContent(e.target.value)}/></label><label>{t('论述语境')}<textarea value={context} maxLength={6000} onChange={e=>setContext(e.target.value)}/></label><label>{t('论述输出语言')}<select value={language} onChange={e=>setLanguage(e.target.value as Language)}><option value="zh-CN">{t('简体中文')}</option><option value="en">English</option></select></label><button type="button" disabled={!content.trim()} onClick={()=>void saveClaim(!!id)}>{t(id?'保存为新版本':'创建论述')}</button></fieldset>
 <fieldset disabled={mutation.busy||!isCurrent||!referenceId}><legend>{t('附加实际来源摘录')}</legend>{source?<><p className="muted">{t(source.source_kind==='pmc'?'当前读取范围：PMC 正文片段':source.source_kind==='abstract'?'当前读取范围：摘要':'当前读取范围：用户材料条目')}</p><blockquote className="literature-original">{source.text}</blockquote></>:<p>{explain('先选择已保存摘要或材料条目。')}</p>}<label>{t('精确摘录')}<textarea value={quote} maxLength={10000} onChange={e=>setQuote(e.target.value)}/></label>{source&&quote&&!source.text.includes(quote)&&<p role="alert">{t('摘录必须是所选实际来源的精确子串。')}</p>}<button type="button" disabled={!source||!quote.trim()||!source.text.includes(quote)} onClick={()=>void attach()}>{t('保存来源证据')}</button></fieldset>
 {evidence.error&&<p role="alert">{t(evidence.error)}</p>}{evidence.data&&<><h4>{t('本版本保存的证据')}</h4><p className="muted">{t('可跨文献选择证据供模型比较；人工决定仅使用当前所选文献的证据。')}</p><p>{t('已选择 {count} 条证据，来自 {references} 篇文献',{count:selected.length,references:new Set(selected.map(e=>e.project_reference_id)).size})}</p>{selected.length>0&&<div><h5>{t('已选证据')}</h5><ul>{selected.map(e=><li key={e.id}>{bibliography(e)} · {e.quote}</li>)}</ul></div>}{!evidence.data.items.length&&<p>{explain('尚无证据；只能保存待人工核验。')}</p>}<ul className="literature-evidence-items">{evidence.data.items.map(e=><li key={e.id}><label><input type="checkbox" checked={selected.some(item=>item.id===e.id)} disabled={!isCurrent} onChange={ev=>setSelected(old=>ev.target.checked?[...old,e]:old.filter(i=>i.id!==e.id))}/>{t(readingScopeName(e.reading_scope))}</label><p className="muted">{bibliography(e)}</p><blockquote className="literature-original">{e.quote}</blockquote><p className="muted">{e.source.filename} {locationText(e.location)}</p></li>)}</ul><EvidencePagination page={evidencePageNumber} total={evidence.data.total} label="证据分页" onPage={setEvidencePage}/></>}
 <fieldset disabled={mutation.busy||!isCurrent||!referenceId}><legend>{t('保存人工决定（不会使用模型结果自动填写）')}</legend><div className="project-fields"><label>{t('论述支持状态')}<select value={status} onChange={e=>setStatus(e.target.value as ReviewInput['status'])}>{reviewStatuses.map(s=><option key={s} value={s}>{t(reviewName(s))}</option>)}</select></label><label>{t('文献相关性')}<select value={relevance} onChange={e=>setRelevance(e.target.value as ReviewInput['relevance'])}><option value="related">{t('相关')}</option><option value="unrelated">{t('不相关')}</option><option value="uncertain">{t('不确定')}</option></select></label></div><label>{t('人工核验理由')}<textarea ref={reviewField} value={reason} maxLength={4000} onChange={e=>setReason(e.target.value)}/></label><label>{t('收窄后的论述（部分支持必填）')}<textarea value={narrow} maxLength={6000} onChange={e=>setNarrow(e.target.value)}/></label><label>{t('读取边界与限制')}<textarea value={limitations} maxLength={4000} onChange={e=>setLimitations(e.target.value)}/></label><p className="muted">{explain('缺少证据或存在冲突时保留待人工核验；相关性和支持状态分别记录。')}</p><button type="button" disabled={!validReviewInput(review)} onClick={()=>void saveReview()}>{t('保存人工核验')}</button></fieldset>
 {reviews.error&&<p role="alert">{t(reviews.error)}</p>}{reviews.data&&<><h4>{t('人工决定历史')}</h4>{reviews.data.items.length===0&&<p>{explain('本版本尚无人工决定。')}</p>}<ol>{reviews.data.items.map(r=><li key={r.id}><strong>{explain(reviewName(r.status))}</strong> · {explain(r.relevance==='related'?'相关':r.relevance==='unrelated'?'不相关':'不确定')} · {new Date(r.created_at).toLocaleString(locale)}<p className="literature-original">{r.reason}</p>{r.narrowed_statement&&<p className="literature-original">{r.narrowed_statement}</p>}{r.limitations&&<p className="literature-original">{r.limitations}</p>}<p className="muted">{t('已记录当前项目用户的人工判定。')}</p></li>)}</ol><EvidencePagination page={reviewPage} total={reviews.data.total} label="人工决定分页" onPage={setReviewPage}/></>}
 <fieldset disabled={mutation.busy||!isCurrent||!!detail.data?.supplement}><legend>{t('有限补搜')}</legend><p>{explain('同一论述（含全部修订）最多补搜 1 轮、20 篇。')}</p>{detail.data?.supplement&&<p className="warning-panel">{explain('本论述已使用补搜轮次，可查看或恢复原任务。')}</p>}<label>{t('补搜检索式')}<textarea value={query} maxLength={4000} onChange={e=>setQuery(e.target.value)}/></label><label>{t('补搜理由')}<textarea value={supplementReason} maxLength={2000} onChange={e=>setSupplementReason(e.target.value)}/></label><button type="button" disabled={!query.trim()||!supplementReason.trim()} onClick={()=>void supplement()}>{t('创建补搜任务')}</button></fieldset>
 {detail.data?.supplement&&<div className="warning-panel"><p lang={detail.data.output_language}>{explain('补搜一轮（最多 20 篇）后仍不足时，请补充实际材料、收窄论述并重新人工核验；不会自动追加补搜。')}</p><div className="literature-actions">{onAddMaterials&&<button type="button" onClick={onAddMaterials}>{t('补充实际材料')}</button>}<button type="button" disabled={!isCurrent} onClick={()=>contentField.current?.focus()}>{t('收窄论述')}</button><button type="button" disabled={!isCurrent||!referenceId} onClick={()=>reviewField.current?.focus()}>{t('重新人工核验')}</button></div></div>}
 {(savedTask||detail.data?.supplement)&&<button type="button" onClick={()=>onOpenTask?.(savedTask?.id??detail.data!.supplement!.task_id)} disabled={!onOpenTask}>{t('查看补搜任务')}</button>}
 </section>
}
