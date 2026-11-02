import {type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {apiError,safeError,useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {pdfRequestTimeoutMs,listPdfExports,type PdfExport,type PdfScope} from './pdfApi'
type Props=PdfScope&{registerLeaveGuard?:RegisterLeaveGuard;sourceLabel:string;active?:boolean;disabled?:boolean;onOpenTask?:(id:string)=>void}
export default function PdfExportHistory(props:Props){return <Exports key={`${props.projectId}:${props.sourceKind}:${props.sourceId}:${props.sourceSha256??''}`} {...props}/>}
function Exports({projectId,sourceKind,sourceId,sourceSha256,sourceLabel,active=true,onOpenTask}:Props){
 const {t}=useI18n(),visible=useDocumentVisible(),scope={projectId,sourceKind,sourceId,sourceSha256}
 const [items,setItems]=useState<PdfExport[]>([]),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[sessionValid,setSessionValid]=useState(true)
 const panel=useRef<HTMLElement|null>(null)
 const [panelVisible,setPanelVisible]=useState(false)
 useLayoutEffect(()=>{
  const ancestors:HTMLElement[]=[]
  for(let node=panel.current;node;node=node.parentElement)ancestors.push(node)
  const update=()=>setPanelVisible(ancestors.every(node=>!node.hidden&&(node.tagName!=='DETAILS'||node.hasAttribute('open'))))
  update();const observer=new MutationObserver(update)
  ancestors.forEach(node=>observer.observe(node,{attributes:true,attributeFilter:['hidden','open']}))
  return()=>observer.disconnect()
 },[])
 useEffect(()=>onApiSessionChanged(()=>{setSessionValid(false);setItems([]);setError('')}),[])
 useEffect(()=>{
  if(!active||!visible||!panelVisible||!sessionValid)return
  let live=true,timer=0;const controller=new AbortController()
  async function load(){try{const data=await listPdfExports({projectId,sourceKind,sourceId,sourceSha256},controller);if(!live||controller.signal.aborted)return;setItems(data.items);setError('');if(data.items.some(e=>e.status==='queued'||e.status==='running'))timer=window.setTimeout(()=>void load(),3000)}catch(cause){if(live)setError(safeError(cause,'PDF 状态读取失败，请刷新。'))}}
  void load();return()=>{live=false;controller.abort();window.clearTimeout(timer)}
 },[projectId,sourceKind,sourceId,sourceSha256,active,visible,panelVisible,sessionValid,attempt])
 return <section ref={panel} className="pdf-exports manuscript-panel" aria-label={t('历史 PDF 文件')}><h4>{t('历史 PDF 文件')}</h4>
 <p>{sourceLabel}</p><p className="muted">{t('仅保留已有 PDF 的查看与下载。文档请导出 Word。')}</p>
 <button type="button" disabled={!sessionValid||!active} onClick={()=>setAttempt(a=>a+1)}>{t('刷新 PDF 状态')}</button>
 {error&&<p role="alert" className="error-panel">{t(error)}</p>}{!sessionValid&&<p role="alert">{t('会话已失效，请重新登录。')}</p>}
 {items.map((item,index)=><div key={item.id} className="manuscript-export"><strong>{t('PDF 导出 {number}',{number:items.length-index})}</strong> · <span role={item.status==='queued'||item.status==='running'?'status':undefined}>{t({queued:'待执行',running:'运行中',succeeded:'已完成',failed:'执行失败'}[item.status])}</span><p><time dateTime={item.created_at}>{item.created_at}</time>{item.parent_export_id&&<> · {t('重试生成，原失败记录保留')}</>}</p>
 {item.error_code&&<p className="warning-panel">{t(apiError({code:item.error_code},'PDF 转换失败，请核对状态。'))}</p>}
 {item.status==='succeeded'&&item.download_url&&<ProjectDownloadLink timeoutMs={pdfRequestTimeoutMs(scope)} href={item.download_url} filename={item.filename??'report.pdf'}>{t('下载 PDF')}</ProjectDownloadLink>}
 {onOpenTask?<button type="button" onClick={()=>onOpenTask(item.task_id)}>{t('查看 PDF 任务')}</button>:<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(item.task_id)}`}>{t('查看 PDF 任务')}</a>}
 </div>)}
 </section>
}
