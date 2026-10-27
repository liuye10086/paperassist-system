import {useLiteratureLeaveGuard} from './literatureActivityContext'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {evidenceBase,evidencePage,validMaterial,validMaterialOptions,validMaterialContent,sourceText,locationText,type Material,type MaterialContent,type MaterialKind} from './evidenceApi'
import {useEvidenceMutation,useEvidenceResource} from './evidenceHooks'
import type {Page} from './literatureApi'
export type SelectedSource={source_kind:'abstract'|'material'|'pmc';pmc_receipt_id?:string;project_reference_id?:string;search_id?:string;material_id?:string;item_id?:string;text:string}
export function EvidencePagination({page,total,size=10,onPage,label}:{page:number;total:number;size?:number;onPage:(v:number)=>void;label:string}){const {t}=useI18n();const pages=Math.max(1,Math.ceil(total/size));return <nav className="literature-pagination" aria-label={t(label)}><span>{t('共 {total} 项 · 第 {page} / {pages} 页',{total,page,pages})}</span><button type="button" disabled={page<=1} onClick={()=>onPage(page-1)}>{t('上一页')}</button><button type="button" disabled={page>=pages} onClick={()=>onPage(page+1)}>{t('下一页')}</button></nav>}
export default function LiteratureMaterials({projectId,referenceId,onSource,onDenied}:{projectId:string;referenceId:string;onSource:(v:SelectedSource|null)=>void;onDenied:()=>void}){
 const {t}=useI18n(),base=evidenceBase(projectId);const [revision,setRevision]=useState(0),[optionPage,setOptionPage]=useState(1),[page,setPage]=useState(1),[sourcePage,setSourcePage]=useState(1)
 const [fileId,setFileId]=useState(''),[versionId,setVersionId]=useState(''),[description,setDescription]=useState(''),[note,setNote]=useState(''),[materialId,setMaterialId]=useState('')
 const formSignature=JSON.stringify([fileId,versionId,description,note]),[savedForm,setSavedForm]=useState(JSON.stringify(['','','','']));useLiteratureLeaveGuard(formSignature!==savedForm,false)
 const options=useEvidenceResource(`${base}/material-options?page=${optionPage}`,v=>validMaterialOptions(v,projectId,optionPage),revision,onDenied)
 const materials=useEvidenceResource<Page<Material>>(referenceId?`${base}/materials?project_reference_id=${encodeURIComponent(referenceId)}&page=${page}`:null,v=>evidencePage(v,projectId,page,validMaterial),revision,onDenied)
 const material=materials.data?.items.find(m=>m.id===materialId)
 const source=useEvidenceResource<MaterialContent>(material?`${base}/materials/${encodeURIComponent(material.id)}/source?page=${sourcePage}`:null,(v):v is MaterialContent=>validMaterialContent(v,sourcePage)&&v.source.file_id===material?.source.file_id&&v.source.version_id===material?.source.version_id&&v.source.sha256===material?.source.sha256,revision,onDenied)
 const mutate=useEvidenceMutation(onDenied),file=options.data?.items.find(f=>f.file_id===fileId),version=file?.versions.find(v=>v.version_id===versionId)
 async function link(){if(!referenceId||!file||!version||!description.trim()||!note.trim())return
 const saved=await mutate.post(`${base}/materials`,{project_reference_id:referenceId,file_id:file.file_id,source_kind:version.kind as MaterialKind,version_id:version.version_id,source_description:description,match_note:note},validMaterial)
 if(saved){setSavedForm(formSignature);setRevision(r=>r+1);setMaterialId(saved.id);setSourcePage(1);onSource(null)}
 }
 return <section className="literature-panel" aria-label={t('用户全文与解析材料')}><h4>{t('用户全文与解析材料')}</h4><p className="muted">{t('选择项目已有文件版本，并人工确认与书目对应；文件和用户原文保持原样。')}</p>
 {options.error&&<p role="alert">{t(options.error)}</p>}{materials.error&&<p role="alert">{t(materials.error)}</p>}{mutate.error&&<p role="alert">{t(mutate.error)}</p>}
 <fieldset disabled={mutate.busy}><legend>{t('关联材料')}</legend><label>{t('项目文件')}<select value={fileId} onChange={e=>{setFileId(e.target.value);setVersionId('')}}><option value="">{t('请选择文件')}</option>{options.data?.items.map(f=><option key={f.file_id} value={f.file_id}>{f.filename}</option>)}</select></label>
 {options.data&&<EvidencePagination page={optionPage} total={options.data.total} label="文件选项分页" onPage={p=>{setOptionPage(p);setFileId('');setVersionId('')}}/>}
 <label>{t('解析或 OCR 核对版本')}<select value={versionId} onChange={e=>setVersionId(e.target.value)}><option value="">{t('请选择版本')}</option>{file?.versions.map(v=><option key={v.version_id} value={v.version_id}>{t(v.kind==='ocr_review_version'?'OCR 人工核对':'文件解析')} · {v.version} · {v.label}</option>)}</select></label>
 <label>{t('来源说明')}<input value={description} maxLength={2000} onChange={e=>setDescription(e.target.value)}/></label><label>{t('书目对应确认')}<textarea required maxLength={2000} value={note} onChange={e=>setNote(e.target.value)}/></label>
 <button type="button" disabled={!referenceId||!version||!description.trim()||!note.trim()} onClick={()=>void link()}>{t('关联所选材料')}</button></fieldset>
 {materials.data&&<><label>{t('已关联材料')}<select value={materialId} onChange={e=>{setMaterialId(e.target.value);setSourcePage(1);onSource(null)}}><option value="">{t('请选择材料')}</option>{materials.data.items.map(m=><option key={m.id} value={m.id}>{m.source.filename} · {t('版本')} {m.source.version} · {m.source_description}</option>)}</select></label><EvidencePagination page={page} total={materials.data.total} label="材料分页" onPage={p=>{setPage(p);setMaterialId('');onSource(null)}}/></>}
 {source.loading&&<p role="status">{t('正在读取来源……')}</p>}{source.error&&<p role="alert">{t(source.error)}</p>}{source.data&&<><ProjectDownloadLink href={`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(source.data.source.file_id??'')}/download`} filename={source.data.source.filename??'original'}>{t('下载原始文件')}</ProjectDownloadLink><p>{source.data.source.filename} · {t('版本')} {source.data.source.version}</p><ul className="literature-evidence-items">{source.data.items.map(item=><li key={item.id}><p className="muted">{locationText(item.location)}</p><p className="literature-original">{sourceText(item)||t('此条目没有可摘录文本')}</p>{item.uncertainties?.length? <p className="warning-panel">{t('此来源含解析或核对不确定项，请查看原件。')}</p>:null}<button type="button" disabled={!sourceText(item)} onClick={()=>onSource({source_kind:'material',material_id:materialId,item_id:item.id,text:sourceText(item)})}>{t('从此条目摘录')}</button></li>)}</ul><EvidencePagination page={sourcePage} total={source.data.total} size={20} label="材料来源分页" onPage={p=>{setSourcePage(p);onSource(null)}}/></>}
 </section>
}
