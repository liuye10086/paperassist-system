import { useEffect, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, useI18n } from '../../shared/i18n'
import { documentBase, documentRequest, isVersion, type DocumentVersion } from './documentApi'
import { isOcrPageResponse, type OcrPage as Page } from './ocrApi'
import OcrPage from './OcrPage'
import type { ReviewSource, ReviewEdit } from './ocrReviewTypes'

type Props={projectId:string;source:ReviewSource;edits:ReviewEdit[];disabled:boolean;readOnly?:boolean;refreshKey?:number;onEdit?:(block:string,edit:ReviewEdit|null)=>void;onUnavailable:()=>void}
/** Read images and immutable OCR blocks exclusively from the frozen parent paths. */
export default function OcrReviewDocument({projectId,source,edits,disabled,readOnly=false,refreshKey=0,onEdit,onUnavailable}:Props) {
 const {t}=useI18n()
 const [document,setDocument]=useState<{version:DocumentVersion;pages:Page[]}|null>(null),[page,setPage]=useState(0),[error,setError]=useState('')
 const [sessionValid,setSessionValid]=useState(true)
 const [attempt,setAttempt]=useState(0)
 const base=`${documentBase(projectId,source.file_id)}/${encodeURIComponent(source.parse_id)}`
 const {file_id:fileId,parse_id:parseId,parse_version:parseVersion,parser_version:parserVersion}=source,selectedPages=source.selected_pages.join(',')
 useEffect(()=>onApiSessionChanged(()=>{setSessionValid(false);setDocument(null)}),[])
 useEffect(()=>{
  if(!sessionValid)return
  const controller=new AbortController()
  void (async()=>{
   try {
    const physicalPages=selectedPages.split(',').map(Number)
    const version=await documentRequest(base,controller.signal,onUnavailable,(v):v is DocumentVersion=>isVersion(v,fileId)&&v.id===parseId&&v.version===parseVersion&&v.kind==='ocr_document'&&v.status==='succeeded'&&v.parser_version===parserVersion&&v.selected_pages?.join(',')===selectedPages)
    const pages=await Promise.all(physicalPages.map(async(physical,index)=>{
     const response=await documentRequest(`${base}/pages?page=${index+1}`,controller.signal,onUnavailable,(v):v is import('./ocrApi').OcrPageResponse=>isOcrPageResponse(v,index+1)&&v.total===physicalPages.length&&v.items[0].page_number===physical)
     return response.items[0]
    }))
    if(controller.signal.aborted)return
    const ids=pages.flatMap(p=>p.text_blocks.map(b=>b.id))
    if(new Set(ids).size!==ids.length||ids.length!==version.summary?.counts.text_blocks)throw new Error('核对内容读取失败，请重试。')
    setDocument({version,pages});setError('')
   }catch(cause){if(!controller.signal.aborted)setError(safeError(cause,'核对内容读取失败，请重试。'))}
  })()
  return()=>controller.abort()
 },[base,fileId,parseId,parseVersion,parserVersion,selectedPages,refreshKey,attempt,sessionValid,onUnavailable])
 if(!sessionValid)return null
 if(error)return <><p role="alert" className="error-panel">{t(error)}</p><button onClick={()=>{setError('');setAttempt(n=>n+1)}}>{t('重新读取核对原图和文字')}</button></>
 if(!document)return <p role="status">{t('正在读取核对原图和文字……')}</p>
 const shown=document.pages[page],decisions=new Map(edits.map(e=>[e.block_id,e]))
 if(edits.some(e=>!document.pages.some(p=>p.text_blocks.some(b=>b.id===e.block_id))))return <p role="alert" className="error-panel">{t('核对内容读取失败，请重试。')}</p>
 const reviewed=shown.text_blocks.filter(b=>decisions.has(b.id)).length
 return <div className="ocr-review-document">
  <p>{t('本页已核对 {reviewed} / {total} 条',{reviewed,total:shown.text_blocks.length})}</p>
  <OcrPage key={`${base}:${shown.page_number}`} page={shown} image={document.version.images?.find(i=>i.id===shown.preview_image_id)} url={`${base}/images/${encodeURIComponent(shown.preview_image_id)}`} onUnavailable={onUnavailable} renderReview={(block,index)=>{
   const edit=decisions.get(block.id)
   if(readOnly)return <div className="ocr-review-effective"><strong>{t(edit?.action==='unreadable'?'无法辨认':edit?.action==='replace_text'?'已修改文字':'已确认原文')}</strong><p>{edit?.action==='unreadable'?t('有效文字为空，未采纳识别猜测。'):edit?.action==='replace_text'?edit.text:block.text}</p></div>
   return <fieldset className="ocr-review-controls" disabled={disabled}><legend>{t('文字核对 {index}',{index})}</legend>
    <div className="ocr-review-actions">{(['accept_original','replace_text','unreadable'] as const).map(action=><label key={action}><input type="radio" name={`${base}:${block.id}`} checked={edit?.action===action} onChange={()=>onEdit?.(block.id,action==='replace_text'?{block_id:block.id,action,text:edit?.action==='replace_text'?edit.text:block.text}:{block_id:block.id,action})}/>{t(action==='accept_original'?'确认原文':action==='replace_text'?'修改文字':'无法辨认')}</label>)}</div>
    {edit?.action==='replace_text'&&<label>{t('核对文字')}<textarea rows={3} maxLength={20000} value={edit.text} onChange={e=>onEdit?.(block.id,{block_id:block.id,action:'replace_text',text:e.target.value})}/></label>}
    {edit?.action==='unreadable'&&<p className="muted">{t('有效文字为空，未采纳识别猜测。')}</p>}
    {edit&&<button type="button" className="button-quiet" onClick={()=>onEdit?.(block.id,null)}>{t('恢复为未核对')}</button>}
   </fieldset>
  }}/>
  <nav><button disabled={page===0} onClick={()=>setPage(n=>n-1)}>{t('上一张核对页')}</button><span>{page+1} / {document.pages.length}</span><button disabled={page+1>=document.pages.length} onClick={()=>setPage(n=>n+1)}>{t('下一张核对页')}</button></nav>
 </div>
}
