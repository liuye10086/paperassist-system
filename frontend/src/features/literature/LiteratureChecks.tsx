import {useEffect,useRef,useState} from 'react'
import {translateForLocale,useI18n,type Locale} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {TaskRequestError,taskRequest} from '../tasks/taskApi'
import {basePath} from './literatureApi'
import {reviewName} from './evidenceApi'
import {EvidencePagination} from './LiteratureMaterials'
import {canSimulateDoi,checkBase,checkStatusLabel,safeLandingTarget,validCheckCandidate,validCheckConfig,validCheckHistory,validCheckReceipt,type CheckCandidate,type CheckKind,type CheckReceipt} from './checkApi'
type Props={projectId:string;referenceId:string;initialSearchId?:string;onDenied:()=>void;onClose?:()=>void;onVerify?:()=>void}
const readError='核验资料读取失败，已读历史仍保留。'
function useCheckResource<T>(url:string,guard:(v:unknown)=>v is T,revision:number,onDenied:()=>void,retainPage=false){
 const callbacks=useRef({guard,onDenied});useEffect(()=>{callbacks.current={guard,onDenied}})
 const [state,setState]=useState<{url:string;data:T|null;error:string;revision:number}>({url:'',data:null,error:'',revision:-1})
 useEffect(()=>{let alive=true;const controller=new AbortController()
  void taskRequest(url,controller,v=>callbacks.current.guard(v),readError).then(data=>{if(alive)setState({url,data,error:'',revision})}).catch(cause=>{if(alive){if(cause instanceof TaskRequestError&&[403,404].includes(cause.status))callbacks.current.onDenied();setState(old=>({url,data:retainPage||old.url===url?old.data:null,error:readError,revision}))}})
  return()=>{alive=false;controller.abort()}
 },[url,revision,retainPage])
 return state.url===url?{data:state.data,error:state.error,loading:state.revision!==revision}:{data:retainPage?state.data:null,error:'',loading:true}
}
export default function LiteratureChecks(props:Props){return <ChecksScope key={`${props.projectId}:${props.referenceId}:${props.initialSearchId??''}`} {...props}/>}
function ChecksScope({projectId,referenceId,initialSearchId,onDenied,onClose,onVerify}:Props){
 const {t}=useI18n(),base=checkBase(projectId),referenceUrl=`${base}/references/${encodeURIComponent(referenceId)}`
 const [revision,setRevision]=useState(0),[page,setPage]=useState(1),[selected,setSelected]=useState(initialSearchId??''),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const active=useRef<AbortController|null>(null),alive=useRef(true),retry=useRef<{signature:string;key:string}|null>(null)
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;active.current?.abort()}},[])
 const config=useCheckResource(`${base}/config`,v=>validCheckConfig(v,projectId),revision,onDenied)
 const candidate=useCheckResource<CheckCandidate>(referenceUrl,v=>validCheckCandidate(v,referenceId),revision,onDenied)
 // Only pages within this keyed project/reference scope may share the last successfully read page.
 const history=useCheckResource(`${referenceUrl}/history?page=${page}`,v=>validCheckHistory(v,referenceId,page),revision,onDenied,true)
 const item=candidate.data,source=item?.sources.find(s=>s.search_id===selected)??item?.sources.find(s=>s.search_id===item.source.search_id)??item?.sources[0]
 const language=source?.output_language??'zh-CN',explain=(key:string)=>translateForLocale(key,language),simulation=canSimulateDoi(config.data)
 async function check(kind:CheckKind){
  if(!source||active.current||kind==='doi_resolution'&&!canSimulateDoi(config.data))return
  const body={kind,search_id:source.search_id},signature=JSON.stringify(body)
  if(retry.current?.signature!==signature)retry.current={signature,key:crypto.randomUUID()}
  const controller=new AbortController();active.current=controller;setBusy(true);setError('')
  try{await taskRequest(`${referenceUrl}/receipts`,controller,(v):v is CheckReceipt=>validCheckReceipt(v,referenceId)&&v.kind===kind&&v.search_id===source.search_id,'核验未确认，请刷新历史后重试。',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':retry.current.key},body:signature});if(alive.current&&!controller.signal.aborted){retry.current=null;setPage(1);setRevision(v=>v+1)}}
  catch(cause){if(alive.current){if(cause instanceof TaskRequestError&&[403,404].includes(cause.status))onDenied();setError('核验未确认，请刷新历史后重试。')}}
  finally{if(active.current===controller)active.current=null;if(alive.current)setBusy(false)}
 }
 const locked=busy||candidate.loading
 return <section className="literature-panel literature-checks" aria-label={t('文献三项核验')}><div className="literature-actions"><h3>{t('文献三项核验')}</h3><button type="button" disabled={busy} onClick={()=>{setError('');setRevision(v=>v+1)}}>{t('刷新核验记录')}</button>{onClose&&<button type="button" onClick={onClose}>{t('关闭三项核验')}</button>}</div>
 {(config.loading||candidate.loading||history.loading)&&<p role="status">{t('正在读取核验记录……')}</p>}{[config.error,candidate.error,history.error,error].filter((v,i,a)=>v&&a.indexOf(v)===i).map(message=><p role="alert" key={message}>{t(message)}</p>)}
 {item&&source&&<><p lang={language} className="muted">{explain('来源匹配、DOI 解析与论述支持分别记录；均不表示已取得全文。')}</p>
 <label>{t('下一次核查来源')}<select disabled={locked} value={source.search_id} onChange={e=>setSelected(e.target.value)}>{item.sources.map((s,i)=><option key={s.search_id} value={s.search_id}>{t('保存检索 {number}',{number:i+1})} · {s.output_language==='en'?'English':t('简体中文')}{s.source_kind==='synthetic_fixture'?` · ${t('合成测试资料')}`:''}</option>)}</select></label>
 <div className="literature-check-grid"><article><h4>{t('来源匹配')}</h4><CurrentCheck receipt={item.saved_record} language={language} projectId={projectId} sources={item.sources}/><p lang={language} className="muted">{explain('仅核对已保存原始来源、身份与书目字段；未重新检索线上文献，也不判断内容支持。')}</p><button type="button" disabled={locked} onClick={()=>void check('saved_record')}>{t('核查保存来源')}</button></article>
 <article><h4>{t('DOI 解析')}</h4><CurrentCheck receipt={item.doi_resolution} language={language} projectId={projectId} sources={item.sources}/><p lang={language} className="muted">{explain('DOI 解析只说明标识符的解析结果，不证明书目真实性或论述支持。')}</p><p lang={language} className="warning-panel">{explain(simulation?'当前仅允许离线模拟 DOI，不访问外网。':'当前环境关闭真实 DOI 请求。')}</p><button type="button" disabled={locked||config.loading||!simulation} onClick={()=>void check('doi_resolution')}>{t(simulation?'模拟 DOI 解析（离线）':'检查 DOI 解析')}</button></article>
 <article><h4>{t('按论述人工支持')}</h4>{!item.content_support.length&&<p lang={language}>{explain('尚无关联论述的人工支持记录。')}</p>}{item.content_support.map(claim=>{const c=(key:string)=>translateForLocale(key,claim.output_language);return <section key={`${claim.claim_id}:${claim.claim_revision}`} lang={claim.output_language}><blockquote className="literature-original">{claim.content}</blockquote><p>{translateForLocale('论述版本：{revision}',claim.output_language,{revision:claim.claim_revision})} · <strong>{c(claim.latest_review?reviewName(claim.latest_review.status):'待人工核验')}</strong></p>{!claim.source_current&&<p className="warning-panel">{c('当前来源已变化或不可用；历史结果保留原样。')}</p>}{claim.latest_review?<><p className="literature-original">{claim.latest_review.reason}</p><p className="literature-original">{claim.latest_review.limitations}</p>{claim.latest_review.narrowed_statement&&<blockquote className="literature-original">{claim.latest_review.narrowed_statement}</blockquote>}</>:<p>{c('未保存本论述的人工支持决定。')}</p>}</section>})}{onVerify&&<button type="button" onClick={onVerify}>{t('去核验论述与证据')}</button>}</article></div></>}
 <details open><summary>{t('核验历史')}</summary>{history.data&&<>{history.error&&history.data.page!==page&&<div className="warning-panel"><p>{t('第 {requested} 页读取失败；当前显示已读第 {shown} 页。',{requested:page,shown:history.data.page})}</p><div className="literature-actions"><button type="button" onClick={()=>setRevision(v=>v+1)}>{t('重试第 {page} 页',{page})}</button><button type="button" onClick={()=>setPage(history.data!.page)}>{t('返回已读第 {page} 页',{page:history.data.page})}</button></div></div>}{!history.data.items.length&&<p>{t('尚无核验历史。')}</p>}<ol className="literature-history">{history.data.items.map(receipt=><li key={receipt.id}><h4>{t(receipt.kind==='saved_record'?'来源匹配':'DOI 解析')}</h4><ReceiptView receipt={receipt} projectId={projectId} sourceNumber={candidate.data?.sources.findIndex(s=>s.search_id===receipt.search_id)===undefined?0:candidate.data.sources.findIndex(s=>s.search_id===receipt.search_id)+1}/></li>)}</ol><EvidencePagination page={history.data.page} total={history.data.total} label="核验历史分页" onPage={next=>{setPage(next);if(next===page)setRevision(v=>v+1)}}/></>}</details>
 </section>
}
function CurrentCheck({receipt,language,projectId,sources}:{receipt:CheckReceipt|null;language:Locale;projectId:string;sources:CheckCandidate['sources']}){return receipt?<ReceiptView receipt={receipt} projectId={projectId} sourceNumber={sources.findIndex(s=>s.search_id===receipt.search_id)+1}/>:<p lang={language}>{translateForLocale('尚未检查',language)}</p>}
function ReceiptView({receipt,projectId,sourceNumber}:{receipt:CheckReceipt;projectId:string;sourceNumber:number}){
 const {t,locale}=useI18n(),r=receipt.result,language=receipt.output_language,e=(key:string)=>translateForLocale(key,language),target=safeLandingTarget(r.resolution_target)
 const synthetic=r.execution_kind==='synthetic_fixture'||r.status==='synthetic_match'||receipt.source_kind==='synthetic_fixture'
 return <div lang={language} className="literature-check-receipt"><p className="muted">{translateForLocale(sourceNumber>0?'本次结果来自保存检索 {number}':'本次结果来自历史保存来源（当前来源列表中不可用）',language,{number:sourceNumber})}</p><strong className={r.status==='source_conflict'?'warning-panel':''}>{e(checkStatusLabel(r.status))}</strong>{synthetic&&<p className="warning-panel"><strong>{e(r.execution_kind==='synthetic_fixture'?'离线模拟，未进行真实 DOI 核验':'合成测试来源，不代表真实文献核验')}</strong></p>}
 {!receipt.source_current&&<p className="warning-panel">{e('当前来源已变化或不可用；历史结果保留原样。')}</p>}<p><time dateTime={receipt.created_at}>{new Date(receipt.created_at).toLocaleString(locale)}</time></p><details><summary>{t('查看核验依据')}</summary><p>PMID {r.source.pmid}{r.doi?` · DOI ${r.doi}`:''}{r.http_status?` · HTTP ${r.http_status}`:''}</p>{r.resolution_target&&(target?<p><a href={target} target="_blank" rel="noopener noreferrer">{t('打开落地目标（不会自动访问）')}</a><span className="literature-original"> · {target}</span></p>:<p>{e('落地目标无法安全打开。')}</p>)}<ProjectDownloadLink href={`${basePath(projectId)}/receipts/${encodeURIComponent(r.source.receipt_id)}/source`} filename="pubmed-source.xml">{t('下载原始 JSON/XML')}</ProjectDownloadLink></details></div>
}
