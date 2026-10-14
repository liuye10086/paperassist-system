import { useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { datasetRequest } from '../datasets/datasetApi'
import { evidenceBase, isEvidence, type Evidence, type EvidenceLocation, type EvidenceTarget, type EvidenceValue } from './evidenceApi'
import { evidenceWarnings, parserWarningLabels, evidenceLabels } from './evidenceMessages'
import './parsedEvidence.css'
type Props=EvidenceTarget & {onUnavailable?:()=>void}
export default function ParsedEvidencePanel(props:Props) {return <Panel key={`${props.projectId}:${props.fileId}:${props.kind}:${props.versionId}`} {...props}/>}
function Panel(props:Props) {
 const {t}=useI18n(); const [open,setOpen]=useState(false),[page,setPage]=useState(1),[data,setData]=useState<Evidence|null>(null),[error,setError]=useState(''),[refresh,setRefresh]=useState(0)
 const request=useRef<AbortController|null>(null); const {version}=evidenceBase(props)
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();setData(null);setOpen(false);setError('')}),[])
 useEffect(()=>{
  if(!open)return
  const controller=new AbortController();request.current=controller;let alive=true
  setData(null);setError('')
  const lost=()=>{if(alive){setData(null);setOpen(false);props.onUnavailable?.()}}
  void datasetRequest(`${version}/evidence?page=${page}`,controller,(v):v is Evidence=>isEvidence(v,props,page),lost)
   .then(v=>{if(alive&&!controller.signal.aborted)setData(v)})
   .catch(cause=>{if(alive){setData(null);setError(safeError(cause,'解析证据读取失败，请重试。'))}})
  return()=>{alive=false;controller.abort();if(request.current===controller)request.current=null}
  // Immutable source identity and page control reads.
  // oxlint-disable-next-line react-hooks/exhaustive-deps
 },[version,page,open,refresh])
 const warning=(code:string)=>t(evidenceWarnings[code]??code)
 function downloadRejected(status:number,body:unknown) {
  const code=(body as {detail?:{code?:string}})?.detail?.code
  if([401,403].includes(status)||status===404&&['project_not_found','file_not_found'].includes(code??'')) {
   request.current?.abort();setData(null);setOpen(false);props.onUnavailable?.()
  } else if([404,409,410].includes(status)){setData(null);setError('解析证据读取失败，请重试。')}
 }
 return <section className="parsed-evidence"><button aria-expanded={open} onClick={()=>setOpen(v=>!v)}>{t('解析内容与来源')}</button>
  {open&&<><h4>{t('解析内容与来源')}</h4><p className="muted">{t('存储数量不是研究样本量。')}</p>
   {error?<p role="alert">{t(error)}</p>:!data&&<p role="status">{t('正在读取解析证据……')}</p>}
   <button onClick={()=>setRefresh(n=>n+1)}>{t('重新读取解析证据')}</button>
   {data&&<><p>{data.source.filename} · v{data.source.version} · {data.format} · {data.parser_version}</p>
    <p>{t('解析范围')} · {data.scope.kind==='sheet' ? [data.scope.sheet_name,data.scope.data_range??data.scope.stored_range].filter(Boolean).join(' · ') : data.format==='docx' ? t('已保存的文档结构') : data.scope.pages.length ? data.scope.pages.map(page=>t('物理页 {page}',{page})).join(', ') : t('未记录物理页范围')}</p>
    <p>{t('解析证据第 {page} 页 · 本页 {returned} 条 · 共 {total} 条',{page:data.pagination.page,returned:data.pagination.returned,total:data.pagination.total})}</p>
    <dl>{Object.entries(data.counts).map(([name,count])=><div key={name}><dt>{t(evidenceLabels[name]??name)}</dt><dd>{count}</dd></div>)}</dl>
    <ProjectDownloadLink href={data.source.original_download_url} filename={data.source.filename} onHttpError={downloadRejected}>{t('核对原件')}</ProjectDownloadLink>{' · '}
    <ProjectDownloadLink href={data.source.object_download_url} filename={`evidence-v${data.source.version}.json`} onHttpError={downloadRejected}>{t('下载证据对象')}</ProjectDownloadLink>
    {data.source.parent_object_download_url&&<> · <ProjectDownloadLink href={data.source.parent_object_download_url} filename="raw-parent.json" onHttpError={downloadRejected}>{t('下载词法来源原始版本')}</ProjectDownloadLink></>}
    <ul className="warning-panel">{data.uncertainties.map(code=><li key={code}>{warning(code)}</li>)}</ul>
    {!!data.warnings.length&&<aside className="warning-panel"><h5>{t('已保存的解析警告')}</h5>{data.warnings.map((w,index)=><article key={index}>
     <strong>{t(parserWarningLabels[w.code]??'解析器警告')}</strong> · <code>{w.code}</code>
     <p>{t(w.scope==='document'?'文档范围警告':'物理页范围警告')}</p>
     <p>{t('记录数量：{count}',{count:w.count})}</p><pre>{w.message}</pre>
     {w.location?<LocationView format={data.format} location={w.location}/>:w.pages.map(number=><p key={number}>{t('物理页 {page}',{page:number})}</p>)}
    </article>)}</aside>}
    {data.items.map(item=><article key={item.id}><h5>{t(evidenceLabels[item.kind]??item.kind)}</h5><LocationView format={data.format} location={item.location}/>
     {item.text!==null&&<pre>{item.text}</pre>}{item.value&&<ValueView value={item.value}/>}
     {item.kind==='table'&&<p>{t('表格尺寸：{rows} 行 · {columns} 列',{rows:item.rows??0,columns:item.columns??0})}</p>}
     {item.preview_url&&<ProjectDownloadLink href={item.preview_url} filename={item.image_id??'image'} onHttpError={downloadRejected}>{t('图片对象')}</ProjectDownloadLink>}
     {item.cells.map(cell=><div key={cell.location.coordinate}><LocationView format={data.format} location={cell.location}/><ValueView value={cell.value}/></div>)}
     {item.associations.map(a=><aside key={a.caption_id}><strong>{t('说明关联候选')}</strong><pre>{a.caption_text}</pre><p>{t('关联依据')} · {t(a.basis==='adjacent_same_container'?'同容器相邻内容，仅为候选':'同页近邻位置，仅为候选')}</p><p>{t('说明来源')}</p><LocationView format={data.format} location={a.caption_source}/><p>{t('目标来源')}</p><LocationView format={data.format} location={a.target_source}/></aside>)}
     {!!item.uncertainties.length&&<ul>{item.uncertainties.map(code=><li key={code}>{warning(code)}</li>)}</ul>}
    </article>)}
    <nav><button disabled={page===1} onClick={()=>setPage(n=>n-1)}>{t('上一页证据')}</button><button disabled={!data.pagination.has_more} onClick={()=>setPage(n=>n+1)}>{t('下一页证据')}</button></nav>
   </>}
  </>}
 </section>
}
function LocationView({location:l,format}:{location:EvidenceLocation;format:Evidence['format']}) {
 const {t}=useI18n()
 return <p className="muted">{l.part} {l.path} {l.sheet_name} {l.coordinate} {l.page_number!=null&&<span>{t('物理页 {page}',{page:l.page_number})}</span>} {l.row!=null&&(l.column!=null?t('行 {row}，列 {column}',{row:l.row+(format==='docx'?1:0),column:l.column+(format==='docx'?1:0)}):t('来源行 {row}',{row:l.row+(format==='docx'?1:0)}))} {l.bbox&&`${l.coordinate_system??''} bbox ${JSON.stringify(l.bbox)}`} {l.polygon&&`${l.coordinate_system} ${JSON.stringify(l.polygon)}`}</p>
}
function ValueView({value:v}:{value:EvidenceValue}) {
 const {t}=useI18n()
 const display=(value:string|boolean|null)=>value===null?t('空值'):value===''?t('空字符串'):JSON.stringify(value)
 return <div><p>{t('读取类型与原值')} · {t(evidenceLabels[v.kind]??v.kind)}</p><pre>{display(v.typed)}</pre>{v.raw_available&&<><p>{t('原始版本读取值')}</p><pre>{display(v.original_typed)}</pre></>}<p>{t('XML 词法原值')}</p><pre>{v.raw_available?display(v.raw):t('未提供词法原值')}</pre><p>{t('单位状态')} · {t(v.unit.status==='confirmed'?'单位已确认':'单位未确认')} {v.unit.value}</p>{v.formula&&<><p>{t('公式与缓存')}</p><pre>{JSON.stringify(v.formula,null,2)}</pre><p>{t('公式缓存未核验，未执行公式。')}</p></>}</div>
}
