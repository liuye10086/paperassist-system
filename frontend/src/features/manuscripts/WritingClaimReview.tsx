import {useEffect,useRef,useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {evidenceBase,evidencePage,validClaim,validEvidence,validEvidencePage,validReview,validReviewInput,type Claim,type Evidence,type ReviewInput,type Review} from '../literature/evidenceApi'
import type {Page} from '../literature/literatureApi'
import type {ClaimFragment} from '../literature/citationApi'
import {type LocalManifest} from './writingLiveTypes'
import {useWritingOperation} from './useWritingOperation'
import type {ProjectEvidenceOption} from './writingEvidenceOptions'
import ParagraphReferenceExcerpts,{readingScopeLabels as scopeLabels} from './ParagraphReferenceExcerpts'
type Option={key:string;label:string;title:string;scope:Evidence['reading_scope'];texts:string[];project_reference_id:string;metadata_version_id:string;frozen:boolean;origin:Record<string,unknown>}
type Props={projectId:string;text:string;context:string;language:'en'|'zh-CN';manifest:LocalManifest;onBinding:(claim:ClaimFragment|null,evidence:Evidence[])=>void
 /** Customer view (B03 task 7): the paragraph name, project literature added after freezing, and the trip to add more. */
 paragraphName?:string;projectOptions?:ProjectEvidenceOption[]|null;onNeedEvidence?:()=>void;returned?:boolean
 /** A claim created earlier for this exact text, read back on mount instead of creating another one. */
 pendingClaim?:string;claimFragment?:ClaimFragment|null;onClaimCreated?:(claim:Claim)=>void
 /** Customer view (B03 task 8): no context, claim, bibliography-version or review IDs and no raw decision values. */
 customerView?:boolean;suggestedEvidenceAliases?:string[]}
const statusLabels:Record<ReviewInput['status'],string>={needs_review:'待人工核验',supported:'支持',partial:'部分支持',unsupported:'不支持'}
const relevanceLabels:Record<ReviewInput['relevance'],string>={uncertain:'不确定',related:'相关',unrelated:'不相关'}
function origin(e:Evidence):Record<string,unknown>{return e.source.kind==='abstract'?{source_kind:'abstract',search_id:e.source.search_id}:e.source.kind==='pmc'?{source_kind:'pmc',pmc_receipt_id:e.source.pmc_receipt_id,item_id:e.location.item_id}:{source_kind:'material',material_id:e.source.material_id,item_id:e.location.item_id}}
export default function WritingClaimReview({projectId,text,context,language,manifest,onBinding,paragraphName,projectOptions,onNeedEvidence,returned=false,pendingClaim,claimFragment,onClaimCreated,customerView=false,suggestedEvidenceAliases}:Props){
 const {t}=useI18n(),op=useWritingOperation(),base=evidenceBase(projectId),[claim,setClaim]=useState<Claim|null>(null),[source,setSource]=useState(''),[quote,setQuote]=useState(''),[evidence,setEvidence]=useState<Evidence[]>([]),[checked,setChecked]=useState<string[]>([]),[status,setStatus]=useState<ReviewInput['status']>('needs_review'),[relevance,setRelevance]=useState<ReviewInput['relevance']>('uncertain'),[reason,setReason]=useState(''),[narrow,setNarrow]=useState(''),[limits,setLimits]=useState(''),[reviews,setReviews]=useState<{review:Review;metadata:string}[]>([]),[chosen,setChosen]=useState<string[]>([])
 function invalidate(){setChosen([]);onBinding(null,[])}
 function selectSource(alias:string,excerpt=''){
  invalidate();setSource(alias);setQuote(excerpt);setChecked([]);setStatus('needs_review');setRelevance('uncertain');setReason('');setNarrow('');setLimits('')
 }
 // Frozen evidence comes first; project literature is offered once per reference that is not already frozen.
 const frozen:Option[]=Object.entries(manifest.evidence).flatMap(([alias,value])=>value.binding.evidence.filter(e=>e.id===value.evidence_id).map(e=>({key:alias,label:`${alias} · ${value.binding.metadata.title} · ${e.reading_scope}`,title:value.binding.metadata.title,scope:e.reading_scope,texts:[e.quote],project_reference_id:value.binding.project_reference_id,metadata_version_id:value.binding.metadata_version_id,frozen:true,origin:origin(e)})))
 const added:Option[]=(projectOptions??[]).filter(o=>!frozen.some(f=>f.project_reference_id===o.project_reference_id)).map(o=>({key:`project:${o.project_reference_id}`,label:t('{title} · 摘要',{title:o.title}),title:o.title,scope:'abstract' as const,texts:o.texts,project_reference_id:o.project_reference_id,metadata_version_id:o.metadata_version_id,frozen:false,origin:{source_kind:'abstract',search_id:o.search_id}}))
 // Customers read “文献 {n} · {题名} · {阅读范围}”; internal roles keep the alias and raw reading scope.
 const options=[...frozen,...added].map((o,index)=>customerView?{...o,label:t('文献 {number} · {title} · {scope}',{number:index+1,title:o.title,scope:t(scopeLabels[o.scope])})}:o)
 const selected=options.find(e=>e.key===source)
 const quotable=!!selected&&!!quote.trim()&&selected.texts.some(item=>item.includes(quote))
 const review:ReviewInput={claim_revision:claim?.revision??0,project_reference_id:selected?.project_reference_id??'',evidence_ids:checked,status,relevance,reason,narrowed_statement:narrow,limitations:limits}
 async function create(){const result=await op.run(`${base}/claims`,(v):v is Claim=>validClaim(v,projectId)&&v.content===text&&v.context===context&&v.output_language===language,{content:text,context,output_language:language});if(result){claimId.current=result.id;setClaim(result);onClaimCreated?.(result)}}
 // Coming back to this paragraph reads the claim, its excerpts and decisions again, and keeps the chosen binding.
 const claimId=useRef<string|null>(null),restoreId=pendingClaim??claimFragment?.claim_id
 async function restore(id:string,live:()=>boolean){
  const found=await op.run(`${base}/claims/${encodeURIComponent(id)}`,(v):v is Claim=>validClaim(v,projectId)&&v.id===id&&v.content===text&&v.context===context&&v.output_language===language)
  if(!found||!live())return
  const url=`${base}/claims/${encodeURIComponent(id)}`,revision=found.revision
  const saved=await op.run(`${url}/evidence?revision=${revision}&page=1`,(v):v is Page<Evidence>=>validEvidencePage(v,projectId,id,revision,1))
  const decided=saved&&live()?await op.run(`${url}/reviews?revision=${revision}&page=1`,(v):v is Page<Review>=>evidencePage(v,projectId,1,x=>validReview(x,id,revision))):null
  if(!live())return
  claimId.current=found.id;setClaim(found);if(saved)setEvidence(saved.items)
  if(!decided)return
  const fragment=claimFragment?.claim_id===id&&claimFragment.claim_revision===revision?claimFragment:null
  const latest=new Map<string,Review>()
  for(const item of decided.items){const old=latest.get(item.project_reference_id);if(!old||Date.parse(item.created_at)>=Date.parse(old.created_at))latest.set(item.project_reference_id,item)}
  const records=[...latest.values()].flatMap(item=>{const metadata=fragment?.bindings.find(b=>b.review_id===item.id)?.metadata_version_id??options.find(o=>o.project_reference_id===item.project_reference_id)?.metadata_version_id;return metadata?[{review:item,metadata}]:[]})
  setReviews(records);setChosen(fragment?fragment.bindings.map(b=>b.review_id).filter(rid=>records.some(r=>r.review.id===rid)):[])
 }
 // oxlint-disable-next-line react-hooks/exhaustive-deps
 useEffect(()=>{if(!restoreId||claimId.current===restoreId)return;let live=true;void restore(restoreId,()=>live);return()=>{live=false}},[restoreId])
 async function attach(){if(!selected||!claim||!quotable)return;const result=await op.run(`${base}/claims/${encodeURIComponent(claim.id)}/evidence`,(v):v is Evidence=>validEvidence(v,claim.id,claim.revision),{claim_revision:claim.revision,project_reference_id:selected.project_reference_id,...selected.origin,quote});if(result){setEvidence(old=>[...old,result]);setQuote('')}}
 async function save(){if(!claim||!selected||!validReviewInput(review))return;const result=await op.run(`${base}/claims/${encodeURIComponent(claim.id)}/reviews`,(v):v is Review=>validReview(v,claim.id,claim.revision),review);if(result){setReviews(old=>[...old.filter(r=>r.review.project_reference_id!==result.project_reference_id),{review:result,metadata:selected.metadata_version_id}]);setChosen([]);onBinding(null,[]);setStatus('needs_review');setReason('')}}
 function choose(ids:string[]){setChosen(ids);if(!claim){onBinding(null,[]);return}const records=reviews.filter(r=>ids.includes(r.review.id));onBinding(records.length?{kind:'claim',claim_id:claim.id,claim_revision:claim.revision,bindings:records.map(r=>({review_id:r.review.id,metadata_version_id:r.metadata}))}:null,evidence.filter(e=>records.some(r=>r.review.evidence_ids.includes(e.id))))}
 const missing=!!onNeedEvidence&&!!projectOptions&&options.length===0
 const heading=customerView?'核对这段的文献依据':'精确新文献主张审核'
 return <section aria-label={t(heading)}><h5>{t(heading)}</h5><blockquote>{text}</blockquote><ParagraphReferenceExcerpts aliases={suggestedEvidenceAliases} manifest={manifest} onUse={selectSource} disabled={op.busy||!op.valid}/>{!customerView&&<p>{t('专属语境')} <code>{context}</code></p>}<p>{t('修改此段会清除本次绑定；旧主张或支持决定不能继承。')}</p>{missing&&<div className="warning-panel"><p>{t('{name}还缺一条文献依据。请选择支持这句话的原文。已加入的文献里没有可选原文。',{name:paragraphName??t('本段')})}</p><button type="button" onClick={onNeedEvidence}>{t('去添加文献（完成后回到本段）')}</button></div>}{returned&&added.length>0&&<p role="status">{t('已加入 {count} 篇文献。请选择支持这句话的原文。',{count:added.length})}</p>}<fieldset disabled={op.busy||!op.valid}><button type="button" disabled={!!claim||text.length>6000} onClick={()=>void create()}>{t('为此精确文本创建新主张')}</button>{claim&&(customerView?<p role="status">{t('已为这段文字建立核对记录（第 {revision} 版）',{revision:claim.revision})}</p>:<p>{claim.id} · {t('版本')} {claim.revision}</p>)}<label>{t('选择实际公开证据与书目')}<select value={source} onChange={e=>selectSource(e.target.value)}><option value="">{t('尚未选择')}</option>{options.map(o=><option key={o.key} value={o.key}>{o.label}</option>)}</select></label>{selected&&<>{selected.texts.map((item,index)=><blockquote key={index}>{item}</blockquote>)}{selected.frozen&&!customerView&&<p>{t('已冻结书目版本')} {selected.metadata_version_id}</p>}</>}<label>{t('新主张精确摘录')}<textarea value={quote} onChange={e=>{invalidate();setQuote(e.target.value)}} maxLength={10000}/></label><button type="button" disabled={!claim||!quotable} onClick={()=>void attach()}>{t('保存新主张证据')}</button>{evidence.filter(e=>e.project_reference_id===selected?.project_reference_id).map(e=><label key={e.id}><input type="checkbox" checked={checked.includes(e.id)} onChange={ev=>{invalidate();setChecked(old=>ev.target.checked?[...old,e.id]:old.filter(x=>x!==e.id))}}/>{e.quote}</label>)}<label>{t('本次支持决定')}<select value={status} onChange={e=>{invalidate();setStatus(e.target.value as ReviewInput['status'])}}><option value="needs_review">{t('待人工核验')}</option><option value="supported">{t('支持')}</option><option value="partial">{t('部分支持')}</option><option value="unsupported">{t('不支持')}</option></select></label><label>{t('本次文献相关性')}<select value={relevance} onChange={e=>{invalidate();setRelevance(e.target.value as ReviewInput['relevance'])}}><option value="uncertain">{t('不确定')}</option><option value="related">{t('相关')}</option><option value="unrelated">{t('不相关')}</option></select></label><label>{t('新主张人工理由')}<textarea value={reason} onChange={e=>{invalidate();setReason(e.target.value)}}/></label><label>{t('收窄后的论述')}<textarea value={narrow} onChange={e=>{invalidate();setNarrow(e.target.value)}}/></label><label>{t('读取范围与限制')}<textarea value={limits} onChange={e=>{invalidate();setLimits(e.target.value)}}/></label><button type="button" disabled={!validReviewInput(review)} onClick={()=>void save()}>{t('保存此主张的人工决定')}</button>{reviews.map((r,index)=><label key={r.review.id}><input type="checkbox" disabled={r.review.status!=='supported'||r.review.relevance!=='related'} checked={chosen.includes(r.review.id)} onChange={e=>choose(e.target.checked?[...chosen,r.review.id]:chosen.filter(x=>x!==r.review.id))}/>{customerView?t('决定 {number} · {status} · {relevance}',{number:index+1,status:t(statusLabels[r.review.status]),relevance:t(relevanceLabels[r.review.relevance])}):<>{t('明确绑定该新决定及书目')} {r.review.id} · {r.review.status} · {r.metadata}</>}</label>)}</fieldset>{op.error&&<p role="alert">{t(op.error)}</p>}</section>
}
