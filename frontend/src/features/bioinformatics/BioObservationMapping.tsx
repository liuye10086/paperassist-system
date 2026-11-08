import {forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react'
import {useI18n,safeError} from '../../shared/i18n'
import {onApiSessionChanged} from '../../shared/api/client'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {bioRequest,projectBase,jsonRequest} from './api'
import {BioJson,BioWriteStatus} from './BioSpatialShared'
import type {BioMap,MappingRow,RawBioSource} from './spatialContracts'
import useBioWrite from './useBioWrite'
import useResearchDraft from '../research-results/useResearchDraft'
import {savedContent} from '../../shared/savedContent'
const fields=['sample_id','section','donor','batch','group'] as const
const labels={sample_id:'样本',section:'切片',donor:'供体',batch:'批次',group:'分组'}
const emptyRow=():MappingRow=>({barcode:'',sample_id:{status:'pending',value:null},section:{status:'pending',value:null},donor:{status:'pending',value:null},batch:{status:'pending',value:null},group:{status:'pending',value:null}})
type TableSource={file_id:string;sha256:string;sheet:number|string;mapping:Record<string,string>}
type Preview={table_source:TableSource;source:{file_id:string;sha256:string;sheet_name?:string};headers:string[];preview_rows:MappingRow[];total:number;valid:boolean;errors:{row:number;code:string;message:string}[];counts:{mapped:number;unmapped:number;total:number}}
export type MappingPreparation={ensureSaved:()=>Promise<string|null|undefined>}
type MapDetails={id:string;setId:string;retainDraft?:boolean}
type MappingProps={disabled?:boolean;projectId:string;source:RawBioSource;designVersionId:string|null;currentVersionId:string|null;currentSetId?:string|null;onSaved:(v:BioMap)=>void;registerLeaveGuard?:RegisterLeaveGuard}
const BioObservationMapping=forwardRef<MappingPreparation,MappingProps>(function BioObservationMapping({disabled=false,projectId,source,designVersionId,currentVersionId,currentSetId,onSaved,registerLeaveGuard},ref){
 const {t}=useI18n(),base=projectBase(projectId);const [rows,setRows]=useState<MappingRow[]>([]),[saved,setSaved]=useState<BioMap|null>(null),[dirty,setDirty]=useState(false),[files,setFiles]=useState<{id:string;filename:string}[]>([]),[fileId,setFileId]=useState(''),[sheet,setSheet]=useState('0'),[columns,setColumns]=useState<Record<string,string>>({barcode:'barcode'}),[preview,setPreview]=useState<Preview|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[page,setPage]=useState(1),[valid,setValid]=useState(true),[tableSource,setTableSource]=useState<TableSource|null>(null),[allLoaded,setAllLoaded]=useState(true)
 const [recovery,setRecovery]=useResearchDraft<MapDetails|null>(projectId,`mapping-result:${source.dataset_id}:${source.dataset_version_id}`,()=>null)
 const request=useRef<AbortController|null>(null),alive=useRef(true),recovering=useRef<MapDetails|null>(recovery),completeSaved=useRef<{id:string;content:string}|null>(null)
 const [draftHead,setDraftHead]=useState(currentVersionId)
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort()}},[])
 useEffect(()=>onApiSessionChanged(()=>{alive.current=false;request.current?.abort();setValid(false);setRows([]);setPreview(null);setFiles([])}),[])
 const mapContent=(mapRows:MappingRow[],raw:RawBioSource,design:string|null)=>savedContent({rows:mapRows,raw_source:raw,design_version_id:design})
 const rememberComplete=(v:BioMap,mapRows:MappingRow[])=>{completeSaved.current=mapRows.length===v.total?{id:v.id,content:mapContent(mapRows,v.raw_source,v.design_version_id??null)}:null}
 const accept=(v:BioMap)=>{if(!alive.current)return;rememberComplete(v,v.rows);setSaved(v);setRows(rows.length===v.total?rows:v.rows);setAllLoaded(rows.length===v.total||v.rows.length===v.total);setTableSource(null);setDraftHead(v.id);setDirty(false);onSaved(v)}
 const writer=useBioWrite<BioMap>(projectId,'map',accept,v=>{void readDetails({id:v.id,setId:v.root_id!})})
 useDraftLeaveGuard(registerLeaveGuard,dirty,busy||writer.busy||writer.unknown||!!recovery)
 async function chooseFile(){const c=new AbortController();request.current=c;setBusy(true);setError('');try{const v=await bioRequest<{id:string;filename:string}[]>(`${base}/files`,{signal:c.signal});if(alive.current&&!c.signal.aborted)setFiles(v)}catch(cause){if(alive.current&&!c.signal.aborted)setError(safeError(cause,'映射读取失败，请重试。'))}finally{if(alive.current)setBusy(false);if(request.current===c)request.current=null}}
 async function inspect(){if(!fileId||busy||!valid)return;const c=new AbortController();request.current=c;setBusy(true);setError('');setPreview(null);try{const v=await bioRequest<Preview>(`${base}/bio-observation-map-table-previews`,{...jsonRequest({raw_source:source,file_id:fileId,sheet:/^\d+$/.test(sheet)?Number(sheet):sheet,mapping:Object.fromEntries(Object.entries(columns).filter(([,v])=>v.trim())),design_version_id:designVersionId}),signal:c.signal});if(alive.current&&!c.signal.aborted)setPreview(v)}catch(cause){if(alive.current&&!c.signal.aborted)setError(safeError(cause,'映射预览失败，请核对列名。'))}finally{if(alive.current)setBusy(false);if(request.current===c)request.current=null}}
 async function loadFixed(){const targetSet=saved?.set_id??currentSetId,targetVersion=saved?.id??currentVersionId;if(!targetSet||!targetVersion||busy||!valid)return;const c=new AbortController();request.current=c;setBusy(true);setError('');try{let all:MappingRow[]=[],p=1,first:BioMap|null=null;do{const value:BioMap=await bioRequest<BioMap>(`${base}/bio-observation-maps/${encodeURIComponent(targetSet)}/versions/${encodeURIComponent(targetVersion)}?page=${p}&page_size=50`,{signal:c.signal});if(!alive.current||c.signal.aborted)return;if(value.id!==targetVersion||value.set_id!==targetSet||value.raw_source.project_id!==projectId||value.raw_source.dataset_version_id!==source.dataset_version_id||!Array.isArray(value.rows)||value.rows.length===0&&all.length<value.total)throw Error('format');first??=value;all=[...all,...value.rows];if(all.length>20000)throw Error('limit');p++}while(all.length<first!.total);if(alive.current&&!c.signal.aborted){rememberComplete(first!,all);setDraftHead(targetVersion);setSaved(first);setRows(all);setAllLoaded(true);setDirty(false);setPage(1)}}catch(cause){if(alive.current&&!c.signal.aborted)setError(safeError(cause,'映射读取失败，请重试。'))}finally{if(alive.current)setBusy(false);if(request.current===c)request.current=null}}
 const mapConflict=dirty&&draftHead!==currentVersionId
 useEffect(()=>{
  if(!dirty&&draftHead!==currentVersionId){setSaved(null);setRows([]);setTableSource(null);setAllLoaded(true);setDraftHead(currentVersionId)}
 },[currentVersionId,dirty,draftHead])
 async function readDetails(target:MapDetails){
  if(!alive.current)return
  recovering.current=target;setRecovery(target);if(request.current)return
  setBusy(true);setError('')
  const controller=new AbortController();request.current=controller
  try{
   const value=await bioRequest<BioMap>(`${base}/bio-observation-maps/${encodeURIComponent(target.setId)}/versions/${encodeURIComponent(target.id)}`,{signal:controller.signal})
   if(!alive.current||controller.signal.aborted)return
   if(value.id!==target.id||value.set_id!==target.setId||value.raw_source.project_id!==projectId||value.raw_source.dataset_id!==source.dataset_id||value.raw_source.dataset_version_id!==source.dataset_version_id||value.raw_source.manifest_sha256!==source.manifest_sha256||!Array.isArray(value.rows))throw Error('format')
   if(target.retainDraft){rememberComplete(value,value.rows);setSaved(value);setDraftHead(target.id)}else accept(value)
   recovering.current=null;setRecovery(null)
  }catch(cause){if(alive.current&&!controller.signal.aborted)setError(safeError(cause,'映射读取失败，请重试。'))}finally{if(request.current===controller)request.current=null;if(alive.current)setBusy(false)}
 }
 function adoptCurrent(){
  request.current?.abort();request.current=null;recovering.current=null;setRecovery(null);setSaved(null);setRows([]);setTableSource(null);setAllLoaded(true);setDraftHead(currentVersionId);setDirty(false);setError('')
 }
 function keepLocal(){
  if(!currentVersionId){setSaved(null);setDraftHead(null);return}
  if(currentSetId)void readDetails({id:currentVersionId,setId:currentSetId,retainDraft:true})
 }
 async function ensureSaved(){
  if(!valid||busy||writer.busy||writer.unknown||writer.completed||!writer.valid||recovering.current||mapConflict)return undefined
  if(!dirty)return currentVersionId
  if(!allLoaded||!rows.length&&!tableSource)return undefined
  if(!tableSource&&completeSaved.current?.id===currentVersionId&&completeSaved.current.content===mapContent(rows,source,designVersionId)){setDirty(false);return currentVersionId}
  const value=await writer.submit(saved?`${base}/bio-observation-maps/${encodeURIComponent(saved.set_id)}/versions`:`${base}/bio-observation-maps`,{name:'Observation mapping',raw_source:source,expected_revision:saved?.revision??0,design_version_id:designVersionId,rows,...(tableSource?{table_source:tableSource}:{})},{notifySaved:false})
  if(!value||!alive.current)return undefined
  accept(value);return value.id
 }
 useImperativeHandle(ref,()=>({ensureSaved}))
 const actionBlocked=disabled||!valid||!writer.valid||busy||writer.busy||writer.unknown||writer.completed
 const blocked=actionBlocked||!!recovery||mapConflict
 return <section className="bio-mapping"><h3>{t('样本与条码对应')}</h3>{mapConflict&&<div className="warning-panel"><p>{t('样本对应关系已更新，本地修改已保留，请选择要使用的内容。')}</p><button type="button" disabled={actionBlocked} onClick={adoptCurrent}>{t('采用已保存的对应关系')}</button><p>{t('采用已保存的对应关系会替换本地映射草稿。')}</p><button type="button" disabled={actionBlocked||!!currentVersionId&&!currentSetId} onClick={keepLocal}>{t('保留本地修改')}</button></div>}{recovery&&<button type="button" disabled={actionBlocked} onClick={()=>void readDetails(recovery)}>{t('重新核对样本对应关系')}</button>}<p>{t('未填写的供体、切片和重复关系保持待确认；不会从条码自动推断。')}</p>{currentVersionId&&<p>{t('固定映射版本')} {t('已固定')}{currentSetId&&<button type="button" disabled={blocked} onClick={()=>{if(!dirty||window.confirm(t('当前项目有未保存的修改。离开并放弃这些修改？')))void loadFixed()}}>{t('读取已保存映射用于编辑')}</button>}</p>}{saved&&<p>{t('映射已保存')} · {saved.counts.mapped}/{saved.counts.total} · {t('未映射')} {saved.counts.unmapped}</p>}
 <section className="analysis-detail"><h3>{t('从同项目表格预览映射')}</h3><button type="button" disabled={blocked} onClick={()=>void chooseFile()}>{t('读取映射来源文件')}</button><fieldset disabled={blocked}><label>{t('映射来源文件')}<select value={fileId} onChange={e=>{setFileId(e.target.value);setPreview(null)}}><option value="">{t('请选择文件')}</option>{files.map(f=><option key={f.id} value={f.id}>{f.filename}</option>)}</select></label><label>{t('工作表名称或索引')}<input value={sheet} onChange={e=>{setSheet(e.target.value);setPreview(null)}}/></label>{['barcode',...fields].map(k=><label key={k}>{t(k==='barcode'?'条码列':labels[k as typeof fields[number]]+'列')}<input value={columns[k]??''} onChange={e=>{setColumns({...columns,[k]:e.target.value});setPreview(null)}}/></label>)}<button type="button" disabled={!fileId} onClick={()=>void inspect()}>{t('只读验证表格映射')}</button></fieldset>{preview&&<><p>{t('有效映射预览')} · {preview.total} · {preview.valid?t('验证通过'):t('存在错误')}</p><section className="customer-advanced-details"><h4>{t('查看映射预览')}</h4><BioJson value={preview.preview_rows}/></section>{preview.errors.map((e,i)=><p role="alert" key={i}>{t('第 {row} 行：{message}',{row:e.row,message:e.message||'请核对列名和内容。'})}</p>)}<button type="button" disabled={blocked||!preview.valid} onClick={()=>{setTableSource(preview.table_source);setRows([]);setAllLoaded(true);setDirty(true);setPage(1)}}>{t('明确应用已验证映射到草稿')}</button></>}</section>
 {tableSource&&<><p>{t('已应用完整表格来源；预览行不会作为完整映射保存。')}</p><section className="customer-advanced-details"><h4>{t('查看来源核对详情')}</h4><BioJson value={tableSource}/></section><button type="button" disabled={blocked} onClick={()=>{setTableSource(null);setRows([]);setAllLoaded(true);setDirty(true)}}>{t('改为手工映射（清除表格来源）')}</button></>}{saved&&!allLoaded&&<button type="button" disabled={blocked} onClick={()=>void loadFixed()}>{t('读取已保存映射用于编辑')}</button>}<fieldset disabled={blocked||!!tableSource||!!saved&&!allLoaded}><legend>{t('条码映射草稿')}</legend>{rows.slice((page-1)*20,page*20).map((r,index)=>{const i=(page-1)*20+index;return <div className="bio-mapping-row" key={i}><label>{t('条码 {number}',{number:i+1})}<input value={r.barcode} onChange={e=>{setRows(rows.map((v,n)=>n===i?{...v,barcode:e.target.value}:v));setDirty(true)}}/></label>{fields.map(key=><label key={key}>{t(labels[key])}<select aria-label={t('{field}状态 {number}',{field:t(labels[key]),number:i+1})} value={r[key].status} onChange={e=>{setRows(rows.map((v,n)=>n===i?{...v,[key]:{status:e.target.value,value:null}}:v));setDirty(true)}}><option value="pending">{t('待确认')}</option><option value="known">{t('已知')}</option><option value="not_applicable">{t('不适用')}</option></select>{r[key].status==='known'&&<input aria-label={t('{field}值 {number}',{field:t(labels[key]),number:i+1})} value={r[key].value??''} onChange={e=>{setRows(rows.map((v,n)=>n===i?{...v,[key]:{...v[key],value:e.target.value}}:v));setDirty(true)}}/>}</label>)}<button type="button" onClick={()=>{setRows(rows.filter((_,n)=>i!==n));setDirty(true)}}>{t('移除此对应')}</button></div>})}<button type="button" onClick={()=>{setRows([...rows,emptyRow()]);setDirty(true);setPage(Math.floor(rows.length/20)+1)}}>{t('添加条码对应')}</button><div><button type="button" disabled={page===1} onClick={()=>setPage(p=>p-1)}>{t('上一页')}</button><button type="button" disabled={page*20>=rows.length} onClick={()=>setPage(p=>p+1)}>{t('下一页')}</button></div></fieldset><button type="button" disabled={blocked||!allLoaded||!dirty||!rows.length&&!tableSource} onClick={()=>void ensureSaved()}>{t('保存映射')}</button>{error&&<p role="alert">{t(error)}</p>}<BioWriteStatus writer={writer}/></section>
})
export default BioObservationMapping
