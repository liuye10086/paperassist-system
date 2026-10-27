import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {apiError,safeError,useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {canRetryPdf,hasUnconfirmedPdfRequest,listPdfExports,submitPdfExport,type PdfExport,type PdfScope} from './pdfApi'
type Props=PdfScope&{registerLeaveGuard?:RegisterLeaveGuard;sourceLabel:string;active?:boolean;disabled?:boolean;onOpenTask?:(id:string)=>void}
export default function PdfExports(props:Props){return <Exports key={`${props.projectId}:${props.sourceKind}:${props.sourceId}:${props.sourceSha256??''}`} {...props}/>}
function Exports({projectId,sourceKind,sourceId,sourceSha256,sourceLabel,active=true,disabled=false,onOpenTask,registerLeaveGuard}:Props){
 const {t}=useI18n(),visible=useDocumentVisible(),scope={projectId,sourceKind,sourceId,sourceSha256}
 const [items,setItems]=useState<PdfExport[]>([]),[error,setError]=useState(''),[actionError,setActionError]=useState(''),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false),[attempt,setAttempt]=useState(0),[sessionValid,setSessionValid]=useState(true)
 const mounted=useRef(true),request=useRef<AbortController|null>(null),panel=useRef<HTMLElement|null>(null)
 const [panelVisible,setPanelVisible]=useState(false)
 useLayoutEffect(()=>{
  const ancestors:HTMLElement[]=[]
  for(let node=panel.current;node;node=node.parentElement)ancestors.push(node)
  const update=()=>setPanelVisible(ancestors.every(node=>!node.hidden&&(node.tagName!=='DETAILS'||node.hasAttribute('open'))))
  update();const observer=new MutationObserver(update)
  ancestors.forEach(node=>observer.observe(node,{attributes:true,attributeFilter:['hidden','open']}))
  return()=>observer.disconnect()
 },[])
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort()}},[])
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();setSessionValid(false);setItems([]);setError('');setActionError('')}),[])
 useEffect(()=>{
  if(!active||!visible||!panelVisible||!sessionValid||busy)return
  let live=true,timer=0;const controller=new AbortController()
  async function load(){try{const data=await listPdfExports({projectId,sourceKind,sourceId,sourceSha256},controller);if(!live||controller.signal.aborted)return;setItems(data.items);setLoaded(true);setError('');if(data.items.some(e=>e.status==='queued'||e.status==='running'))timer=window.setTimeout(()=>void load(),3000)}catch(cause){if(live)setError(safeError(cause,'PDF 状态读取失败，请刷新。'))}}
  void load();return()=>{live=false;controller.abort();window.clearTimeout(timer)}
 },[projectId,sourceKind,sourceId,sourceSha256,active,visible,panelVisible,sessionValid,attempt,busy])
 async function submit(parent?:string){
  if(request.current||disabled||!loaded||!active||!sessionValid)return
  const controller=new AbortController();request.current=controller;setBusy(true);setActionError('')
  try{const value=await submitPdfExport(scope,controller,parent,items.find(item=>item.id===parent));if(!mounted.current||controller.signal.aborted)return;setItems(old=>[value,...old.filter(item=>item.id!==value.id)]);setAttempt(a=>a+1)}
  catch(cause){if(mounted.current&&!controller.signal.aborted)setActionError(safeError(cause,'PDF 请求未确认，请刷新状态后重试。'));else if(mounted.current&&sessionValid)setActionError('PDF 请求未确认，请刷新状态后重试。')}
  finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}
 }
 const blocked=busy||!loaded||!sessionValid||disabled||!active||!panelVisible
 const unconfirmed=hasUnconfirmedPdfRequest(scope)
 useDraftLeaveGuard(registerLeaveGuard,unconfirmed||items.some(item=>hasUnconfirmedPdfRequest(scope,item.id)),busy)
 return <section ref={panel} className="pdf-exports manuscript-panel" aria-label={t('PDF 导出')}><h4>{t('PDF 导出')}</h4>
 <p>{t('PDF 来源：{version}，使用该已保存的 DOCX；后续编辑不会更新此 PDF。',{version:sourceLabel})}</p><p className="muted">{t('PDF 独立转换，不调用模型或搜索；失败后仍可下载 Word。')}</p>
 {unconfirmed&&<p className="warning-panel">{t('上次 PDF 请求尚未确认。请沿用原请求确认结果，确认完成后再新建导出。')}</p>}
 <div className="analysis-actions"><button type="button" disabled={blocked||!unconfirmed&&items.some(item=>item.status==='queued'||item.status==='running')||!!error} onClick={()=>void submit()}>{t(busy?'正在提交……':unconfirmed?'确认上次 PDF 请求':items.length?'新建 PDF 导出':'生成 PDF')}</button><button type="button" disabled={busy||!sessionValid||!active} onClick={()=>setAttempt(a=>a+1)}>{t('刷新 PDF 状态')}</button></div>
 {error&&<p role="alert" className="error-panel">{t(error)}</p>}{actionError&&<p role="alert" className="error-panel">{t(actionError)}</p>}{!sessionValid&&<p role="alert">{t('会话已失效，请重新登录。')}</p>}
 {items.map((item,index)=><div key={item.id} className="manuscript-export"><strong>{t('PDF 导出 {number}',{number:items.length-index})}</strong> · <span role={item.status==='queued'||item.status==='running'?'status':undefined}>{t({queued:'待执行',running:'运行中',succeeded:'已完成',failed:'执行失败'}[item.status])}</span><p><time dateTime={item.created_at}>{item.created_at}</time>{item.parent_export_id&&<> · {t('重试生成，原失败记录保留')}</>}</p>
 {item.error_code&&<p className="warning-panel">{t(apiError({code:item.error_code},'PDF 转换失败，请核对状态。'))}</p>}
 {item.status==='succeeded'&&item.download_url&&<ProjectDownloadLink href={item.download_url} filename={item.filename??'report.pdf'}>{t('下载 PDF')}</ProjectDownloadLink>}
 {(hasUnconfirmedPdfRequest(scope,item.id)||canRetryPdf(item,items))&&<button type="button" disabled={blocked||!hasUnconfirmedPdfRequest(scope,item.id)&&items.some(row=>row.status==='queued'||row.status==='running')} onClick={()=>void submit(item.id)}>{t(hasUnconfirmedPdfRequest(scope,item.id)?'确认上次 PDF 重试':item.recovery_mode==='local_candidate'?'恢复原导出候选':'重试 PDF')}</button>}
 {onOpenTask?<button type="button" onClick={()=>onOpenTask(item.task_id)}>{t('查看 PDF 任务')}</button>:<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(item.task_id)}`}>{t('查看 PDF 任务')}</a>}
 </div>)}
 </section>
}
