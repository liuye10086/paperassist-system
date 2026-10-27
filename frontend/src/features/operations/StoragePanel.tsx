import {useCallback,useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {OperationsError,operationsRequest,useOperationsRead} from './operationsApi'
import {DateValue,ReadState,Table} from './OperationsCommon'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { UsageViewTabs } from './UsageSummaryView'
import './usageViews.css'
import StorageDeletion from './StorageDeletion'
import {storageNames,type StoragePolicy,type StorageUsage,type RecoveryReceipt,type StorageInventory} from './storageTypes'
import './storage.css'
type PolicyEvent={id:string;scope_type:string;scope_id:string;revision:number;actor_user_id:string|null;reason:string;created_at:string;before_limit_bytes:number;after_limit_bytes:number;before_mode:string;after_mode:string}
export default function StoragePanel({admin,onForbidden,active=true,layered=false,registerLeaveGuard}:{admin:boolean;onForbidden:()=>void;active?:boolean;layered?:boolean;registerLeaveGuard?:RegisterLeaveGuard}){
 const{t}=useI18n(),[valid,setValid]=useState(true),[projectDraft,setProjectDraft]=useState(''),[project,setProject]=useState(''),[editor,setEditor]=useState<StoragePolicy|null>(null),[limit,setLimit]=useState(''),[mode,setMode]=useState('observe_only'),[reason,setReason]=useState(''),[error,setError]=useState(''),[pending,setPending]=useState(false),[uncertain,setUncertain]=useState(false),[scanReceipt,setScanReceipt]=useState<StorageInventory|null>(null)
 const[view,setView]=useState('overview'),[visited,setVisited]=useState<string[]>([])
 const show=(key:string)=>!layered||view===key
 const select=(key:string)=>{setView(key);setVisited(values=>values.includes(key)?values:[...values,key])}
 const dirty=valid&&!!editor&&(limit!==String(editor.limit_bytes)||mode!==editor.mode||!!reason)
 useDraftLeaveGuard(registerLeaveGuard,dirty,valid&&pending)
 const mutation=useRef<AbortController|null>(null)
 const forbidden=useCallback(()=>{mutation.current?.abort();setValid(false);setPending(false);setScanReceipt(null);setEditor(null);setReason('');setLimit('');setError('');onForbidden()},[onForbidden])
 const dataRead=useOperationsRead<StorageUsage>(admin?'/api/v1/admin/storage':'/api/v1/me/storage'+(project?'?project_id='+encodeURIComponent(project):''),forbidden,active&&valid&&(!layered||['overview','quota','inventory'].includes(view)))
 const events=useOperationsRead<{items:PolicyEvent[]}>('/api/v1/admin/storage/policy-events',forbidden,admin&&active&&valid&&(!layered||view==='audit'||view==='quota'&&uncertain))
 const recovery=useOperationsRead<RecoveryReceipt>('/api/v1/admin/storage/recovery',forbidden,admin&&active&&valid&&(!layered||view==='recovery'))
 useEffect(()=>{const stop=onApiSessionChanged(()=>{mutation.current?.abort();setValid(false);setPending(false);setScanReceipt(null);setEditor(null);setReason('');setLimit('');setProject('');setProjectDraft('');setError('');setUncertain(false)});return()=>{stop();mutation.current?.abort()}},[])
 const inventory=dataRead.data?.inventory??scanReceipt
 const data=dataRead.data, policy=editor&&data?.policies?.find(p=>p.scope_type===editor.scope_type&&p.scope_id===editor.scope_id)
 const name=(s:string|undefined)=>t(storageNames[s??'unknown']??'未知'),bytes=(n:number|null|undefined)=>n==null?t('未知'):`${n} bytes`
 const refresh=()=>{dataRead.reload();if(admin){events.reload();recovery.reload()}}
 async function mutate(scan=false){
  if(mutation.current||!valid||!scan&&(!policy||uncertain||!Number.isSafeInteger(Number(limit))||Number(limit)<0||reason.trim().length<5||reason.length>500))return
  const controller=new AbortController();mutation.current=controller;setPending(true);setError('')
  try{const result=await operationsRequest<{inventory?:StorageInventory|null}>(scan?'/api/v1/admin/storage/scan':`/api/v1/admin/storage/policies/${policy!.scope_type}/${encodeURIComponent(policy!.scope_id)}`,controller.signal,{method:scan?'POST':'PUT',headers:{'Content-Type':'application/json'},...(!scan?{body:JSON.stringify({limit_bytes:Number(limit),mode,expected_revision:policy!.revision,reason:reason.trim()})}:{})});if(controller.signal.aborted)return;if(scan)setScanReceipt(result.inventory??null);if(!scan){setEditor(null);setReason('');setUncertain(false)}refresh()}
  catch(cause){if(controller.signal.aborted)return;if(cause instanceof OperationsError&&cause.status===403){setValid(false);setPending(false);setScanReceipt(null);setEditor(null);setReason('');onForbidden();return}if(cause instanceof OperationsError&&cause.status===409){setError('配额版本已变化；草稿保留，请核对最新版本后重新提交。');refresh()}else if(!(cause instanceof OperationsError)||cause.status>=500||cause.status===408){setUncertain(!scan);refresh();setError(scan?'盘点结果未知，请刷新核对。':'配额提交结果未知；请先刷新政策和审计核对，不自动重发。')}else setError(safeError(cause,'存储操作失败，输入已保留。'))}
  finally{if(mutation.current===controller){mutation.current=null;setPending(false)}}
 }
 if(!valid)return null
 return <section className="storage-panel" hidden={!active} aria-label={t(admin?'存储治理':'本人存储')}>
  <h2>{t(admin?'存储治理':'本人存储')}</h2>
  <p>{t('统计范围为应用资产文件；数据库正文不计入资产配额。')}</p>
  <p>{t('资产、备份和历史记录默认持续保留，不自动删除。')}</p>
  {layered&&<UsageViewTabs label="存储工作视图" items={admin?[['overview','存储概览'],['quota','配额政策'],['inventory','资产盘点'],['audit','配额审计'],['recovery','恢复回执']]:[['overview','存储概览'],['deletion','受控处置']]} selected={view} onChange={select}/>}
  <div className="usage-layer" hidden={!show('overview')}>
   {!admin&&<form onSubmit={e=>{e.preventDefault();setProject(projectDraft.trim())}}><label>{t('本人项目标识（可选）')}<input value={projectDraft} onChange={e=>setProjectDraft(e.target.value)}/></label><button>{t('读取本人存储')}</button></form>}
  </div>
  {(show('overview')||show('quota')||show('inventory')||show('audit')||show('recovery'))&&<button disabled={dataRead.loading||pending} onClick={refresh}>{t('刷新存储状态')}</button>}
  {admin&&<div className="usage-layer" hidden={!show('inventory')}><button disabled={pending} onClick={()=>void mutate(true)}>{t('盘点资产（不删除）')}</button></div>}
  <div className="usage-layer" hidden={layered&&!['overview','quota','inventory'].includes(view)}><ReadState {...dataRead}/></div>
  {error&&<p role="alert">{t(error)}</p>}
  {data&&<>
   <div className="usage-layer" hidden={!show('overview')}>
    <dl className="storage-summary"><dt>{t('已用资产')}</dt><dd>{bytes(data.usage_bytes)}</dd><dt>{t('预留资产')}</dt><dd>{bytes(data.reserved_bytes)}</dd><dt>{t('配额状态')}</dt><dd>{name(data.status)}</dd></dl>
    <p>{t('未知预留：{reservations}；未知对象：{objects}',{reservations:data.unknown_reservation_count,objects:data.unknown_object_count})}</p>
    {admin&&<p>{t('无法归属的控制记录：{count}',{count:data.unattributed_intent_count??t('未知')})}</p>}
    {data.quota&&<><p>{bytes(data.usage_bytes+data.reserved_bytes)} / {bytes(data.quota.limit_bytes)}</p><p>{name(data.quota.mode)}</p><p>{t('配额修订：{revision}',{revision:data.quota.revision})}</p></>}
    <p>{t('80% 提醒；100% 在强制模式拒绝新增写入。降低配额不删除已有资料。')}</p>
    <p>{t('账本核对时间')}：<DateValue value={data.reconciled_at}/> · {name(data.reconciliation_status)}</p>
    <h3>{t('资产根所在磁盘')}</h3><p>{t('磁盘可用 / 总量 / 保护阈值')}：{bytes(data.disk.free_bytes)} / {bytes(data.disk.total_bytes)} / {bytes(data.disk.threshold_bytes)}</p>
    <p>{name(data.disk.status)} · <DateValue value={data.disk.measured_at}/></p>
    <p>{t('磁盘不足或无法测量时拒绝新增写入；现有读取继续遵循原权限。')}</p>
    <p>{t('保留策略')}：{name(data.retention_policy)} · {name(data.cleanup_status)}</p>
   </div>
   {admin&&<div className="usage-layer" hidden={!show('quota')}>
    <h3>{t('安全标识与配额')}</h3>
    <Table headers={['范围','安全标识','配额上限','模式','版本','操作']}>{data.policies?.map(p=><tr key={JSON.stringify([p.scope_type,p.scope_id])}><td>{t(p.scope_type==='user'?'用户':'项目')}</td><td>{p.scope_id}</td><td>{bytes(p.limit_bytes)}</td><td>{name(p.mode)}</td><td>{p.revision}</td><td><button disabled={pending||uncertain} onClick={()=>{setEditor(p);setLimit(String(p.limit_bytes));setMode(p.mode);setReason('');setError('')}}>{t('编辑配额 {id}',{id:p.scope_id})}</button></td></tr>)}</Table>
    {editor&&<form onSubmit={e=>{e.preventDefault();void mutate()}}><h4>{editor.scope_id}</h4><p>{t('当前修订：{revision}',{revision:policy?.revision??editor.revision})}</p>
     <label>{t('配额上限（bytes）')}<input type="number" min="0" step="1" required value={limit} disabled={pending||uncertain} onChange={e=>setLimit(e.target.value)}/></label>
     <label>{t('配额模式')}<select value={mode} disabled={pending||uncertain} onChange={e=>setMode(e.target.value)}><option value="observe_only">{name('observe_only')}</option><option value="enforced">{name('enforced')}</option></select></label>
     <label>{t('配额变更理由')}<textarea minLength={5} maxLength={500} required disabled={pending||uncertain} value={reason} onChange={e=>setReason(e.target.value)}/></label>
     <button disabled={pending||uncertain||!policy}>{t('保存配额')}</button>
     {uncertain&&<><p>{t('请核对最新政策及配额审计，再继续编辑。')}</p><button type="button" disabled={dataRead.loading||events.loading||!dataRead.data||!events.data} onClick={()=>{setUncertain(false);setError('')}}>{t('已核对政策与审计，继续编辑')}</button></>}
    </form>}
   </div>}
  </>}
  {admin&&<>
   <section className="usage-layer" hidden={!show('inventory')} aria-label={t('资产盘点')}><h3>{t('资产盘点')}</h3>
    {inventory?<><p><DateValue value={inventory.scanned_at}/> · {name(inventory.status)}</p><p>{t(inventory.coverage==='asset_files'?'覆盖：资产文件；不含数据库正文。':inventory.coverage==='not_started'?'覆盖：盘点尚未开始。':'覆盖范围未知。')}</p>{inventory.error_code==='storage_control_directory_unsafe'&&<p>{t('控制目录不安全，本次盘点未开始。')}</p>}<p>{t('盘点对象 / 字节 / 未知对象 / 未知字节 / 失败')}：{inventory.physical_object_count??t('未知')} / {bytes(inventory.physical_bytes)} / {inventory.unknown_count} / {bytes(inventory.unknown_bytes)} / {inventory.scan_failure_count}</p></>:<p>{t('尚无盘点记录；不能推断为零。')}</p>}
   </section>
   <div className="usage-layer" hidden={!show('audit')}><h3>{t('配额变更审计（最近 100 条）')}</h3><ReadState {...events}/>{events.data?.items.length===0&&<p>{t('暂无配额变更记录。')}</p>}{events.data?.items.map(e=><p key={e.id}>{e.scope_type} / {e.scope_id} · {e.actor_user_id??t('未知')} · {e.before_limit_bytes} → {e.after_limit_bytes} · {name(e.before_mode)} → {name(e.after_mode)} · {e.reason} · <DateValue value={e.created_at}/></p>)}</div>
   <div className="usage-layer" hidden={!show('recovery')}><h3>{t('备份与实际恢复结果')}</h3><ReadState {...recovery}/>{recovery.data&&<><p>{t(recovery.data.status==='available'?'恢复回执可用':'恢复回执不可用')}</p><p>{t('备份无限期保留。')}</p>{recovery.data.status==='unavailable'&&<p>{t('备份点')}：{t('未知')} · {t('实际恢复')}：{t('未知')}</p>}{recovery.data.status==='available'&&<><p>{t(recovery.data.synthetic_only?'仅合成夹具验证范围':'回执声明的验证范围')} · {recovery.data.source_schema}</p><p>{t('备份点')}：{recovery.data.backup.consistency_id??t('未知')} · {name(recovery.data.backup.status)} · <DateValue value={recovery.data.backup.finished_at}/></p><p>{t('实际恢复')}：{name(recovery.data.restore.status)} · <DateValue value={recovery.data.restore.finished_at}/> · {t('耗时（秒）')} {recovery.data.restore.duration_seconds??t('未知')} · {t('验证结果')} {name(recovery.data.restore.verification)}</p></>}</>}</div>
  </>}
  {!admin&&(!layered||visited.includes('deletion'))&&<div className="usage-layer" hidden={!show('deletion')}><StorageDeletion onForbidden={onForbidden} active={active&&show('deletion')} registerLeaveGuard={registerLeaveGuard}/></div>}
 </section>
}
