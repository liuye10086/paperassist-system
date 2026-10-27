import { useEffect, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { documentRequest } from './documentApi'
import { isReviewDetail, isReviewPage, reviewVersionsBase, type ReviewDetail, type ReviewPage } from './ocrReviewApi'
import OcrReviewDocument from './OcrReviewDocument'

export default function OcrReviewHistory({projectId,fileId,parseId,filename,refreshKey,onUnavailable,active=true}:{projectId:string;fileId:string;parseId:string;filename:string;refreshKey:number;onUnavailable:()=>void;active?:boolean}) {
 const {t}=useI18n()
 const [list,setList]=useState<ReviewPage|null>(null),[page,setPage]=useState(1),[selected,setSelected]=useState(''),[detail,setDetail]=useState<ReviewDetail|null>(null),[error,setError]=useState(''),[sessionValid,setSessionValid]=useState(true)
 const [detailAttempt,setDetailAttempt]=useState(0)
 const base=reviewVersionsBase(projectId,fileId)
 useEffect(()=>onApiSessionChanged(()=>{setSessionValid(false);setList(null);setDetail(null);setSelected('')}),[])
 useEffect(()=>{
  if(!sessionValid||!active)return
  const controller=new AbortController()
  void documentRequest(`${base}?parse_id=${encodeURIComponent(parseId)}&page=${page}&page_size=5`,controller.signal,onUnavailable,(v):v is ReviewPage=>isReviewPage(v,projectId,fileId,parseId,page)).then(value=>{if(!controller.signal.aborted){const last=Math.max(1,Math.ceil(value.total/5));if(page>last){setPage(last);return}setList(value);setError('')}}).catch(cause=>{if(!controller.signal.aborted)setError(safeError(cause,'核对历史读取失败，请重试。'))})
  return()=>controller.abort()
 },[base,projectId,fileId,parseId,page,refreshKey,sessionValid,active,onUnavailable])
 useEffect(()=>{
  if(!selected||!sessionValid||!active)return
  const controller=new AbortController()
  void documentRequest(`${base}/${encodeURIComponent(selected)}`,controller.signal,onUnavailable,(v):v is ReviewDetail=>isReviewDetail(v,projectId,fileId,parseId,selected)).then(value=>{if(!controller.signal.aborted){setDetail(value);setError('')}}).catch(cause=>{if(!controller.signal.aborted)setError(safeError(cause,'核对历史读取失败，请重试。'))})
  return()=>controller.abort()
 },[base,projectId,fileId,parseId,selected,detailAttempt,sessionValid,active,onUnavailable])
 if(!sessionValid)return null
 return <section className="ocr-review-history" aria-label={t('核对历史版本')}><h4>{t('核对历史版本')}</h4>
  {error&&<p role="alert" className="error-panel">{t(error)}</p>}
  {list?.total===0&&<p className="muted">{t('暂无已生成核对版本。')}</p>}
  <ul className="document-version-list">{list?.items.map(version=><li key={version.id}><button onClick={()=>{if(selected===version.id&&detail)return;setDetail(null);setSelected(version.id);setDetailAttempt(n=>n+1)}}>{t('查看核对版本 v{version}',{version:version.version})}</button><span>{new Date(version.created_at).toLocaleString()}</span><span>{t('来源识别版本 v{version}',{version:version.parent_parse_version})}</span><ProjectDownloadLink href={version.download_url} filename={`${filename}.review-v${version.version}.json`}>{t('下载此核对版本')}</ProjectDownloadLink></li>)}</ul>
  {list&&list.total>5&&<nav><button disabled={page===1} onClick={()=>{setList(null);setPage(n=>n-1)}}>{t('上一页核对版本')}</button><span>{page}</span><button disabled={page*5>=list.total} onClick={()=>{setList(null);setPage(n=>n+1)}}>{t('下一页核对版本')}</button></nav>}
  {detail&&<div className="ocr-review-history-detail"><h5>{t('核对版本 v{version} · 只读',{version:detail.version})}</h5><button onClick={()=>{setSelected('');setDetail(null)}}>{t('关闭历史预览')}</button><p>{t('确认原文 {accepted} 条 · 修改 {corrected} 条 · 无法辨认 {unreadable} 条',{accepted:detail.summary.accepted_blocks,corrected:detail.summary.corrected_blocks,unreadable:detail.summary.unreadable_blocks})}</p><p className="warning-panel">{t('人工核对仅确认原图转录，不代表研究事实、单位、数字或统计结论已验证。')}</p><ProjectDownloadLink href={detail.download_url} filename={`${filename}.review-v${detail.version}.json`}>{t('下载核对版本 JSON')}</ProjectDownloadLink><OcrReviewDocument key={detail.id} projectId={projectId} source={detail.source} edits={detail.edits} readOnly disabled onUnavailable={onUnavailable}/></div>}
 </section>
}
