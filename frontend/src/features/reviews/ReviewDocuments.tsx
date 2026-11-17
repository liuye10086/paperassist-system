import {useReviewDraftGuard} from './reviewActivityContext'
import type {ReviewView} from '../projects/reviewViews'
import FixedEvidenceDetails,{FixedChangeValue} from './FixedEvidenceDetails'
import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react'
import {apiError,useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {locationText,object,reviewBase,revisionHash,type Revision} from './revisionTypes'
import {validReviewDocument,validDocumentExport,type ReviewDocument,type DocumentExport} from './documentTypes'
import {roles,type DocumentDefaults} from './reviewTypes'
import {useReviewRequest} from './useReviewRequest'
import {customerChangeText,customerReviewLocation} from './customerReviewDisplay'
type Props={selectedItemId?:string;onSelectItem?:(id:string)=>void;view?:ReviewView;onSelectDocument?:(id:string,automatic?:boolean)=>void;customer?:boolean;evidenceNames?:ReadonlyMap<string,string>;projectId:string;revision:Revision;projectType:'sci'|'thesis';outputLanguage:'zh-CN'|'en';active:boolean;onOpenTask:(id:string)=>void;initialDocument?:string;documentDefaults?:DocumentDefaults}
export default function ReviewDocuments(props:Props){return <Documents key={`${props.projectId}:${props.revision.id}`} {...props}/>}
function Documents({selectedItemId,onSelectItem,view,onSelectDocument,projectId,revision,projectType,outputLanguage,active,onOpenTask,initialDocument,documentDefaults,customer=false,evidenceNames}:Props){
 const {t,locale}=useI18n(),visible=useDocumentVisible(),{request,run,available,busy,error,setError}=useReviewRequest(),base=reviewBase(projectId)
 const [documents,setDocuments]=useState<ReviewDocument[]>([]),[selectedId,setSelectedId]=useState(initialDocument??''),[draft,setDraft]=useState<{item_id:string;text:string}[]>([]),[languages,setLanguages]=useState<Record<string,''|'zh-CN'|'en'>>({}),[editLanguage,setEditLanguage]=useState(outputLanguage),[refresh,setRefresh]=useState(0),[exports,setExports]=useState<DocumentExport[]>([])
 const kind=view==='comparison'?'comparison':view==='response'?'reply':null
 const language=languages[kind??'all']??'',setLanguage=(value:''|'zh-CN'|'en')=>setLanguages(old=>({...old,[kind??'all']:value}))
 const documentDrafts=useRef(new Map<string,{draft:{item_id:string;text:string}[];language:'zh-CN'|'en';dirty:boolean}>()),selection=useRef(selectedId),activity=useRef(active),routeKind=useRef(kind);useLayoutEffect(()=>{selection.current=selectedId;activity.current=active;routeKind.current=kind},[selectedId,active,kind])
 const dirty=useRef(false),loaded=useRef(''),shownDocuments=documents.filter(d=>!kind||d.kind===kind),current=shownDocuments.find(d=>d.id===selectedId)??(!selectedId?shownDocuments[0]:undefined)
 const [appliedDocument,setAppliedDocument]=useState(initialDocument)
 if(initialDocument!==appliedDocument){setAppliedDocument(initialDocument);if(initialDocument||customer)setSelectedId(initialDocument??'')}
 const [localItem,setLocalItem]=useState(''),reportedItem=useRef('')
 const chosenItemId=selectedItemId||(current?.snapshot.items.some(i=>i.item_id===localItem)?localItem:current?.snapshot.items[0]?.item_id??'')
 useEffect(()=>{const key=`${current?.id}:${chosenItemId}`;if(!customer&&view&&active&&!selectedItemId&&chosenItemId&&reportedItem.current!==key){reportedItem.current=key;onSelectItem?.(chosenItemId)}},[customer,view,active,selectedItemId,chosenItemId,current?.id,onSelectItem])
 const valid=(v:unknown):v is ReviewDocument=>validReviewDocument(v,projectId,revision.id)
 const editor=useRef({draft,language:editLanguage}),initialApplied=useRef<string|undefined>(undefined),[savedDraftDirty,setSavedDraftDirty]=useState(false)
 useLayoutEffect(()=>{editor.current={draft,language:editLanguage}},[draft,editLanguage])
 const select=useCallback((d:ReviewDocument,report=true,automatic=false)=>{if(loaded.current)documentDrafts.current.set(loaded.current,{...editor.current,dirty:dirty.current});const saved=documentDrafts.current.get(d.id);setSelectedId(d.id);setDraft(saved?.draft??d.snapshot.items.map(i=>({item_id:i.item_id,text:i.text})));setEditLanguage(saved?.language??d.language);dirty.current=saved?.dirty??false;loaded.current=d.id;setSavedDraftDirty(Array.from(documentDrafts.current.entries()).some(([id,s])=>id!==d.id&&s.dirty));if(report){if(customer&&automatic)onSelectDocument?.(d.id,true);else onSelectDocument?.(d.id)}},[customer,onSelectDocument])
 // Synchronize an external fixed-document route after its immutable snapshot is available.
 // oxlint-disable-next-line react/set-state-in-effect
 useEffect(()=>{if(initialDocument!==initialApplied.current){initialApplied.current=initialDocument;if(initialDocument){const target=documents.find(d=>d.id===initialDocument&&(!kind||d.kind===kind));if(target)select(target,false);return}}if(initialDocument)return;const chosen=documents.find(d=>d.id===selection.current),target=kind&&chosen?.kind!==kind?documents.find(d=>d.kind===kind):undefined;if(target)select(target,activity.current,true)},[initialDocument,kind,documents,select])


 useEffect(()=>{if(!active||!visible||!available)return;let live=true;void request(base+'/revisions/'+encodeURIComponent(revision.id)+'/documents',(v):v is {items:ReviewDocument[]}=>object(v)&&Array.isArray(v.items)&&v.items.every(d=>validReviewDocument(d,projectId,revision.id))).then(data=>{if(!live)return;setDocuments(old=>[...data.items,...old.filter(d=>!data.items.some(x=>x.id===d.id))]);const matching=data.items.filter(d=>!kind||d.kind===kind),d=matching.find(d=>d.id===selectedId)??(!selectedId?matching[0]:undefined);if(d&&loaded.current!==d.id)select(d,!initialDocument&&activity.current,true)}).catch(cause=>{if(live)setError(cause instanceof Error?cause.message:'成果读取失败。')});return()=>{live=false}},[base,projectId,revision.id,active,visible,available,refresh,request,setError,selectedId,kind,select,initialDocument])
 const currentDocumentId=current?.id
 const draftChanged=!!current&&(JSON.stringify(draft)!==JSON.stringify(current.snapshot.items.map(i=>({item_id:i.item_id,text:i.text})))||editLanguage!==current.language)
 useEffect(()=>{if(!currentDocumentId||!active||!visible||!available)return;let live=true,timer=0;const id=currentDocumentId;async function load(){try{const data=await request(base+'/documents/'+encodeURIComponent(id)+'/exports',(v):v is {items:DocumentExport[]}=>object(v)&&Array.isArray(v.items)&&v.items.every(e=>validDocumentExport(e,projectId,id)));if(!live)return;setExports(data.items);if(data.items.some(e=>['queued','running'].includes(e.status)))timer=window.setTimeout(()=>void load(),3000)}catch(cause){if(live)setError(cause instanceof Error?cause.message:'成果导出读取失败。')}}void load();return()=>{live=false;window.clearTimeout(timer)}},[base,currentDocumentId,active,visible,available,refresh,projectId,request,setError])
 useReviewDraftGuard(draftChanged||savedDraftDirty)
 async function create(kind:'comparison'|'reply'){const before=selection.current,startingKind=routeKind.current;await run(async()=>{const d=await request(base+'/revisions/'+encodeURIComponent(revision.id)+'/documents',valid,{kind,...(language?{language}:{})});setDocuments(old=>[d,...old.filter(x=>x.id!==d.id)]);if(activity.current&&selection.current===before&&routeKind.current===startingKind)select(d,true,true)})}
 async function save(){if(!current)return;const startingKind=routeKind.current;await run(async()=>{const d=await request(base+'/documents/'+encodeURIComponent(current.id)+'/versions',valid,{expected_version:current.version,language:editLanguage,items:draft});setDocuments(old=>[d,...old.map(x=>x.kind===d.kind?{...x,latest_version:d.version}:x)]);documentDrafts.current.delete(current.id);if(activity.current&&selection.current===current.id&&routeKind.current===startingKind){loaded.current='';select(d,true,true)}})}
 async function confirm(){if(!current||draftChanged)return;const startingKind=routeKind.current;await run(async()=>{const d=await request(base+'/documents/'+encodeURIComponent(current.id)+'/confirm',valid,{expected_version:current.version});setDocuments(old=>old.map(x=>x.id===d.id?d:x));if(activity.current&&selection.current===current.id&&routeKind.current===startingKind)select(d,true,true)})}
 async function exportDoc(){if(!current)return;await run(async()=>{const e=await request(base+'/documents/'+encodeURIComponent(current.id)+'/exports',(v):v is DocumentExport=>validDocumentExport(v,projectId,current.id),{});setExports(old=>[e,...old.filter(x=>x.id!==e.id)]);setRefresh(x=>x+1)})}
 if(!available)return <p>{t('会话或项目不可用，请重新打开项目。')}</p>
 const comparisonOnly=kind==='comparison'||(customer&&projectType==='thesis')
 const heading=kind==='reply'?'独立逐条回复':comparisonOnly?'独立逐条对照':'独立逐条对照与回复'
 const description=!customer?'修改稿、逐条对照和回复分别导出；原意见、实际变化、待补和未采纳原因固定保存。'
  : kind==='reply'?'逐条核对审稿意见和回复。确认回复后可生成 Word。'
  : comparisonOnly?'对照稿汇总原意见、修改前后内容及待处理事项。':null
 const reply=current?.kind==='reply'
 return <section className="manuscript-panel" aria-label={t(heading)}><h3>{t(heading)}</h3>{description&&<p>{t(description)}</p>}{error&&<p role="alert" className="error-panel">{t(error)}</p>}
 <p>{documentDefaults?t('本轮默认文档语言：{language}',{language:t(documentDefaults.language==='en'?'英语':'简体中文')}):t('本轮默认文档语言依据未记录。')}</p><label>{t(kind==='comparison'||projectType!=='sci'?'对照语言':'回复语言')}<select value={language} onChange={e=>setLanguage(e.target.value as ''|'zh-CN'|'en')}><option value="">{t('使用本轮默认')}</option><option value="zh-CN">{t('简体中文')}</option><option value="en">{t('英语')}</option></select></label><button hidden={kind==='reply'} type="button" disabled={busy} onClick={()=>void create('comparison')}>{t(customer?'生成对照稿':'生成独立逐条对照')}</button>{projectType==='sci'&&kind!=='comparison'&&<><button type="button" disabled={busy} onClick={()=>void create('reply')}>{t(customer?'起草逐条回复':'生成独立回复草稿')}</button></>}
 <button type="button" disabled={busy} onClick={()=>setRefresh(n=>n+1)}>{t(customer?'刷新成果':'刷新独立成果')}</button>
 {!!shownDocuments.length&&<label>{t(customer?'查看已保存文档':'选择固定成果版本')}<select disabled={busy} value={current?.id??''} onChange={e=>{const d=documents.find(d=>d.id===e.target.value);if(d)select(d)}}>{shownDocuments.map(d=><option key={d.id} value={d.id}>{t(d.kind==='reply'?'逐条回复':'逐条对照')} · {customer?t(d.language==='en'?'英语':'简体中文'):d.language} · {customer?new Date(d.created_at).toLocaleString(locale):t('版本 {number}',{number:d.version})}</option>)}</select></label>}
 {selectedId&&!current&&<p role="alert">{t(customer?'找不到此文档。请从已保存的文档中选择。':'指定成果版本不可用；不会自动替换为最新成果。')}</p>}
 {current&&<article>
  <h4>{current.snapshot.title}{!customer&&<> · {t('版本 {number}',{number:current.version})} · {current.language}</>}</h4>
  <p>{!customer&&<>{t('来源修改稿版本 {number}',{number:current.snapshot.output.revision})} · </>}
   {t(customer?(current.confirmed_at?'已确认':'待确认'):(current.confirmed_at?'此版本已确认':'此版本尚未确认'))}
  </p>
  {!customer&&<p>SHA256 {current.snapshot.result_sha256}</p>}
  <a href={revisionHash(projectId,revision.round_id,revision.id,current.id)}>{t(customer?'此文档的链接':'此份固定成果链接')}</a>
  {!customer&&<p>{current.snapshot.location_notice}</p>}
 {view&&<label>{t('当前成果意见')}<select value={chosenItemId} onChange={e=>{setLocalItem(e.target.value);reportedItem.current=`${current.id}:${e.target.value}`;onSelectItem?.(e.target.value)}}>{current.snapshot.items.map(i=><option key={i.item_id} value={i.item_id}>{i.source_label} · {i.original_number||i.number} · {i.original_text}</option>)}</select></label>}
 {view&&selectedItemId&&!current.snapshot.items.some(i=>i.item_id===selectedItemId)&&<p role="alert">{t(customer?'找不到这条意见。请选择本文档中的意见。':'指定成果意见不可用；请核对固定意见编号。')}</p>}
 <fieldset disabled={busy||current.version!==current.latest_version}><legend>{t(customer?(reply?'编辑回复':'编辑修改说明'):'编辑当前成果说明')}</legend>
 {reply&&<label>{t(customer?'回复正文语言':'此版本回复语言')}<select value={editLanguage} onChange={e=>{dirty.current=true;setEditLanguage(e.target.value as 'zh-CN'|'en')}}><option value="zh-CN">中文</option><option value="en">English</option></select></label>}
 {current.snapshot.items.map((i,n)=><article hidden={!!view&&i.item_id!==chosenItemId} key={i.item_id}><h5>{i.source_role&&Object.hasOwn(roles,i.source_role)?t(roles[i.source_role as keyof typeof roles])+' · ':''}{i.source_label} · {i.original_number||i.number} · {t({completed:'有实际修改',executing:'执行中',waiting_material:'待补材料',not_adopted:'未采纳',pending:'待处理',waiting_confirmation:'待确认'}[i.status]??(customer?'待核对':i.status))}</h5><blockquote>{i.original_text}</blockquote>{i.translation&&<p>{t('人工译文')} · {i.translation.text}</p>}<p>{i.reason}</p>{i.actual_changes.map((c,j)=><dl key={j}><dt>{t('修改前')}</dt><dd>{customer?customerChangeText(c.before,t,c.kind,c.before):<FixedChangeValue value={c.before}/>}</dd><dt>{t('修改后')}</dt><dd>{customer?customerChangeText(c.after,t,c.kind,c.before):<FixedChangeValue value={c.after}/>}</dd></dl>)}{i.locations.map((l,j)=><p key={j}>{customer?customerReviewLocation(l,t):locationText(l,t)}</p>)}{i.evidence.map((e,j)=><FixedEvidenceDetails key={j} evidence={e} customer={customer} names={evidenceNames}/>)}<label>{t(customer?(reply?'回复 {number}':'修改说明 {number}'):'逐条回复或说明 {number}',{number:n+1})}<textarea value={draft.find(d=>d.item_id===i.item_id)?.text??i.text} onChange={e=>{dirty.current=true;setDraft(old=>old.map(d=>d.item_id===i.item_id?{...d,text:e.target.value}:d))}}/></label></article>)}
 <button type="button" disabled={!draftChanged} onClick={()=>void save()}>{t(customer?(reply?'另存回复':'另存说明'):'保存为新成果版本')}</button>
 <button type="button" disabled={draftChanged||!!current.confirmed_at||current.version!==current.latest_version} onClick={()=>void confirm()}>{t(customer?(reply?'确认回复':'确认对照稿'):(reply?'确认此回复版本':'确认此对照版本'))}</button></fieldset>
 <button type="button" disabled={busy||draftChanged||reply&&!current.confirmed_at} onClick={()=>void exportDoc()}>{t(customer?'生成 Word':'导出此版本 DOCX')}</button>
 {exports.filter(e=>e.document_id===current.id).map(e=><section key={e.id} className="review-word-output">
  <h5>{t(current.kind==='reply'?'逐条回复':'逐条对照')} · {customer?t(current.language==='en'?'英语':'简体中文'):current.language}
   {!customer&&<> · {t('版本 {number}',{number:current.version})} · DOCX</>}
   {' · '}{t({queued:'待执行',running:'运行中',succeeded:'已完成',failed:'执行失败'}[e.status])}
  </h5>
  {e.error_code&&<p className="warning-panel">{customer?t(apiError({code:e.error_code},'Word 导出失败，请查看任务详情。')):e.error_code}</p>}
  {e.status==='succeeded'&&e.download_url&&e.sha256&&<>
   {!customer&&<p>DOCX SHA256 {e.sha256}</p>}
   <ProjectDownloadLink href={e.download_url} filename={customer
    ? t(current.kind==='reply'?'审稿意见回复':'逐条修改对照')+'.docx'
    : e.filename??'review.docx'}>{t(customer?'下载 Word':'下载此版本 DOCX')}</ProjectDownloadLink>
  </>}
  <button type="button" onClick={()=>onOpenTask(e.task_id)}>{t('查看独立成果任务')}</button>
 </section>)}
 </article>}
 {!customer&&<p className="muted">{t('没有可核验的 PDF 页/行映射时只显示稳定定位；Word/WPS 分页可能不同。')}</p>}</section>
}
