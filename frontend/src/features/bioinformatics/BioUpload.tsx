import {useEffect,useRef,useState} from 'react'
import {useI18n,safeError} from '../../shared/i18n'
import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import useResearchDraft from '../research-results/useResearchDraft'
import {bioRequest,jsonRequest,projectBase,IntakeError} from './api'

type Item={id:string;filename:string;size_bytes?:number;status:string;file_id:string|null;error?:{code:string}|null}
type Batch={id:string;project_id:string;items:Item[];profile?:unknown}
type Registration={key:string;body:{items:{client_id:string;filename:string;size_bytes:number}[]}}
type UploadDraft={batch:Batch|null;registration:Registration|null;unknown:boolean}
type Props={embedded?:boolean;active?:boolean;projectId:string;onChanged:()=>void;registerLeaveGuard?:RegisterLeaveGuard;customerView?:boolean}
const reselectMessage='请重新选择名称和大小一致的原文件。'
const pending=(item:Item)=>!item.file_id&&item.status!=='rejected'

export default function BioUpload(props:Props){
 return <UploadContent key={`${getApiUserId()}:${props.projectId}`} {...props}/>
}
function UploadContent({projectId,onChanged,registerLeaveGuard,active=true,embedded=false,customerView=false}:Props){
 const {t}=useI18n()
 // File objects stay in memory. Only the original request identity and server snapshot survive a reload.
 const [draft,setDraft]=useResearchDraft<UploadDraft>(projectId,'bio-upload',()=>({batch:null,registration:null,unknown:false}))
 const batch=draft.batch,unknown=draft.unknown
 const [files,setFiles]=useState<File[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[valid,setValid]=useState(true)
 const [batches,setBatches]=useState<Batch[]>([]),[batchPage,setBatchPage]=useState(1),[batchTotal,setBatchTotal]=useState(0)
 const create=useRef<Registration|null>(draft.registration),request=useRef<AbortController|null>(null),live=useRef(true)
 const registrationLocked=!!batch||!!draft.registration
 const setBatch=(value:Batch)=>setDraft(old=>({...old,batch:value}))
 const setUnknown=(value:boolean)=>setDraft(old=>({...old,unknown:value}))
 const missingLocal=!!batch&&batch.items.some((item,index)=>pending(item)&&(!files[index]||files[index].name!==item.filename||item.size_bytes!==undefined&&files[index].size!==item.size_bytes))
 useDraftLeaveGuard(registerLeaveGuard,files.length>0&&!batch,busy||unknown)
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();create.current=null;setFiles([]);setValid(false)}),[])
 useEffect(()=>{live.current=true;return()=>{live.current=false;request.current?.abort()}},[])
 useEffect(()=>{
  if(!active||!valid)return
  const c=new AbortController();let current=true
  void bioRequest<{items:Batch[];total:number}>(`${projectBase(projectId)}/bio-upload-batches?page=${batchPage}`,{signal:c.signal})
   .then(result=>{if(current){setBatches(result.items??[]);setBatchTotal(result.total??0)}}).catch(()=>{})
  return()=>{current=false;c.abort()}
 },[active,valid,projectId,batchPage])

 async function upload(){
  if(!valid||busy||!files.length&&!create.current)return
  setBusy(true);setError('');const c=new AbortController();request.current=c
  let current=batch
  try{
   if(!current){
    create.current??={key:crypto.randomUUID(),body:{items:files.map(file=>({client_id:crypto.randomUUID(),filename:file.name,size_bytes:file.size}))}}
    // Persist before POST, including an interrupted registration whose response never arrives.
    setDraft(old=>({...old,registration:create.current,unknown:true}))
    current=await bioRequest<Batch>(`${projectBase(projectId)}/bio-upload-batches`,{...jsonRequest(create.current.body,create.current.key),signal:c.signal})
    if(!live.current||c.signal.aborted)return
    setBatch(current)
   }
   const registered=current
   if(!registered)return
   for(const [index,item] of registered.items.entries()){
    if(!pending(item))continue
    const fresh:Batch=await bioRequest<Batch>(`${projectBase(projectId)}/bio-upload-batches/${encodeURIComponent(registered.id)}`,{signal:c.signal})
    if(!live.current||c.signal.aborted)return
    setBatch(fresh);current=fresh
    const latest=fresh.items.find(value=>value.id===item.id)
    if(!latest||!pending(latest))continue
    const local=files[index]
    if(!local||local.name!==latest.filename||latest.size_bytes!==undefined&&local.size!==latest.size_bytes){setError(reselectMessage);break}
    const body=new FormData();body.append('file',local);setUnknown(true)
    await bioRequest<Item>(`${projectBase(projectId)}/bio-upload-batches/${encodeURIComponent(fresh.id)}/items/${encodeURIComponent(item.id)}`,{method:'POST',body,signal:c.signal},120000)
    current=await bioRequest<Batch>(`${projectBase(projectId)}/bio-upload-batches/${encodeURIComponent(fresh.id)}`,{signal:c.signal})
    if(!live.current||c.signal.aborted)return
    setBatch(current)
   }
   setUnknown(false);onChanged()
  }catch(cause){
   if(!live.current||c.signal.aborted)return
   const definite=cause instanceof IntakeError&&cause.status<500
   setError(safeError(cause,'生信上传失败，请核对批次后继续。'));setUnknown(!definite)
   if(definite&&!current){create.current=null;setDraft(old=>({...old,registration:null,unknown:false}))}
  }finally{if(request.current===c)request.current=null;if(live.current)setBusy(false)}
 }
 async function check(){
  if(!batch||busy||!valid)return
  const c=new AbortController();request.current=c;setBusy(true);setError('')
  try{const next=await bioRequest<Batch>(`${projectBase(projectId)}/bio-upload-batches/${encodeURIComponent(batch.id)}`,{signal:c.signal});if(!live.current||c.signal.aborted)return;setBatch(next);setUnknown(false);onChanged()}
  catch(cause){if(live.current&&!c.signal.aborted){setError(safeError(cause,'生信上传失败，请核对批次后继续。'));setUnknown(true)}}
  finally{if(request.current===c)request.current=null;if(live.current)setBusy(false)}
 }
 const recoveringRegistration=!batch&&!!draft.registration&&unknown
 const filePicker=<label className="upload-file-picker">
  {t('选择生信文件')}
  <input type="file" multiple disabled={busy||registrationLocked} accept=".tar,.tar.gz,.tgz,.gz,.mtx,.tsv,.csv,.xlsx,.txt,.json,.h5,.hdf5,.png,.jpg,.jpeg" onChange={e=>{
   const next=Array.from(e.target.files??[])
   if(next.length>10||next.some(file=>file.size===0)){setError('每批最多 10 项，且文件不能为空。');return}
   setFiles(next);setError('')
  }}/>
 </label>
 const uploadButton=<button type="button" className="button-primary" disabled={busy||!valid||!files.length&&!recoveringRegistration||unknown&&!!batch||!!batch&&!batch.items.some(pending)}
  onClick={()=>void upload()}>{t(busy?'正在上传':batch?'核对并继续上传':recoveringRegistration&&!files.length?'核对登记结果':embedded?'开始上传':'登记并上传')}</button>
 return <section className="bio-workspace bio-upload">
  {!embedded&&<h3>{t('生信上传与数据包')}</h3>}
  <p>{t(customerView?'上传测序数据包、矩阵或样本信息表，每批最多 10 个文件。':embedded?'支持数据包、矩阵和样本信息表；每批最多 10 个文件，上传后选择分析，再继续导入核对。':'原件保存后仍待生信导入；每批最多 10 项，按顺序上传，不触发旧文件解析。')}</p>
  {customerView?<div className="customer-upload-row">{filePicker}{uploadButton}</div>:filePicker}
  {files.length>0&&<ul>{files.filter(Boolean).map((file,index)=><li key={index}>{file.name} · {file.size.toLocaleString()} {t('字节')}</li>)}</ul>}
  {batch&&<ul>{batch.items.map((item,index)=><li key={item.id}>{item.filename}{pending(item)&&<label>{t('重新选择同一文件')}<input type="file" disabled={busy} onChange={e=>{const file=e.target.files?.[0];if(!file||file.name!==item.filename||item.size_bytes!==undefined&&file.size!==item.size_bytes){setError(reselectMessage);return}setFiles(old=>{const next=[...old];next[index]=file;return next});setError('')}}/></label>} · {t(item.file_id?(customerView?'已上传':'已保存，待生信导入'):item.status==='rejected'?'上传被拒绝':'待上传或待核对')}</li>)}</ul>}
  {missingLocal&&!error&&<p>{t(reselectMessage)}</p>}
  {error&&<p role="alert" className="error-panel">{t(error)}</p>}
  {unknown&&<p className="warning-panel">{t('上传结果尚未核实，先读取原批次；保持原文件和请求身份。')}</p>}
  {(!customerView||batch)&&<div className="intake-actions">
   {!customerView&&uploadButton}
   {batch&&<button type="button" disabled={busy||!valid} onClick={()=>void check()}>{t('重新读取上传批次')}</button>}
   {batch&&batch.items.every(item=>!pending(item))&&<button type="button" disabled={busy} onClick={()=>{setDraft({batch:null,registration:null,unknown:false});setFiles([]);create.current=null;setError('')}}>{t('开始另一批上传')}</button>}
  </div>}
  {!batch&&batches.length>0&&<section className="bio-upload-history" aria-label={t('已上传批次')}><h4>{t('已上传批次')}</h4><div className="bio-upload-history-list">{batches.map(value=><button key={value.id} type="button" disabled={busy||registrationLocked} onClick={()=>{setDraft({batch:value,registration:null,unknown:false});create.current=null;setFiles([]);setError('')}}>{value.items.map(item=>item.filename).join(' · ')}</button>)}</div>{batchTotal>5&&<nav className="file-pagination" aria-label={t('上传批次')}><button type="button" disabled={batchPage===1} onClick={()=>setBatchPage(page=>page-1)}>{t('上一页')}</button><span>{batchPage} / {Math.ceil(batchTotal/5)}</span><button type="button" disabled={batchPage*5>=batchTotal} onClick={()=>setBatchPage(page=>page+1)}>{t('下一页')}</button></nav>}</section>}
 </section>
}
