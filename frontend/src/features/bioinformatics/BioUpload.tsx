import {useEffect,useRef,useState} from 'react'
import {apiError,useI18n,safeError} from '../../shared/i18n'
import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
import type {BatchItem} from '../files/batchUploadApi'
import {UploadBatchCard,UploadFileRow,UploadHistory,type MaterialHistory} from '../files/UploadHistory'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {useResearchRead} from '../research-results/api'
import useResearchDraft from '../research-results/useResearchDraft'
import {bioRequest,jsonRequest,projectBase,IntakeError} from './api'

type Item=Pick<BatchItem,'id'|'filename'|'status'|'file_id'> & {size_bytes?:number;error?:BatchItem['error']}
type Batch={id:string;project_id:string;created_at:string;items:Item[]}
type Registration={key:string;body:{items:{client_id:string;filename:string;size_bytes:number}[]}}
type UploadDraft={batch:Batch|null;registration:Registration|null;unknown:boolean}
type Props={embedded?:boolean;active?:boolean;projectId:string;onChanged:()=>void;registerLeaveGuard?:RegisterLeaveGuard;customerView?:boolean;materialHistory?:MaterialHistory}
const reselectMessage='请重新选择名称和大小一致的原文件。'
const pending=(item:Item)=>!item.file_id&&item.status!=='rejected'

