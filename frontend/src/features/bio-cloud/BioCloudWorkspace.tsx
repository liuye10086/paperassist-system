import {reconcileRun} from './api'
import {useEffect,useRef,useState} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {jsonRequest,projectBase} from '../bioinformatics/api'
import useDraftLeaveGuard from '../projects/useDraftLeaveGuard'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {CloudClient,PART_SIZE,matrixOutputs,newRunDraft,resumeUpload,runBody} from './cloud'
import type {Capabilities,CloudRun,RunDraft,Upload} from './cloud'
const terminal=new Set(['completed','failed','cancelled'])
const providerTerminal=new Set(['FAILED','CANCELLED','DELETED','COMPLETED'])
const canCancel=(run:CloudRun)=>!providerTerminal.has(run.provider_state??'')&&!['completed','cancelled'].includes(run.status)&&(run.status!=='failed'||!!run.provider_run_id)
const statusNames:Record<string,string>={queued:'排队中',submitting:'正在提交',submission_unknown:'提交结果未知',pending:'云端等待',running:'分析中',cancelling:'取消中',cancelled:'已取消',collecting:'获取/验证结果',completed:'云计算完成，待矩阵审核',failed:'失败',blocked:'阻塞',uploading:'上传中',created:'等待上传'}
export default function BioCloudWorkspace({projectId,active,onSelectMatrix,registerLeaveGuard}:{projectId:string;active:boolean;onSelectMatrix:(roles:Record<'matrix'|'features'|'barcodes',string>)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const [providerIds,setProviderIds]=useState<Record<string,string>>({})
 const [client]=useState(()=>new CloudClient(projectId))
 const [cap,setCap]=useState<Capabilities|null>(null),[uploads,setUploads]=useState<Upload[]>([]),[runs,setRuns]=useState<CloudRun[]>([])
 const [valid,setValid]=useState(true),[busy,setBusy]=useState(false),[unknown,setUnknown]=useState(!!client.pending),[error,setError]=useState(''),[attempt,setAttempt]=useState(0)
 const [draft,setDraft]=useState<RunDraft>(newRunDraft),[file,setFile]=useState<File|null>(null),[uploadId,setUploadId]=useState(()=>{try{return sessionStorage.getItem(client.storageKey+':upload')??''}catch{return ''}}),[progress,setProgress]=useState('')
 const controllers=useRef(new Set<AbortController>()),local=useRef<AbortController|null>(null),live=useRef(true)
 const stop=()=>{controllers.current.forEach(c=>c.abort());controllers.current.clear();local.current?.abort();local.current=null}
 useEffect(()=>{live.current=true;const unsubscribe=onApiSessionChanged(()=>{stop();setValid(false);setBusy(false);setUnknown(false);setCap(null);setUploads([]);setRuns([]);setDraft(newRunDraft());setProviderIds({});setFile(null);setError('会话已改变，请重新进入项目。')});return()=>{live.current=false;stop();unsubscribe()}},[])
 useEffect(()=>{if(!active){stop();setBusy(false)}},[active])
 const dirty=JSON.stringify(draft)!==JSON.stringify(newRunDraft())||!!file||Object.values(providerIds).some(Boolean)
 useDraftLeaveGuard(registerLeaveGuard,dirty,busy||unknown)
 useEffect(()=>{
  if(!active||!valid)return
  const c=new AbortController();controllers.current.add(c);let timer=0
  async function load(){try{
   const [abilities,uploaded,computed]=await Promise.all([client.request<Capabilities>('/capabilities',{signal:c.signal}),client.request<{items:Upload[]}>('/uploads',{signal:c.signal}),client.request<{items:CloudRun[]}>('/runs',{signal:c.signal})])
   if(c.signal.aborted||!live.current)return
   setCap(abilities);setUploads(uploaded.items);setRuns(computed.items)
   if(computed.items.some(run=>!terminal.has(run.status)))timer=window.setTimeout(()=>void load(),5000)
  }catch{if(!c.signal.aborted&&live.current)setError('云工作区读取失败，请刷新重试。')}}
  void load();return()=>{c.abort();controllers.current.delete(c);window.clearTimeout(timer)}
 },[client,active,valid,attempt])
 const enabled=!!cap?.enabled&&cap.profiles.some(profile=>profile.account_verified)&&cap.part_size===PART_SIZE
 const blocked=!active||!valid||busy||unknown
 const profile=cap?.profiles.find(item=>item.id===draft.profile_id&&item.account_verified)
 let body:ReturnType<typeof runBody>|null=null
 try{if(profile)body=runBody(draft,profile)}catch{/* Incomplete drafts remain editable. */}
 const complete=uploads.filter(upload=>upload.status==='completed')
 const rememberUpload=(upload:Upload)=>{setUploads(items=>[upload,...items.filter(item=>item.id!==upload.id)]);setUploadId(upload.id);try{sessionStorage.setItem(client.storageKey+':upload',upload.id)}catch{/* Server list remains authoritative. */}}
 async function action(work:(c:AbortController)=>Promise<void>){if(blocked||local.current)return;const c=new AbortController();local.current=c;setBusy(true);setError('');try{await work(c)}catch{if(!c.signal.aborted&&live.current)setError(client.pending?'提交结果未知，请查回原请求；不要重复提交。':'操作未完成，草稿已保留；请核对文件、参数和状态后重试。')}finally{if(local.current===c)local.current=null;if(live.current&&!c.signal.aborted){setBusy(false);setUnknown(!!client.pending);setAttempt(v=>v+1)}}}
 async function createUpload(){if(!enabled||!file||!/\.(fastq|fq)\.gz$/i.test(file.name)||file.size<=0)return;await action(async c=>{const upload=await client.create<Upload>('upload',{filename:file.name,size_bytes:file.size},c.signal);if(!c.signal.aborted){rememberUpload(upload);await transfer(file,upload,c)}})}
 async function transfer(selected:File,upload:Upload,c:AbortController){const result=await resumeUpload(selected,upload,client.request,c.signal,fetch,(part,total)=>{if(!c.signal.aborted)setProgress(`${part} / ${total} 分片已核对`)});if(!c.signal.aborted)rememberUpload(result)}
 async function lookup(){if(!active||!valid||busy||!client.pending)return;const kind=client.pending.kind,c=new AbortController();local.current=c;setBusy(true);setError('');try{const value=await client.lookup<Upload|CloudRun>(c.signal);if(!c.signal.aborted){if(kind==='upload')rememberUpload(value as Upload);else setRuns(items=>[value as CloudRun,...items.filter(item=>item.id!==value.id)]);setUnknown(false);setAttempt(v=>v+1)}}catch{if(!c.signal.aborted)setError('原请求尚未查回，请继续使用原请求身份查询，不重新提交。')}finally{if(local.current===c)local.current=null;if(live.current&&!c.signal.aborted)setBusy(false)}}
 async function download(fileId:string){await action(async c=>{const response=await apiFetch(`${projectBase(projectId)}/files/${encodeURIComponent(fileId)}/download`,{signal:c.signal});if(!response.ok)throw Error('download');const blob=await response.blob();if(c.signal.aborted)return;const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=runs.flatMap(run=>run.outputs).find(output=>output.file_id===fileId)?.filename??'cloud-output';a.click();window.setTimeout(()=>URL.revokeObjectURL(url),0)})}
 const change=<K extends keyof RunDraft>(key:K,value:RunDraft[K])=>setDraft(previous=>({...previous,[key]:value}))
 return <section className="bio-cloud-workspace" aria-label="FASTQ 云端工作区">
  <h3>FASTQ 云端计算（AWS / STARsolo）</h3>
  <p>官方文档支持、代码接入与真实运行分别核对。真实云验证未执行；账号、地域、参考与建库适用性仍需核验。</p>
  {!enabled&&<p role="status">未开通/未核验，当前阻塞上传和云分析。{cap?.blockers?.length?' 阻塞项：'+cap.blockers.join('、'):''}</p>}
  {cap&&<p>提供商：{cap.provider} · 地域：{cap.region??'未配置'} · 文档支持：{cap.evidence.documentation_supported?'是':'否'} · 代码接入：{cap.evidence.code_integrated?'是':'否'}</p>}
  {error&&<p role="alert">{error}</p>}
  <button type="button" disabled={!active||!valid||busy} onClick={()=>setAttempt(v=>v+1)}>刷新云状态</button>
  {unknown&&<p>存在结果待确认的请求。<button type="button" disabled={!active||!valid||busy} onClick={()=>void lookup()}>查回原请求</button></p>}
  <fieldset disabled={blocked||!enabled}><legend>FASTQ 分片上传与续传</legend>
   <label>本地 FASTQ<input type="file" accept=".fastq.gz,.fq.gz" onChange={e=>{setFile(e.target.files?.[0]??null);setProgress('')}}/></label>
   <p>每片 16 MiB，逐片 SHA256；刷新后重新选择原文件续传，同名同大小仍须逐片校验。上传停止不会删除原件。</p>
   <button type="button" disabled={!file||!/\.(fastq|fq)\.gz$/i.test(file.name)||file.size<=0} onClick={()=>void createUpload()}>创建上传并续传</button>
   <label>续传会话<select value={uploadId} onChange={e=>setUploadId(e.target.value)}><option value="">选择已有上传</option>{uploads.map(upload=><option key={upload.id} value={upload.id}>{upload.filename} · {statusNames[upload.status]??upload.status}</option>)}</select></label>
   <button type="button" disabled={!file||!uploadId||uploads.find(u=>u.id===uploadId)?.status==='completed'} onClick={()=>{const upload=uploads.find(u=>u.id===uploadId);if(file&&upload)void action(c=>transfer(file,upload,c))}}>继续所选上传</button>
   <button type="button" disabled={!uploadId} onClick={()=>void action(async c=>{const value=await client.request<Upload>(`/uploads/${encodeURIComponent(uploadId)}/cancel`,{...jsonRequest({}),signal:c.signal});if(!c.signal.aborted)rememberUpload(value)})}>取消所选上传</button>
  </fieldset>
  {busy&&<button type="button" onClick={()=>{local.current?.abort();local.current=null;setBusy(false);setUnknown(!!client.pending);setAttempt(v=>v+1)}}>停止本地传输/等待</button>}{progress&&<p role="status">{progress}</p>}
  <ul aria-label="已登记 FASTQ">{uploads.map(upload=><li key={upload.id}>{upload.filename} · {statusNames[upload.status]??upload.status}{upload.error_code?' · 上传存在错误，请核对后续传或取消。':''}</li>)}</ul>
  <fieldset disabled={blocked||!enabled}><legend>单样本单文库云分析</legend><p>本批支持 L001 的一对 R1/R2；不宣称完整多 lane 支持。仅使用已核验 profile。</p>
   <label>云流程<select value={draft.profile_id} onChange={e=>setDraft(previous=>({...previous,profile_id:e.target.value,chemistry:''}))}><option value="">选择流程</option>{cap?.profiles.filter(p=>p.account_verified).map(p=><option key={p.id} value={p.id}>{p.name??p.id} · {p.species} · {p.reference_id??'参考未配置'}</option>)}</select></label>
   {profile&&<p>{profile.estimated_run_cost_usd?`预计单次分析费：USD ${profile.estimated_run_cost_usd.toFixed(2)}（管理员已核实报价）`:'预计单次分析费：待核实；缺少已核实报价时服务端将阻塞提交。'}</p>}{profile&&<p>物种：{profile.species} · 引擎：{profile.engine} · 参考：{profile.reference_id}</p>}
   <label>建库 chemistry<select value={draft.chemistry} onChange={e=>change('chemistry',e.target.value)}><option value="">选择已支持的建库</option>{profile?.chemistries.map(value=><option key={value}>{value}</option>)}</select></label>
   {([['sample_id','样本 ID'],['library_id','文库 ID'],['donor_id','供者 ID'],['group','组别']] as const).map(([key,label])=><label key={key}>{label}<input value={draft[key]} onChange={e=>change(key,e.target.value)}/></label>)}
   {(['r1','r2'] as const).map((key,index)=><label key={key}>R{index+1} FASTQ<select value={draft[key]} onChange={e=>change(key,e.target.value)}><option value="">选择完成上传</option>{complete.map(upload=><option key={upload.id} value={upload.id}>{upload.filename}</option>)}</select></label>)}
   <label>预算上限（USD）<input inputMode="decimal" value={draft.budget_limit_usd} onChange={e=>change('budget_limit_usd',e.target.value)}/></label>
   <p>应用预算只校验已核实的预计单次分析费；S3、网络和日志费用另计，供应商账单没有实时硬封顶。取消请求不代表云端已取消，也不保证免费。</p>
  </fieldset>
  <p>点击提交即确认所选材料可交给该境外服务分析，并按显示报价及附加费用计费。</p>
  <button type="button" disabled={blocked||!enabled||!body||!complete.some(u=>u.id===draft.r1)||!complete.some(u=>u.id===draft.r2)} onClick={()=>{if(body&&profile)void action(async c=>{const run=await client.create<CloudRun>('run',runBody(draft,profile),c.signal);if(!c.signal.aborted){setRuns(items=>[run,...items.filter(item=>item.id!==run.id)]);setDraft(newRunDraft())}})}}>提交云分析</button>
  <h4>云运行记录</h4><p>关闭页面仅停止本地请求，后台任务继续；完成产物仍需现有矩阵导入核对与人工审核。</p>
  {runs.map(run=><article key={run.id}><h5>{run.sample_id} / {run.library_id} · {run.engine}</h5><p>{statusNames[run.status]??'待核对状态'}</p>{run.error_code&&<p role="status">云运行存在错误，需核对配置、输入或结果完整性；未自动重新付费运行。</p>}{run.cancel_requested&&<p>取消意图已记录，等待云端终态。</p>}
   {run.status==='submission_unknown'&&<fieldset disabled={blocked}><legend>查回原云提交</legend><p>请先在云控制台核对本次请求对应的运行 ID。平台会核对任务身份、流程版本和参数摘要；此操作不会重新提交付费分析。</p><label>云运行 ID<input value={providerIds[run.id]??''} maxLength={128} onChange={e=>setProviderIds(previous=>({...previous,[run.id]:e.target.value}))}/></label><button type="button" disabled={!providerIds[run.id]?.trim()} onClick={()=>void action(async c=>{const value=await reconcileRun(client,run.id,providerIds[run.id],c.signal);if(!c.signal.aborted){setRuns(items=>items.map(item=>item.id===value.id?value:item));setProviderIds(previous=>({...previous,[run.id]:''}))}})}>按云运行 ID 核对原提交</button></fieldset>}
   {canCancel(run)&&<button type="button" disabled={blocked} onClick={()=>void action(async c=>{await client.request(`/runs/${encodeURIComponent(run.id)}/cancel`,{...jsonRequest({}),signal:c.signal})})}>请求取消云运行</button>}
   {['failed','blocked','submission_unknown','collecting'].includes(run.status)&&<button type="button" disabled={blocked} onClick={()=>void action(async c=>{await client.request(`/runs/${encodeURIComponent(run.id)}/retry`,{...jsonRequest({}),signal:c.signal})})}>重试查询/取回（不重新计算）</button>}
   <ul>{run.outputs?.map(output=><li key={output.file_id}>{output.role} · {output.filename??output.file_id}{output.sha256&&<> · SHA256 {output.sha256}</>}<button type="button" disabled={blocked} onClick={()=>void download(output.file_id)}>下载 {output.filename??output.role}</button></li>)}</ul>
   {run.status==='completed'&&matrixOutputs(run.outputs)&&<button type="button" disabled={blocked} onClick={()=>{const selected=matrixOutputs(run.outputs);if(selected)onSelectMatrix(selected)}}>选择产物进入矩阵导入审核</button>}
  </article>)}
 </section>
}
