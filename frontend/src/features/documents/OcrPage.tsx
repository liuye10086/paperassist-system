import { useEffect, useRef, useState, type ReactNode } from 'react'
import { apiFetch, onApiSessionChanged } from '../../shared/api/client'
import { useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import type { ImageMetadata } from './documentApi'
import type { OcrPage as Page, OcrText } from './ocrApi'

export default function OcrPage({page,image,url,onUnavailable,renderReview}: {page:Page;image:ImageMetadata|undefined;url:string;onUnavailable:()=>void;renderReview?:(block:OcrText,index:number)=>ReactNode}) {
 const {t}=useI18n()
 const [part,setPart]=useState(0),[selected,setSelected]=useState<string|null>(null),[attempt,setAttempt]=useState(0)
 const [loaded,setLoaded]=useState<{key:string;src:string}|null>(null),[error,setError]=useState('')
 const preview=useRef<HTMLDivElement>(null)
 const requestKey=`${url}:${attempt}`
 useEffect(()=>{
  if(!image?.inline_preview || !['image/jpeg','image/png'].includes(image.mime))return
  const controller=new AbortController();let alive=true,objectUrl=''
  const timeout=window.setTimeout(()=>{if(alive){controller.abort();setError(requestKey)}},15000)
  const unsubscribe=onApiSessionChanged(()=>{controller.abort();setLoaded(null)})
  void apiFetch(url,{signal:controller.signal}).then(async response=>{
   if([401,403].includes(response.status)){onUnavailable();throw new Error('permission')}
   if(!response.ok)throw new Error('image')
   const blob=await response.blob()
   if(!alive||controller.signal.aborted)return
   if(!['image/png','image/jpeg'].includes(blob.type))throw new Error('type')
   objectUrl=URL.createObjectURL(blob);setLoaded({key:requestKey,src:objectUrl});setError('')
  }).catch(()=>{if(alive&&!controller.signal.aborted)setError(requestKey)}).finally(()=>window.clearTimeout(timeout))
  return()=>{alive=false;controller.abort();window.clearTimeout(timeout);unsubscribe();if(objectUrl)URL.revokeObjectURL(objectUrl)}
 },[url,requestKey,image,onUnavailable])
 const shown=page.text_blocks.slice(part*20,(part+1)*20)
 return <section className="ocr-page"><h5>{t('物理页 {page} · OCR 文字候选',{page:page.page_number})}</h5>
  {!renderReview&&<p className="warning-panel">{t('全部识别文字待人工核对。')}</p>}<p className="muted">{t('点击文字定位原图。预览图用于核对，请保留原件。')}</p>
  {page.text_status==='no_text'&&<p>{t('此页未识别到文字，请核对原图。')}</p>}
  {!!page.warnings.length&&<p className="warning-panel">{t('识别存在限制，请核对原图和文字。')}</p>}
  <div className="ocr-review-grid"><div ref={preview} className="ocr-preview-panel">
   {loaded?.key===requestKey&&<div className="ocr-image-overlay"><img src={loaded.src} alt={t('物理页 {page} 原图预览',{page:page.page_number})}/><svg viewBox={`0 0 ${page.width} ${page.height}`} preserveAspectRatio="none" aria-label={t('识别文字位置框')}><g>{shown.map(block=><polygon key={block.id} points={block.polygon.map(p=>p.join(',')).join(' ')} data-selected={selected===block.id} className={selected===block.id?'ocr-box-selected':'ocr-box'} />)}</g></svg></div>}
   {error===requestKey&&<><p className="error-panel" role="alert">{t('图片读取失败，请重新读取图片。')}</p><button onClick={()=>setAttempt(n=>n+1)}>{t('重新读取图片')}</button></>}
   {!image&&<p className="error-panel" role="alert">{t('识别预览图不可用，请下载原件核对。')}</p>}
   {image&&<ProjectDownloadLink href={url} filename={`page-${page.page_number}-preview.jpg`}>{t('下载核对页图')}</ProjectDownloadLink>}
  </div><div className="ocr-text-panel"><p>{t('识别文字第 {page} 页，每页最多 20 条，共 {total} 条',{page:part+1,total:page.text_blocks.length})}</p>
   {shown.map((block,index)=><article className="document-block" key={block.id}><small>{t('第 {page} 页 · 文字 {index}',{page:page.page_number,index:part*20+index+1})}{!renderReview&&<> · {t('待核对')}</>}</small><button className="ocr-text-button" aria-pressed={selected===block.id} onClick={()=>{setSelected(block.id);preview.current?.scrollIntoView?.({behavior:'smooth',block:'nearest'})}}>{block.text}</button><span className="ocr-confidence">{t('识别置信度 {score}%',{score:Math.round(block.score*100)})}{block.score<0.8&&<> · <strong>{t('较低置信度')}</strong></>}</span>{renderReview?.(block,part*20+index+1)}</article>)}
   {page.text_blocks.length>20&&<nav><button disabled={part===0} onClick={()=>{setPart(n=>n-1);setSelected(null)}}>{t('上一页 OCR 文字')}</button><span>{part+1}</span><button disabled={(part+1)*20>=page.text_blocks.length} onClick={()=>{setPart(n=>n+1);setSelected(null)}}>{t('下一页 OCR 文字')}</button></nav>}
  </div></div>
 </section>
}