export default function BioUpload(props:Props){
 return <UploadContent key={`${getApiUserId()}:${props.projectId}`} {...props}/>
}
function UploadContent({projectId,onChanged,registerLeaveGuard,active=true,embedded=false,customerView=false,materialHistory}:Props){
 const {t,locale}=useI18n()
 // File objects stay in memory. Only the original request identity and server snapshot survive a reload.
 const [draft,setDraft]=useResearchDraft<UploadDraft>(projectId,'bio-upload',()=>({batch:null,registration:null,unknown:false}))
 const batch=draft.batch,unknown=draft.unknown
 const [files,setFiles]=useState<File[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[valid,setValid]=useState(true)
 const [batchPage,setBatchPage]=useState(1)
 const batchRead=useResearchRead<{items:Batch[];total:number}>(`${projectBase(projectId)}/bio-upload-batches?page=${batchPage}`,active&&valid)
 const batches=batchRead.data?.items??[],batchTotal=batchRead.data?.total??0
 const create=useRef<Registration|null>(draft.registration),request=useRef<AbortController|null>(null),live=useRef(true)
 const registrationLocked=!!batch||!!draft.registration
 const setBatch=(value:Batch)=>setDraft(old=>({...old,batch:value}))
 const setUnknown=(value:boolean)=>setDraft(old=>({...old,unknown:value}))
 const missingLocal=!!batch&&batch.items.some((item,index)=>pending(item)&&(!files[index]||files[index].name!==item.filename||item.size_bytes!==undefined&&files[index].size!==item.size_bytes))
 useDraftLeaveGuard(registerLeaveGuard,files.length>0&&!batch,busy||unknown)
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();create.current=null;setFiles([]);setValid(false)}),[])
 useEffect(()=>{live.current=true;return()=>{live.current=false;request.current?.abort()}},[])

 function refreshHistory(){
  if(materialHistory)batchRead.refresh()
  onChanged()
 }

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
   setUnknown(false);refreshHistory()
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
  try{const next=await bioRequest<Batch>(`${projectBase(projectId)}/bio-upload-batches/${encodeURIComponent(batch.id)}`,{signal:c.signal});if(!live.current||c.signal.aborted)return;setBatch(next);setUnknown(false);refreshHistory()}
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

 function restoreBatch(value:Batch|null){
  setDraft({batch:value,registration:null,unknown:false})
  create.current=null
  setFiles([])
  setError('')
 }

 function retryPicker(item:Item,index:number){
  return <label>{t('重新选择同一文件')}<input type="file" disabled={busy} onChange={event=>{
   const file=event.target.files?.[0]
   if(!file||file.name!==item.filename||item.size_bytes!==undefined&&file.size!==item.size_bytes){setError(reselectMessage);return}
   setFiles(old=>{const next=[...old];next[index]=file;return next})
   setError('')
  }}/></label>
 }

 const batchActions=batch&&<>
  <button type="button" disabled={busy||!valid} onClick={()=>void check()}>{t('重新读取上传批次')}</button>
  {batch.items.every(item=>!pending(item))&&<button type="button" disabled={busy} onClick={()=>restoreBatch(null)}>{t('开始另一批上传')}</button>}
 </>
 const batchPagination=batchTotal>5&&<nav className="file-pagination" aria-label={t('上传批次')}>
  <button type="button" disabled={batchPage===1} onClick={()=>setBatchPage(page=>page-1)}>{t('上一页')}</button>
  <span>{batchPage} / {Math.ceil(batchTotal/5)}</span>
  <button type="button" disabled={batchPage*5>=batchTotal} onClick={()=>setBatchPage(page=>page+1)}>{t('下一页')}</button>
 </nav>
 const visibleBatches=batch?[batch,...batches.filter(value=>value.id!==batch.id)]:batches

 return <section className="bio-workspace bio-upload">
  {!embedded&&<h3>{t('生信上传与数据包')}</h3>}
  <p>{t(customerView?'上传测序数据包、矩阵或样本信息表，每批最多 10 个文件。':embedded?'支持数据包、矩阵和样本信息表；每批最多 10 个文件，上传后选择分析，再继续导入核对。':'原件保存后仍待生信导入；每批最多 10 项，按顺序上传，不触发旧文件解析。')}</p>
  {customerView?<div className="customer-upload-row">{filePicker}{uploadButton}</div>:filePicker}
  {files.length>0&&(!materialHistory||!batch)&&<ul>{files.filter(Boolean).map((file,index)=><li key={index}>{file.name} · {file.size.toLocaleString()} {t('字节')}</li>)}</ul>}
  {missingLocal&&!error&&<p>{t(reselectMessage)}</p>}
  {error&&<p role="alert" className="error-panel">{t(error)}</p>}
  {unknown&&<p className="warning-panel">{t('上传结果尚未核实，先读取原批次；保持原文件和请求身份。')}</p>}
  {materialHistory?<UploadHistory projectId={projectId} history={materialHistory} batchPagination={batchPagination}
   emptyBatches={!!batchRead.data&&!batchRead.error&&batchTotal===0&&!batch} onRefresh={batchRead.refresh}>
   {batchRead.error&&<p role="alert" className="error-panel">{t('上传批次读取失败，请刷新资料。')}</p>}
   {visibleBatches.map(value=>{
    const current=value.id===batch?.id
    const actions=current?<div className="upload-batch-actions">{batchActions}</div>:
     value.items.some(pending)&&<button type="button" className="button-quiet" disabled={busy||registrationLocked}
      onClick={()=>restoreBatch(value)}>{t('继续上传')}</button>
    return <UploadBatchCard key={value.id} title={`${t('上传批次')} · ${new Date(value.created_at).toLocaleString(locale)}`} showColumns actions={actions}>
     {value.items.map((item,index)=><UploadFileRow key={item.id} projectId={projectId} filename={item.filename} fileId={item.file_id}
      status={item.status} material={materialHistory.describe(item.file_id,item.filename,/\.(tar(\.gz)?|tgz)$/i.test(item.filename)?'bio_bundle':'bio_component')}
      error={item.error?apiError(item.error,'文件处理失败，请重试。'):undefined} retry={current&&pending(item)&&retryPicker(item,index)} />)}
    </UploadBatchCard>
   })}
  </UploadHistory>:<>
   {batch&&<ul>{batch.items.map((item,index)=><li key={item.id}>{item.filename}{pending(item)&&retryPicker(item,index)} · {t(item.file_id?(customerView?'已上传':'已保存，待生信导入'):item.status==='rejected'?'上传被拒绝':'待上传或待核对')}</li>)}</ul>}
   {(!customerView||batch)&&<div className="intake-actions">{!customerView&&uploadButton}{batchActions}</div>}
   {!batch&&batches.length>0&&<section className="bio-upload-history" aria-label={t('已上传批次')}>
    <h4>{t('已上传批次')}</h4>
    <div className="bio-upload-history-list">{batches.map(value=><button key={value.id} type="button" disabled={busy||registrationLocked}
     onClick={()=>restoreBatch(value)}>{value.items.map(item=>item.filename).join(' · ')}</button>)}</div>
    {batchPagination}
   </section>}
  </>}
 </section>
}
