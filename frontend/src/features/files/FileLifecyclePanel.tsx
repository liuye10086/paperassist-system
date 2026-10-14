import {useCallback,useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import FileImpactReview,{retentionText} from './FileImpactReview'
import useLifecycleSubmission from './useLifecycleSubmission'
import {isPage,isReceipt,lifecycleBase,lifecycleRequest,reasonLabels,type Page,type Receipt} from './fileLifecycleApi'
type Props={projectId:string;fileId:string;active:boolean;observedVersion?:number;onUnavailable:()=>void}
export default function FileLifecyclePanel(props:Props){return <Panel key={JSON.stringify([props.projectId,props.fileId])} {...props}/>}
function Panel({projectId,fileId,active,observedVersion,onUnavailable}:Props){
 const {t,locale}=useI18n(),[review,setReview]=useState(false),[reason,setReason]=useState(''),[history,setHistory]=useState<Page<Receipt>|null>(null),[receipt,setReceipt]=useState<Receipt|null>(null),[page,setPage]=useState(1),[refresh,setRefresh]=useState(0),[loading,setLoading]=useState(false),[error,setError]=useState(''),[valid,setValid]=useState(true)
 const base=lifecycleBase(projectId,fileId),generation=useRef(0),unavailable=useRef(onUnavailable)
 useEffect(()=>{unavailable.current=onUnavailable},[onUnavailable])
 const lost=useCallback(()=>{generation.current++;setValid(false);setReview(false);setReason('');setReceipt(null);setHistory(null);unavailable.current()},[])
 // send only the frozen payload retained by the submission hook.
 const send=useLifecycleSubmission<Receipt>((r,signal)=>lifecycleRequest(r.url,signal,lost,(v):v is Receipt=>isReceipt(v,fileId)&&v.reason===JSON.parse(r.body).reason&&v.assessment_revision===JSON.parse(r.body).expected_assessment_revision,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':r.key},body:r.body}),v=>{setReceipt(v);setReason('');setReview(false);setPage(1);setRefresh(n=>n+1)},()=>{setReview(false);setRefresh(n=>n+1)})
 useEffect(()=>onApiSessionChanged(()=>{generation.current++;setValid(false);setReview(false);setReason('');setReceipt(null);setHistory(null);setError('')}),[])
 useEffect(()=>{
  if(!active||!valid)return
  const c=new AbortController(),captured=generation.current;let current=true
  // Invalidate the old history while synchronizing this request's page/scope.
  // oxlint-disable-next-line react/set-state-in-effect
  setLoading(true);setHistory(null);setError('');const timer=window.setTimeout(()=>c.abort(),15000)
  void lifecycleRequest(`${base}/deletion-requests?page=${page}&page_size=10`,c.signal,lost,(v):v is Page<Receipt>=>isPage(v,page,(x):x is Receipt=>isReceipt(x,fileId))).then(v=>{if(current&&captured===generation.current&&!c.signal.aborted)setHistory(v)}).catch(cause=>{if(current&&captured===generation.current)setError(safeError(cause,'删除申请历史读取失败或超时，请重试。'))}).finally(()=>{window.clearTimeout(timer);if(current&&captured===generation.current)setLoading(false)})
  return()=>{current=false;c.abort();window.clearTimeout(timer)}
 },[base,fileId,page,refresh,active,valid,lost])
 const display=(value:Receipt)=><article key={value.id}><p className="saved-notice">{t(value.status==='retained'?'已记录申请，文件按规则保留':'申请存在阻塞原因，文件继续保留')}</p><time dateTime={value.requested_at}>{new Date(value.requested_at).toLocaleString(locale)}</time><p>{t('申请理由：{reason}',{reason:value.reason})}</p><ul>{value.assessment.reasons.map(r=><li key={r.code}>{t(reasonLabels[r.code])}</li>)}</ul></article>
 return <section className="file-lifecycle" aria-label={t('文件保留与删除申请')}><h4>{t('文件保留与删除申请')}</h4><p>{t('可提交删除申请；申请即时记录保留或阻塞结果，不安排后续自动删除。')}</p><p className="file-retention">{t(retentionText)}</p>
  {valid&&<><label>{t('删除申请理由')}<textarea maxLength={500} value={reason} disabled={send.busy||send.unknown} onChange={e=>setReason(e.target.value)}/></label><button disabled={!active||send.busy||send.unknown} onClick={()=>setReview(true)}>{t('提交删除申请')}</button>{review&&active&&<FileImpactReview projectId={projectId} fileId={fileId} action="delete" operation={t('记录删除申请并保留文件')} observedVersion={observedVersion} onUnavailable={lost} onCancel={()=>setReview(false)} confirmDisabled={!reason.trim()||reason.trim().length>500||send.busy||send.unknown} onConfirm={v=>void send.submit({url:`${base}/deletion-requests`,body:JSON.stringify({expected_assessment_revision:v.assessment_revision,reason:reason.trim()})})}/>}</>}
  {send.busy&&<p role="status">{t('正在提交申请……')}</p>}{send.error&&<p role="alert" className="error-panel">{t(send.error)}</p>}{send.unknown&&valid&&<button disabled={send.busy} onClick={()=>void send.submit()}>{t('使用同一请求确认申请结果')}</button>}{receipt&&display(receipt)}
  <h5>{t('删除申请历史')}</h5><button disabled={loading||!valid} onClick={()=>setRefresh(n=>n+1)}>{t('重新读取申请历史')}</button>{loading&&<p role="status">{t('正在读取申请历史……')}</p>}{error&&<p role="alert">{t(error)}</p>}{history&&<><p>{t('删除申请共 {total} 条',{total:history.total})}</p>{!history.items.length&&<p>{t('尚无删除申请。')}</p>}{history.items.map(display)}<nav aria-label={t('删除申请历史分页')}><button disabled={page===1||loading} onClick={()=>setPage(n=>n-1)}>{t('上一页删除申请')}</button><span>{t('第 {page} 页',{page})}</span><button disabled={page*10>=history.total||loading} onClick={()=>setPage(n=>n+1)}>{t('下一页删除申请')}</button></nav></>}
 </section>
}
