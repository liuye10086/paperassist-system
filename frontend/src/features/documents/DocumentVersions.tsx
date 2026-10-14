import { useCallback, useEffect, useRef, useState } from 'react'
import { safeError, useI18n, apiError } from '../../shared/i18n'
import { onApiSessionChanged } from '../../shared/api/client'
import { useDocumentVisible } from '../tasks/useDocumentVisible'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import DocumentBlock, { Properties } from './DocumentBlock'
import PdfPage, { PdfWarnings } from './PdfPage'
import OcrPage from './OcrPage'
import OcrReview from './OcrReview'
import { isPdfPageResponse, type PdfPageResponse } from './pdfApi'
import { isOcrPageResponse, parseOcrPageSelection, type OcrPageResponse } from './ocrApi'
import { documentSourceLabel } from './documentLabels'
import { documentBase, documentRequest, isBlockPage, isVersion, type DocumentPage, type DocumentVersion, type BlockPage } from './documentApi'
import './documents.css'
import ParsedEvidencePanel from '../parsedEvidence/ParsedEvidencePanel'
import FileImpactReview from '../files/FileImpactReview'
import useLifecycleSubmission from '../files/useLifecycleSubmission'

const statuses = {queued:'待执行',running:'运行中',succeeded:'已完成',failed:'执行失败'}
type Content = BlockPage | PdfPageResponse | OcrPageResponse
const kind = (v:DocumentVersion) => v.kind ?? 'docx_document'
function DocumentVersionsContent({projectId,fileId,filename,fileType,active,onUnavailable}: {
 projectId:string;fileId:string;filename:string;fileType?:'docx'|'pdf'|'png'|'jpeg';active:boolean;onUnavailable:()=>void
}) {
 const {t}=useI18n(),visible=useDocumentVisible()
 const pdf=fileType ? fileType==='pdf' : filename.toLowerCase().endsWith('.pdf')
 const image=fileType ? ['png','jpeg'].includes(fileType) : /\.(png|jpe?g)$/i.test(filename)
 const label=useCallback((value:string)=>pdf?value.replaceAll('Word','PDF'):image?value.replaceAll('Word','图片').replaceAll(' 图片','图片').replaceAll('图片 ','图片'):value,[pdf,image])
 const base=documentBase(projectId,fileId)
 const [list,setList]=useState<DocumentPage|null>(null),[page,setPage]=useState(1),[refresh,setRefresh]=useState(0)
 const [selected,setSelected]=useState<DocumentVersion|null>(null),[preview,setPreview]=useState<DocumentVersion|null>(null)
 const [content,setContent]=useState<Content|null>(null),[blockPage,setBlockPage]=useState(1)
 const [error,setError]=useState(''),[actionError,setActionError]=useState(''),[loading,setLoading]=useState(false)
 const [selection,setSelection]=useState(''),[suggestions,setSuggestions]=useState<number[]>([]),[suggesting,setSuggesting]=useState(false),[suggestionError,setSuggestionError]=useState('')
 const selectionEdited=useRef(false),suggestionVersion=useRef(''),confirmedRead=useRef(''),action=useRef<AbortController|null>(null)
 const [review,setReview]=useState<{ocr:boolean;pages:number[]|null;version:number}|null>(null)
 const submission=useLifecycleSubmission<DocumentVersion>((r,signal)=>{
  const request=JSON.parse(r.body)
  return documentRequest(r.url,signal,onUnavailable,(v):v is DocumentVersion=>isVersion(v,fileId)&&v.version===request.expected_latest_version+1&&(!r.url.endsWith('/ocr')||(v.kind==='ocr_document'&&JSON.stringify(v.selected_pages)===JSON.stringify(request.page_numbers))),{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':r.key},body:r.body})
 },()=>{setReview(null);setPage(1);setRefresh(n=>n+1)},()=>{setReview(null);setRefresh(n=>n+1)})
 const busy=submission.busy
 const validateList=useCallback((v:unknown):v is DocumentPage=>{
  const p=v as DocumentPage
  return !!p&&Array.isArray(p.items)&&p.items.every(x=>isVersion(x,fileId))&&Number.isSafeInteger(p.page)&&p.page>=1&&p.page_size===5&&Number.isSafeInteger(p.total)&&p.total>=0&&Number.isSafeInteger(p.latest_version)&&p.latest_version>=0
 },[fileId])
 const read=useCallback(async(version:DocumentVersion,page:number,signal:AbortSignal):Promise<Content>=>{
  if(kind(version)==='pdf_document')return documentRequest(`${base}/${encodeURIComponent(version.id)}/pages?page=${page}`,signal,onUnavailable,(v):v is PdfPageResponse=>isPdfPageResponse(v,page))
  if(kind(version)==='ocr_document')return documentRequest(`${base}/${encodeURIComponent(version.id)}/pages?page=${page}`,signal,onUnavailable,(v):v is OcrPageResponse=>isOcrPageResponse(v,page)&&v.items[0].page_number===version.selected_pages?.[page-1])
  return documentRequest(`${base}/${encodeURIComponent(version.id)}/blocks?page=${page}&page_size=20`,signal,onUnavailable,(v):v is BlockPage=>isBlockPage(v,page))
 },[base,onUnavailable])
 useEffect(()=>onApiSessionChanged(()=>{setList(null);setSelected(null);setPreview(null);setContent(null);setSuggestions([]);setSelection('');setReview(null);action.current?.abort()}),[])
 useEffect(()=>()=>action.current?.abort(),[])
 useEffect(()=>{
  if(!active||!visible)return
  const controller=new AbortController();let alive=true,timer=0
  const load=async()=>{
   try {
    const value=await documentRequest(`${base}?page=${page}&page_size=5`,controller.signal,onUnavailable,(v):v is DocumentPage=>validateList(v)&&v.page===page)
    if(!alive||controller.signal.aborted)return
    setList(value);setError('')
    if(value.items.some(v=>['queued','running'].includes(v.status)))timer=window.setTimeout(()=>void load(),5000)
   }catch(cause){if(alive&&!controller.signal.aborted)setError(safeError(cause,label('Word 版本读取失败，请重试。')))}
  }
  void load();return()=>{alive=false;controller.abort();window.clearTimeout(timer)}
 },[base,page,refresh,active,visible,onUnavailable,label,validateList])
 // Suggestions never restrict manual page entry or silently truncate more than ten pages.
 useEffect(()=>{
  if(!pdf||!list||!active||!visible)return
  const controller=new AbortController();let alive=true
  const load=async()=>{
   let candidate:DocumentVersion|undefined=preview&&kind(preview)==='pdf_document'?preview:list.items.filter(v=>kind(v)==='pdf_document'&&v.status==='succeeded').sort((a,b)=>b.version-a.version)[0]
   try {
    if(!candidate)for(let p=1;p<=Math.ceil(list.total/5);p++){
     if(p===list.page)continue
     const history=await documentRequest(`${base}?page=${p}&page_size=5`,controller.signal,onUnavailable,(v):v is DocumentPage=>validateList(v)&&v.page===p)
     candidate=history.items.find(v=>kind(v)==='pdf_document'&&v.status==='succeeded')
     if(candidate)break
    }
    if(!candidate||suggestionVersion.current===candidate.id)return
    setSuggesting(true);setSuggestionError('')
    const found:number[]=[],total=candidate.summary?.counts.pages??0
    for(let p=1;p<=total;p++){
     const result=await read(candidate,p,controller.signal) as PdfPageResponse
     if(result.items[0]?.text_status==='no_extractable_text')found.push(result.items[0].page_number)
    }
    if(!alive||controller.signal.aborted)return
    suggestionVersion.current=candidate.id;setSuggestions(found)
    if(!selectionEdited.current)setSelection(found.length<=10?found.join(', '):'')
   }catch(cause){if(alive&&!controller.signal.aborted)setSuggestionError(safeError(cause,'建议页读取失败，可手动输入物理页后识别。'))}
   finally{if(alive)setSuggesting(false)}
  }
  void load();return()=>{alive=false;controller.abort()}
 },[pdf,list,preview,active,visible,base,onUnavailable,validateList,read])
 async function select(version:DocumentVersion) {
  if(action.current)return
  const controller=new AbortController();action.current=controller;setLoading(true);setError('')
  try {
   const value=await documentRequest(`${base}/${encodeURIComponent(version.id)}`,controller.signal,onUnavailable,(v):v is DocumentVersion=>isVersion(v,fileId)&&v.id===version.id)
   const first=value.status==='succeeded'?await read(value,1,controller.signal):null
   if(!controller.signal.aborted){
    setSelected(value)
    if(first){confirmedRead.current=`${value.id}:1:${refresh}`;setPreview(value);setBlockPage(1);setContent(first)}
   }
  }catch(cause){if(!controller.signal.aborted)setError(safeError(cause,label('Word 版本读取失败，请重试。')))}
  finally{if(action.current===controller)action.current=null;if(!controller.signal.aborted)setLoading(false)}
 }
 useEffect(()=>{
  if(!active||!preview||preview.status!=='succeeded')return
  const readKey=`${preview.id}:${blockPage}:${refresh}`
  if(confirmedRead.current===readKey)return
  const controller=new AbortController();let alive=true
  void read(preview,blockPage,controller.signal).then(value=>{if(alive&&!controller.signal.aborted){confirmedRead.current=readKey;setContent(value);setError('')}}).catch(cause=>{if(alive&&!controller.signal.aborted)setError(safeError(cause,label('Word 正文读取失败，请重试。')))})
  return()=>{alive=false;controller.abort()}
 },[preview,blockPage,active,refresh,read,label])
 async function reparse(ocr=false) {
  if(!list||action.current||submission.busy||submission.unknown||!submission.valid||list.items.some(v=>['queued','running'].includes(v.status)))return
  const pages=ocr?parseOcrPageSelection(selection):null
  if(ocr&&!pages){setActionError('每次选择 1—10 个不重复的物理页，页码范围 1—100。');return}
  setActionError('');setReview({ocr,pages,version:list.latest_version})
 }
 const disabled=!list||busy||submission.busy||submission.unknown||!submission.valid||loading||list.items.some(v=>['queued','running'].includes(v.status))
 const pdfPages=preview&&kind(preview)==='pdf_document'?content as PdfPageResponse|null:null
 const ocrPages=preview&&kind(preview)==='ocr_document'?content as OcrPageResponse|null:null
 const blocks=preview&&kind(preview)==='docx_document'?content as BlockPage|null:null
 const selectedPages=parseOcrPageSelection(selection)??[]
 return <section className="document-versions" aria-label={t(image?'图片识别版本':label('Word 解析版本'))}>
  <h3>{t(image?'图片识别版本':label('Word 解析版本'))}</h3>
  <p className="muted">{t(pdf?'按物理页提取文字和有边框表格候选，阅读顺序及表格结构待核对。文字与表格是两种读取视图，PDF 表格不直接用于统计。请下载原件核对。':image?'图片识别提取文字候选，全部待人工核对。图片文字不直接用于统计。':'结构预览保留正文顺序，不还原 Word 分页或最终版式。Word 表格不直接用于统计分析。')}</p>
  <div className="file-actions"><button disabled={busy||loading} onClick={()=>setRefresh(n=>n+1)}>{t(label('刷新 Word 版本'))}</button><button className="button-primary" disabled={disabled} onClick={()=>void reparse()}>{t(busy?'正在提交解析……':image?'重新识别图片':pdf?'重新提取文本':label('重新解析 Word'))}</button></div>
  {pdf&&<div className="ocr-selection"><label>{t('识别物理页（1—100）')}<input type="text" value={selection} disabled={busy} onChange={e=>{selectionEdited.current=true;setSelection(e.target.value);setActionError('')}} placeholder={t('例如 1, 3, 8-10')}/></label><p className="muted">{t('每次选择 1—10 页，可选择任何物理页。识别结果只覆盖所选页，不替换文字层。')}</p>
   {suggesting&&<p role="status">{t('正在读取无文字页建议……')}</p>}{suggestionError&&<p className="warning-panel">{t(suggestionError)}</p>}
   {!!suggestions.length&&<><p>{t('建议识别无可提取文字的页：{pages}',{pages:suggestions.join(', ')})}</p>{suggestions.length>10&&<p className="warning-panel">{t('建议页超过 10 页，请勾选或输入本次最多 10 页。')}</p>}<div className="ocr-page-options">{suggestions.map(p=><label key={p}><input type="checkbox" disabled={busy} checked={selectedPages.includes(p)} onChange={e=>{selectionEdited.current=true;if(e.target.checked&&selectedPages.length>=10){setActionError('每次选择 1—10 个不重复的物理页，页码范围 1—100。');return}const next=e.target.checked?[...selectedPages,p]:selectedPages.filter(x=>x!==p);setSelection(next.sort((a,b)=>a-b).join(', '));setActionError('')}}/>{t('物理页 {page}',{page:p})}</label>)}</div></>}
   <button className="button-primary" disabled={disabled} onClick={()=>void reparse(true)}>{t('识别所选页')}</button>
  </div>}
  {review&&active&&<FileImpactReview projectId={projectId} fileId={fileId} action="reparse" operation={review.ocr?t('识别物理页：{pages}',{pages:review.pages?.join(', ')??''}):t(image?'重新识别图片':pdf?'重新提取文本':'重新解析 Word')} observedVersion={list?.latest_version} onUnavailable={onUnavailable} onCancel={()=>setReview(null)} confirmDisabled={submission.busy||submission.unknown||disabled} onConfirm={v=>void submission.submit({url:review.ocr?`${base}/ocr`:base,body:JSON.stringify({expected_latest_version:list?.latest_version??review.version,expected_assessment_revision:v.assessment_revision,...(review.ocr?{page_numbers:review.pages}:{})})})}/>}
  {submission.busy&&<p role="status">{t('正在提交解析……')}</p>}{submission.error&&<p role="alert" className="error-panel">{t(submission.error)}</p>}{submission.unknown&&submission.valid&&<button disabled={submission.busy} onClick={()=>void submission.submit()}>{t('使用同一请求确认解析结果')}</button>}
  {error&&<p className="error-panel" role="alert">{t(error)}</p>}{actionError&&<p className="error-panel" role="alert">{t(actionError)}</p>}{loading&&<p role="status">{t(label('正在读取 Word 版本……'))}</p>}
  <ul className="document-version-list">{list?.items.map(v=><li key={v.id}><button disabled={loading||busy} aria-pressed={selected?.id===v.id} onClick={()=>void select(v)}>{t(label('Word 版本 v{version}'),{version:v.version})} · {t(statuses[v.status])}</button><span>{new Date(v.created_at).toLocaleString()}</span><span>{t(kind(v)==='ocr_document'?'文字识别候选':kind(v)==='pdf_document'?'文本提取':'文档结构')}</span>{v.error&&<p className="error-panel">{t(apiError(v.error,image?'图片识别失败，请核对原文件后重试。':label('Word 解析失败，请核对原文件后重试。')))}</p>}{v.download_url&&<ProjectDownloadLink href={`${base}/${encodeURIComponent(v.id)}/download`} filename={`${filename}.v${v.version}.json`}>{t('下载结构 JSON')}</ProjectDownloadLink>}</li>)}</ul>
  {list&&list.total>5&&<nav><button disabled={page===1||busy} onClick={()=>setPage(n=>n-1)}>{t(label('上一页 Word 版本'))}</button><span>{t('第 {page} 页',{page})}</span><button disabled={page*5>=list.total||busy} onClick={()=>setPage(n=>n+1)}>{t(label('下一页 Word 版本'))}</button></nav>}
  {selected&&<div className="document-preview"><h4>{t(label('Word 版本 v{version}'),{version:selected.version})}</h4>{selected.error&&<p role="alert">{t(apiError(selected.error,image?'图片识别失败，请核对原文件后重试。':label('Word 解析失败，请核对原文件后重试。')))}</p>}
   {preview&&selected.id!==preview.id&&<p className="muted">{t('继续显示此前成功版本 v{version} 的内容。',{version:preview.version})}</p>}
   {preview&&active&&<ParsedEvidencePanel projectId={projectId} fileId={fileId} versionId={preview.id} kind="document_version" onUnavailable={onUnavailable}/>}
   {pdfPages&&preview&&<><p>{t('PDF 共 {total} 页',{total:pdfPages.total})}</p>{preview.summary&&<PdfWarnings warnings={preview.summary.warnings}/>} {pdfPages.items.map(p=><PdfPage key={`${preview.id}:${p.page_number}`} page={p}/>)}<nav><button disabled={blockPage===1} onClick={()=>setBlockPage(n=>n-1)}>{t('上一页 PDF')}</button><span>{pdfPages.page}</span><button disabled={blockPage>=pdfPages.total} onClick={()=>setBlockPage(n=>n+1)}>{t('下一页 PDF')}</button></nav></>}
   {ocrPages&&preview&&<OcrReview projectId={projectId} fileId={fileId} filename={filename} parent={preview} onUnavailable={onUnavailable}><><p>{t('本次识别物理页：{pages}（共 {total} 页）',{pages:preview.selected_pages?.join(', ')??'',total:ocrPages.total})}</p>{ocrPages.items.map(p=><OcrPage key={`${preview.id}:${p.page_number}`} page={p} image={preview.images?.find(i=>i.id===p.preview_image_id)} url={`${base}/${encodeURIComponent(preview.id)}/images/${encodeURIComponent(p.preview_image_id)}`} onUnavailable={onUnavailable}/>)}<nav><button disabled={blockPage===1} onClick={()=>setBlockPage(n=>n-1)}>{t('上一张识别页')}</button><span>{ocrPages.page} / {ocrPages.total}</span><button disabled={blockPage>=ocrPages.total} onClick={()=>setBlockPage(n=>n+1)}>{t('下一张识别页')}</button></nav></></OcrReview>}
   {blocks&&preview&&<>{preview.summary&&<><p>{t('正文 {paragraphs} 段 · 表格 {tables} 个 · 单元格 {cells} 个 · 图片 {images} 个',preview.summary.counts)}</p><ul className="warning-panel">{preview.summary.warnings.map(w=><li key={w.code}>{t(w.message)} · {w.count}</li>)}</ul></>}<p className="muted">{t('正文块第 {page} 页，每页最多 20 块，共 {total} 块',{page:blocks.page,total:blocks.total})}</p>{blocks.items.map(block=><DocumentBlock key={`${preview.id}:${block.id}`} block={block} version={preview} base={base} onUnavailable={onUnavailable}/>)}<nav><button disabled={blockPage===1} onClick={()=>setBlockPage(n=>n-1)}>{t('上一页正文')}</button><span>{blocks.page}</span><button disabled={blockPage*20>=blocks.total} onClick={()=>setBlockPage(n=>n+1)}>{t('下一页正文')}</button></nav></>}
   {!!preview?.styles?.length&&<details><summary>{t('样式概要（显式属性，不代表最终继承样式）')}</summary>{preview.styles.map(style=><article key={style.id}><h5>{style.name} · {style.type}</h5>{style.based_on&&<p>{t('继承自：{name}',{name:preview.styles?.find(s=>s.id===style.based_on)?.name??t('未解析基础样式')})}</p>}<Properties values={style.properties}/></article>)}</details>}
   {!!preview?.sections?.length&&<details><summary>{t('分节概要')}</summary>{preview.sections.map((section,i)=><article key={i}><p>{documentSourceLabel(section.source.label,t)}</p><Properties values={section.properties}/></article>)}</details>}
  </div>}
 </section>
}
export default function DocumentVersions(props:Parameters<typeof DocumentVersionsContent>[0]){return <DocumentVersionsContent key={documentBase(props.projectId,props.fileId)} {...props}/>}
