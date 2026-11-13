import '../research-results/researchLayout.css'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import {deliveryMemberContainsPdf as retiredCandidate} from '../../shared/pdfDelivery'
import ReadableDetails from '../../shared/components/ReadableDetails'
import {useEffect,useRef,useState,type ReactNode} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import useResearchDraft from '../research-results/useResearchDraft'
import {Notices,OperationStatus} from '../research-results/ResearchShared'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {intakeRequest,jsonRequest} from './api'
import useDeliveryOperation from './useDeliveryOperation'
import {completenessLabels,deliveryBase,deliveryHref,deliveryStageLabels,selectionKey,type AcceptanceEvent,type AcceptanceWrite,type Candidate,type DeliveryCandidates,type DeliveryPackage,type DeliverySnapshot,type SnapshotWrite} from './deliveryPackageContracts'
type Props={projectId:string;deliveryId:string;active:boolean;snapshotId?:string;onSelect:(id:string)=>void;registerLeaveGuard?:RegisterLeaveGuard;analysisOnly?:boolean;requiredVersionId?:string;renderSnapshotActions?:(snapshot:DeliverySnapshot)=>ReactNode;publicationHistory?:ReactNode}
const stageName=(stage:string)=>({first:'首次交付',revision:'修订交付',final:'最终交付阶段'}[stage]??'交付阶段待核对')
const modeName=(mode:string)=>mode==='blind'?'盲审交付':'普通交付'
const formatName=(format:string)=>({docx:'Word 文档',pdf:'PDF 文档',png:'PNG 图片',tiff:'TIFF 图片',jpg:'JPG 图片',jpeg:'JPEG 图片',svg:'SVG 矢量图',zip:'ZIP 压缩包',csv:'CSV 数据表',tsv:'TSV 数据表',xlsx:'Excel 数据表'}[format]??'其他格式文件')
const reviewName=(mode?:string)=>mode==='blind'?'盲审版':mode==='identified'?'署名版':mode?'审阅模式待核对':''
const languageName=(language?:string)=>language?({'zh-CN':'简体中文',zh:'中文',en:'英文','en-US':'英文'}[language]??'其他语言'):''
const noticeText=(text:string)=>text.replace(/required_format:/g,'缺少必需格式：').replace(/font_verification:/g,'字体核对：').replace(/pending_verification/g,'待核对').replace(/unknown/g,'未知').replace(/mapping_status:/g,'图号对应状态：').replace(/figure_mapping:/g,'图号与面板对应待核对：').replace(/text_verification:/g,'图中文字待核对：').replace(/semantic_verification:/g,'科学含义待核对：').replace(/source_alignment:/g,'来源对应关系待核对：').replace(/source_quality:/g,'来源质量待核对：')
const emptyDraft=():SnapshotWrite=>({stage:'first',parent_snapshot_id:null,expected_revision:0,requirement_version_id:'',change_note:'',opinion_round:'',opinion_round_id:null,opinion_round_event_id:null,mode:'complete',required_formats:[],quality_items:[],members:[]})
const lines=(value:string)=>value.split(/[,，\n]/).map(s=>s.trim()).filter(Boolean)
export default function DeliveryPackagePanel(props:Props){return <Panel key={`${props.projectId}:${props.deliveryId}`} {...props}/>}
function Panel({projectId,deliveryId,active,snapshotId='',onSelect,registerLeaveGuard,analysisOnly=false,requiredVersionId,renderSnapshotActions,publicationHistory}:Props){
 const {t,locale}=useI18n(),base=deliveryBase(projectId,deliveryId),[candidates,setCandidates]=useState<DeliveryCandidates|null>(null),[history,setHistory]=useState<DeliverySnapshot[]>([]),[selected,setSelected]=useState<DeliverySnapshot|null>(null),[readId,setReadId]=useState(snapshotId),[editing,setEditing]=useState(false),[deliveryView,setDeliveryView]=useState(analysisOnly&&!snapshotId?'candidates':'snapshot'),[valid,setValid]=useState(true),[loading,setLoading]=useState(false),[error,setError]=useState(''),[reload,setReload]=useState(0),[preview,setPreview]=useState<DeliverySnapshot|null>(null),[previewSignature,setPreviewSignature]=useState('')
 const [freezeCheck,setFreezeCheck]=useState<{signature:string;containsPdf:boolean}|null>(null)
 const [savedDraft,setDraft]=useResearchDraft(projectId,`delivery:${deliveryId}`,emptyDraft),freeze=useDeliveryOperation<DeliverySnapshot>(projectId,deliveryId,'freeze'),previewController=useRef<AbortController|null>(null),latest=history[0]
 const hasDraft=JSON.stringify(savedDraft)!==JSON.stringify(emptyDraft())
 const draft=analysisOnly&&!hasDraft&&!latest&&requiredVersionId
  ?{...savedDraft,requirement_version_id:requiredVersionId,opinion_round:'分析交付'}
  :savedDraft
 const signature=JSON.stringify(draft)
 useDraftLeaveGuard(registerLeaveGuard,(analysisOnly||editing)&&hasDraft,loading||freeze.busy||freeze.unknown)
 useEffect(()=>{setReadId(snapshotId);if(analysisOnly)setDeliveryView(snapshotId?'snapshot':'candidates')},[analysisOnly,snapshotId])
 useEffect(()=>()=>previewController.current?.abort(),[])
 useEffect(()=>onApiSessionChanged(()=>{previewController.current?.abort();setValid(false);setCandidates(null);setHistory([]);setSelected(null);setPreview(null);setEditing(false)}),[])
 useEffect(()=>{setPreview(null);setPreviewSignature('');previewController.current?.abort()},[signature])
 useEffect(()=>{if(!active||!valid)return;const c=new AbortController();let live=true;setLoading(true);void Promise.all([intakeRequest<DeliveryCandidates>(base+'/candidates',{signal:c.signal}),intakeRequest<{items:DeliverySnapshot[]}>(base+'/snapshots',{signal:c.signal})]).then(([a,b])=>{if(live){setCandidates(a);setHistory(b.items);setError('')}}).catch(e=>{if(live)setError(safeError(e,'交付来源读取失败，请重试。'))}).finally(()=>{if(live)setLoading(false)});return()=>{live=false;c.abort()}},[base,active,valid,reload])
 useEffect(()=>{if(!analysisOnly)setSelected(null);if(!active||!valid||!readId)return;const c=new AbortController();let live=true;void intakeRequest<DeliverySnapshot>(base+'/snapshots/'+encodeURIComponent(readId),{signal:c.signal}).then(s=>{if(live)setSelected(s)}).catch(e=>{if(live)setError(safeError(e,'固定快照读取失败，请重新核对。'))});return()=>{live=false;c.abort()}},[base,readId,active,valid,reload,analysisOnly])
 useEffect(()=>{if(!freeze.value)return;const result=freeze.value;setSelected(result);setReadId(result.id);setEditing(false);setDeliveryView('snapshot');setDraft(emptyDraft());setPreview(null);setReload(r=>r+1);onSelect(result.id)},[freeze.value])
 const blocked=loading||freeze.busy||freeze.unknown||!freeze.valid||!valid
 function edit(p:Partial<SnapshotWrite>){setDraft({...draft,...p});setPreview(null)}
 function derive(s:DeliverySnapshot){if(blocked)return;const binding=analysisOnly?undefined:s.opinion_round_binding;setDraft({stage:'revision',parent_snapshot_id:s.id,expected_revision:s.revision,requirement_version_id:s.requirement_version_id,change_note:'',opinion_round:analysisOnly?'分析交付':s.opinion_round,opinion_round_id:binding?.status==='fixed_existing_event'?String(binding.round_id):null,opinion_round_event_id:binding?.status==='fixed_existing_event'?String(binding.event_id):null,mode:analysisOnly?'complete':s.mode,required_formats:s.required_formats,quality_items:s.quality_items,members:s.members.map(m=>m.selection)});setEditing(true);setPreview(null)}
 function toggle(c:Candidate,checked:boolean){edit({members:checked?[...draft.members,c.selection]:draft.members.filter(m=>selectionKey(m)!==selectionKey(c.selection))})}
 const knownMembers=[...history.flatMap(s=>s.members),...(selected?.members??[]),...(preview?.members??[])]
 const eligible=(c:Candidate,mode:SnapshotWrite['mode'])=>(!analysisOnly||c.selection.kind!=='manuscript_export')&&!retiredCandidate(c)&&!knownMembers.some(m=>selectionKey(m.selection)===selectionKey(c.selection)&&retiredCandidate(m))&&(c.status==='succeeded'||c.status==='existing_upload')&&(mode==='complete'||c.review_mode==='blind'||c.blind_eligible===true)
 const retiredPdf=draft.members.some(m=>m.kind==='pdf_export'||[...(candidates?.items??[]),...knownMembers].some(c=>selectionKey(c.selection)===selectionKey(m)&&retiredCandidate(c)))
 const pdfRequired=draft.required_formats.some(format=>format.toLowerCase()==='pdf')
 const pendingFreeze=freeze.pendingBody as Partial<SnapshotWrite>|undefined
 const retiredFreeze=pendingFreeze?.required_formats?.some(format=>format.toLowerCase()==='pdf')||pendingFreeze?.members?.some(m=>m.kind==='pdf_export'||[...(candidates?.items??[]),...knownMembers].some(c=>selectionKey(c.selection)===selectionKey(m)&&retiredCandidate(c)))
 const freezeSignature=JSON.stringify(freeze.pendingBody)
 useEffect(()=>{
  setFreezeCheck(null)
  if(!active||!valid||!freeze.valid||freeze.busy||!freeze.retryable||retiredFreeze||!candidates||loading||!freeze.pendingBody)return
  const c=new AbortController();let live=true
  void intakeRequest<DeliverySnapshot>(base+'/snapshots/preview',{...jsonRequest(freeze.pendingBody),signal:c.signal}).then(result=>{if(live&&!c.signal.aborted)setFreezeCheck({signature:freezeSignature,containsPdf:result.members.some(retiredCandidate)})}).catch(cause=>{if(live&&!c.signal.aborted)setError(safeError(cause,'固定交付快照读取失败，请重试。'))})
  return()=>{live=false;c.abort()}
 },[base,active,valid,freeze.valid,freeze.busy,freeze.retryable,freeze.pendingBody,freezeSignature,retiredFreeze,candidates,loading])
 const ready=!retiredPdf&&!pdfRequired&&!!draft.requirement_version_id&&(requiredVersionId===undefined||draft.requirement_version_id===requiredVersionId)&&!!draft.change_note.trim()&&!!draft.opinion_round.trim()&&!!draft.members.length&&(!draft.opinion_round_id||!!draft.opinion_round_event_id)&&(!analysisOnly||!draft.members.some(member=>member.kind==='manuscript_export'))
 async function check(){if(blocked||!ready)return;previewController.current?.abort();const c=new AbortController();previewController.current=c;const input=signature;setLoading(true);setError('');try{const value=await intakeRequest<DeliverySnapshot>(base+'/snapshots/preview',{...jsonRequest(draft),signal:c.signal});if(!c.signal.aborted){setPreview(value);setPreviewSignature(input)}}catch(e){if(!c.signal.aborted)setError(safeError(e,'核对失败，草稿已保留。'))}finally{if(previewController.current===c){previewController.current=null;setLoading(false)}}}
 const round=candidates?.opinion_rounds?.find(r=>r.id===draft.opinion_round_id)
 if(!valid||!freeze.valid)return <p role="alert">{t('会话已改变，请重新打开项目。')}</p>
 const refresh=<button type="button" disabled={blocked} onClick={()=>setReload(r=>r+1)}>{t(analysisOnly?'刷新交付记录':'读取服务器历史并保留草稿')}</button>
 const count=<span>{t('已选择成员数')} <output aria-label={t('已选择成员数')}>{draft.members.length}</output></span>
 const snapshotLabel=(s:DeliverySnapshot)=>[t(stageName(s.stage)),!analysisOnly&&`${t('版本')} ${s.revision}`,new Date(s.created_at).toLocaleString(locale)].filter(Boolean).join(' · ')
 const openSnapshot=(id:string)=>{setReadId(id);onSelect(id)}
 const visibleSnapshot=analysisOnly&&selected?.id!==readId?null:selected
 const startRevision=visibleSnapshot&&<button type="button" disabled={blocked} onClick={()=>{derive(visibleSnapshot);setDeliveryView(analysisOnly?'candidates':'draft')}}>{t(analysisOnly?'沿用这次交付进行修订':'从此快照派生新版本')}</button>
 const olderSnapshot=visibleSnapshot&&latest&&visibleSnapshot.id!==latest.id&&<p className="warning-panel">{t('正在查看历史交付。修订前请核对最近的交付：')}{snapshotLabel(latest)}</p>
 const freezeFields=<>
   <label>{t('交付阶段')}<select value={draft.stage} onChange={e=>edit({stage:e.target.value as SnapshotWrite['stage']})}><option value="first" disabled={!!draft.parent_snapshot_id}>{t('首次交付')}</option><option value="revision" disabled={!draft.parent_snapshot_id}>{t('修订交付')}</option><option value="final" disabled={!draft.parent_snapshot_id}>{t('最终阶段（不等于接受）')}</option></select></label>
   {!analysisOnly&&<p>{t('固定父快照')} {draft.parent_snapshot_id?t('已选定原交付版本'):t('首次交付，无原版本')} · {t('期望修订号')} {draft.expected_revision}</p>}
   {latest&&<div className={analysisOnly?'analyst-delivery-actions':undefined}><span>{analysisOnly?`${t('最近冻结')}: ${snapshotLabel(latest)}`:`${t('服务器当前父快照')} · ${t('版本')} ${latest.revision}`}</span><button type="button" onClick={()=>edit({parent_snapshot_id:latest.id,expected_revision:latest.revision,stage:draft.stage==='first'?'revision':draft.stage})}>{t(analysisOnly?'采用最近的交付（保留选择）':'已比较，明确采用此父快照与修订号（保留选择）')}</button></div>}
   <label>{t(analysisOnly?'关联客户需求':'固定需求版本')}<select value={draft.requirement_version_id} onChange={e=>edit({requirement_version_id:e.target.value})}><option value="">{t(analysisOnly?'请选择客户需求':'请选择需求版本')}</option>{candidates?.requirements.filter(r=>requiredVersionId===undefined||r.id===requiredVersionId).map(r=><option key={r.id} value={r.id}>{analysisOnly?[t('客户最新提交'),r.created_at&&new Date(r.created_at).toLocaleString(locale)].filter(Boolean).join(' · '):`${t('已保存需求')} · ${t('版本')} ${r.version}`}</option>)}</select></label>
   {!analysisOnly&&<><label>{t('交付模式')}<select value={draft.mode} onChange={e=>edit({mode:e.target.value as SnapshotWrite['mode'],members:[]})}><option value="complete">{t('普通完整交付')}</option><option value="blind">{t('独立盲审子交付')}</option></select></label>
   {draft.mode==='blind'&&<p className="warning-panel">{t('仅选择明确适用的盲审派生件；普通报告 ZIP、表格、图源和原件不会自动加入。整个 ZIP 匿名性仍需独立核查。')}</p>}</>}
   {retiredPdf&&<p role="alert">{t('新交付不再支持 PDF 成果，请移除此原选择；其他草稿内容保留。')}</p>}{pdfRequired&&<p role="alert">{t('交付不再支持 PDF 必需格式，请移除后继续；其他草稿内容保留。')}<button type="button" onClick={()=>edit({required_formats:draft.required_formats.filter(format=>format.toLowerCase()!=='pdf')})}>{t('移除 PDF 格式')}</button></p>}<label>{t(analysisOnly?'本次必需格式':'本次必需格式（逗号分隔）')}<DelimitedInput placeholder={analysisOnly?t('用逗号分隔，例如 png, docx'):undefined} value={draft.required_formats} onChange={value=>edit({required_formats:value.map(v=>v.toLowerCase())})}/></label>
   <label>{t('本次修改说明')}<textarea rows={2} maxLength={8000} value={draft.change_note} onChange={e=>edit({change_note:e.target.value})}/></label>
   {!analysisOnly&&<><label>{t('意见轮次说明或不适用原因')}<input maxLength={200} value={draft.opinion_round} onChange={e=>edit({opinion_round:e.target.value})}/></label>
   <label>{t('绑定已有意见轮次')}<select value={draft.opinion_round_id??''} onChange={e=>edit({opinion_round_id:e.target.value||null,opinion_round_event_id:null})}><option value="">{t('不绑定；上述说明仅为人工标签')}</option>{candidates?.opinion_rounds?.map(r=><option key={r.id} value={r.id}>{t('第')} {r.round_number} {t('轮')} · {r.label}</option>)}</select></label>
   {round&&<label>{t('固定意见事件')}<select value={draft.opinion_round_event_id??''} onChange={e=>edit({opinion_round_event_id:e.target.value||null})}><option value="">{t('请选择已保存事件')}</option>{round.events.map(e=><option key={e.id} value={e.id}>{t('已保存事件')} · {t('版本')} {e.revision}</option>)}</select></label>}</>}
   <label>{t(analysisOnly?'人工未决质量项':'人工未决质量项（每行一项）')}<textarea rows={2} placeholder={analysisOnly?t('选填，每行一项'):undefined} value={draft.quality_items.map(text=>(selected?.members??[]).reduce((result,member)=>result.replaceAll(member.id,member.name),noticeText(text))).join('\n')} onChange={e=>edit({quality_items:e.target.value.split('\n')})}/></label>
 </>
 const available=candidates?.items.filter(c=>eligible(c,draft.mode))??[]
 function candidate(c:Candidate){
  const key=selectionKey(c.selection),chosen=draft.members.find(m=>selectionKey(m)===key)
  const date=analysisOnly&&c.created_at?new Date(c.created_at).toLocaleString(locale):''
  const label=[c.label,t(formatName(c.format)),c.review_mode&&t(reviewName(c.review_mode)),date].filter(Boolean).join(' · ')
  function updateMapping(figure_mapping:NonNullable<SnapshotWrite['members'][number]['figure_mapping']>){
   edit({members:draft.members.map(m=>selectionKey(m)===key?{...m,figure_mapping}:m)})
  }
  const mapping=chosen?.figure_mapping
  return <div key={key} className={analysisOnly?'analyst-delivery-candidate':undefined}>
   {analysisOnly?<label className="analyst-delivery-candidate-row">
    <strong>{c.label}</strong><span>{date||t(formatName(c.format))}{c.language&&' · '+t(languageName(c.language))}</span>
    <input aria-label={label} type="checkbox" checked={!!chosen} onChange={e=>toggle(c,e.target.checked)}/>
   </label>:<>
    <label><input type="checkbox" checked={!!chosen} onChange={e=>toggle(c,e.target.checked)}/>{label}</label>
    <small>{t(languageName(c.language))} · {t('已保存成果')}</small>
   </>}
   {chosen&&['png','tiff','jpg','jpeg','svg'].includes(c.format)&&<fieldset className={analysisOnly?'analyst-delivery-fields analyst-delivery-mapping':undefined}>
    <legend>{t('图号与面板声明')}{!analysisOnly&&' · '+c.label}</legend>
    <label>{t('图号')}<input value={mapping?.figure_number??''} onChange={e=>updateMapping({figure_number:e.target.value,panel_order:mapping?.panel_order??[],caption:mapping?.caption??'',confirmed:mapping?.confirmed??false})}/></label>
    {mapping&&<>
     <label>{t('面板顺序（逗号分隔）')}<DelimitedInput value={mapping.panel_order} onChange={panel_order=>updateMapping({...mapping,panel_order})}/></label>
     <label>{t('图注')}<textarea rows={2} value={mapping.caption} onChange={e=>updateMapping({...mapping,caption:e.target.value})}/></label>
     <label className={analysisOnly?'analyst-delivery-check':undefined}><input type="checkbox" checked={mapping.confirmed} onChange={e=>updateMapping({...mapping,confirmed:e.target.checked})}/>{t('明确确认此图号与面板对应（不确认字体、文字或科学语义）')}</label>
    </>}
   </fieldset>}
  </div>
 }
 const missing=draft.members.filter(m=>!available.some(c=>selectionKey(c.selection)===selectionKey(m))).map(m=>
  <p key={selectionKey(m)} className="warning-panel">{t('原选择当前不可选，请明确移除或核对来源')} {t('此前选定的成果')} {draft.members.indexOf(m)+1} <button type="button" onClick={()=>edit({members:draft.members.filter(s=>selectionKey(s)!==selectionKey(m))})}>{t('移除此原选择')}</button></p>)
 const canFreeze=preview&&previewSignature===signature&&!retiredPdf&&!pdfRequired
 const checkButton=<button type="button" className={analysisOnly&&!canFreeze?'button-primary':undefined} disabled={blocked||!ready} onClick={()=>void check()}>{t('核对所选成员与缺口')}</button>
 const freezeButton=canFreeze&&<button type="button" className={analysisOnly?'button-primary':undefined} disabled={blocked} onClick={()=>void freeze.submit('freeze',base+'/snapshots',draft,base+'/snapshots/requests/{key}')}>{t('冻结本次交付快照')}</button>
 const operationStatus=<>{freeze.unknown&&(retiredFreeze||freezeCheck?.containsPdf)&&<p>{t('此历史交付包含 PDF，仅保留状态与原请求查询。')}</p>}<OperationStatus operation={{...freeze,retryable:freeze.retryable&&!retiredFreeze&&!loading&&!!candidates&&freezeCheck?.signature===freezeSignature&&!freezeCheck.containsPdf}}/></>

 if(analysisOnly){
  const canEdit=!!candidates&&(!latest||hasDraft||editing)
  const waitForRequirement=requiredVersionId===''
  const moveToPublication=<button type="button" onClick={()=>setDeliveryView('snapshot')}>{t('查看已冻结快照')}</button>
  return <section hidden={!active} className="analyst-delivery-panel" aria-busy={loading||freeze.busy}>
   {error&&<p role="alert" className="error-panel">{t(error)}</p>}
   <ModuleViews label={t('交付流程')} value={deliveryView} onChange={setDeliveryView}>
    <ModuleView id="candidates" title={t('交付候选')}>
     <div className="analyst-delivery-bar"><p>{t('勾选本次要交付的文件。')}</p>{refresh}</div>
     {!candidates&&loading&&<p role="status">{t('正在读取交付候选……')}</p>}
     {candidates&&!available.length&&<p className="analyst-delivery-hint">{t('暂无可选的交付文件。')}</p>}
     {candidates&&(available.length>0||missing.length>0)&&<fieldset className="analyst-delivery-candidates" disabled={blocked||!canEdit||waitForRequirement}>
      {(['succeeded','existing_upload'] as const).map(status=>{
       const items=available.filter(c=>c.status===status)
       return items.length>0&&<div className="analyst-delivery-candidate-group" key={status}>
        <h3>{t(status==='succeeded'?'分析成果':'已上传文件')}</h3>
        {items.map(candidate)}
       </div>
      })}
      {missing}
     </fieldset>}
     {waitForRequirement?<p className="analyst-delivery-hint">{t('客户尚未提交需求。')}</p>:candidates&&
      <div className="analyst-delivery-bar analyst-delivery-footer">{count}{canEdit
       ?<button type="button" className="button-primary" disabled={blocked||!draft.members.length} onClick={()=>setDeliveryView('draft')}>{t('下一步：冻结快照')}</button>
       :moveToPublication}</div>}
    </ModuleView>
    <ModuleView id="draft" title={t('冻结快照')}>
     {canEdit&&!waitForRequirement?<div className="analyst-delivery-module">
      <div className="analyst-delivery-freeze">
       <fieldset className="analyst-delivery-fields" disabled={blocked}>{freezeFields}</fieldset>
       {canFreeze&&<SnapshotFacts snapshot={preview} candidates={available}/>}
      </div>
      <div className="analyst-delivery-bar">
       <span>{count}{!ready&&<small> · {t('请先选定成员并填写本次修改说明。')}</small>}</span>
       <div className="analyst-delivery-actions">{checkButton}{freezeButton}</div>
      </div>
     </div>:candidates&&<div className="analyst-delivery-bar">
      <p>{t(waitForRequirement?'客户尚未提交需求。':'沿用已冻结的交付后，可调整本次要交付的文件。')}</p>
      {!waitForRequirement&&moveToPublication}
     </div>}
    </ModuleView>
    <ModuleView id="snapshot" title={t('发布交付')}>
     <div className="analyst-delivery-module">
      {history.length>0?<div className="analyst-delivery-row">
       <label>{t('固定交付快照')}<select value={readId} onChange={e=>openSnapshot(e.target.value)} disabled={blocked}>
        <option value="" disabled>{t('请选择交付快照')}</option>
        {history.map(s=><option key={s.id} value={s.id}>{snapshotLabel(s)}</option>)}
       </select></label>
       {startRevision}
      </div>:candidates&&<div className="analyst-delivery-bar"><p>{t('请先冻结交付快照。')}</p>
       <button type="button" onClick={()=>setDeliveryView('draft')}>{t('去冻结快照')}</button></div>}
      {readId&&!visibleSnapshot&&!error&&<p role="status">{t('正在读取交付记录……')}</p>}
      {visibleSnapshot&&<>
       {renderSnapshotActions?.(visibleSnapshot)}
       {olderSnapshot}
       <SnapshotFacts snapshot={visibleSnapshot} candidates={available}/>
       <div className="analyst-delivery-actions"><a href={deliveryHref(projectId,deliveryId,visibleSnapshot.id)}>{t('此快照的固定链接')}</a>
        <button type="button" onClick={()=>setDeliveryView('package')}>{t('生成和下载 ZIP')}</button></div>
      </>}
      {publicationHistory&&<div className="analyst-delivery-history">{publicationHistory}</div>}
     </div>
    </ModuleView>
    {visibleSnapshot&&<ModuleView id="package" title={t('生成和下载 ZIP')}>
     <PackageAndAcceptance key={visibleSnapshot.id} projectId={projectId} deliveryId={deliveryId} snapshot={visibleSnapshot} active={active&&valid&&deliveryView==='package'} registerLeaveGuard={registerLeaveGuard} analysisOnly/>
    </ModuleView>}
   </ModuleViews>
   {operationStatus}
  </section>
 }

 return <section hidden={!active} aria-label={t('固定交付快照')} className="project-form research-panel" aria-busy={loading||freeze.busy}>
  <h3>{t('固定交付快照与接受记录')}</h3>{refresh}{error&&<p role="alert">{t(error)}</p>}
  <ModuleViews label={t('固定交付快照与接受记录')} value={deliveryView} onChange={setDeliveryView}>
   <ModuleView id="snapshot" title={t('固定交付快照')}>
    <h4>{t('历史快照')}</h4><ul className="research-record-list">{history.map(s=><li key={s.id}><a href={deliveryHref(projectId,deliveryId,s.id)} onClick={()=>openSnapshot(s.id)}>{t(stageName(s.stage))} · {t('版本')} {s.revision} · {t(modeName(s.mode))} · {new Date(s.created_at).toLocaleString(locale)}</a></li>)}</ul>
    {!history.length&&candidates&&<button type="button" disabled={blocked||requiredVersionId===''} onClick={()=>{setEditing(true);setDeliveryView('draft')}}>{t('准备首次交付')}</button>}
    {!editing&&hasDraft&&<button type="button" disabled={blocked} onClick={()=>{setEditing(true);setDeliveryView('draft')}}>{t('继续已保留的交付草稿')}</button>}
    {selected&&<><SnapshotFacts snapshot={selected}/><p><a href={deliveryHref(projectId,deliveryId,selected.id)}>{t('此快照的固定链接')}</a></p>{startRevision}{olderSnapshot}{renderSnapshotActions?.(selected)}</>}
   </ModuleView>
   <ModuleView id="draft" title={t('交付草稿')}>
    {editing&&<><fieldset disabled={blocked}><legend>{t('本次固定交付输入')}</legend>{freezeFields}
     <h4>{t('选择已有成员')}</h4>{available.map(candidate)}<p>{count}</p>{missing}{checkButton}
    </fieldset>{canFreeze&&<><SnapshotFacts snapshot={preview}/>{freezeButton}</>}</>}
   </ModuleView>
   <ModuleView id="package" title={t('封包与接受')}>{selected&&<PackageAndAcceptance key={selected.id} projectId={projectId}
    deliveryId={deliveryId} snapshot={selected} active={active&&valid} registerLeaveGuard={registerLeaveGuard} analysisOnly={false}/>}</ModuleView>
  </ModuleViews>
  {operationStatus}
 </section>
}
function SnapshotFacts({snapshot:s,candidates}:{snapshot:DeliverySnapshot;candidates?:Candidate[]}){
 const{t,locale}=useI18n()
 const memberLabel=(member:DeliverySnapshot['members'][number])=>member.display_name??candidates?.find(c=>selectionKey(c.selection)===selectionKey(member.selection))?.label??t('交付文件')
 const displayNotice=(text:string)=>s.members.reduce((result,member)=>result.replaceAll(member.name,memberLabel(member)).replaceAll(member.id,memberLabel(member)),noticeText(text))
 if(candidates)return <section aria-label={t('冻结成员与缺口核对')} className="analyst-delivery-review">
  <div className="analyst-delivery-bar">
   <h3>{t(s.sha256?'固定交付快照':'预览尚未冻结')}</h3>
   <span className={`status-badge analyst-delivery-completeness${s.completeness==='complete'?' is-complete':''}`}>{t(completenessLabels[s.completeness])}</span>
  </div>
  <p className="analyst-delivery-hint">{t(stageName(s.stage))}{s.created_at&&` · ${new Date(s.created_at).toLocaleString(locale)}`} · {t('已选择成员数')} {s.members.length}</p>
  <ul className="analyst-delivery-members">{s.members.map(m=><li key={m.id}>
   <strong>{memberLabel(m)}</strong><span>{t(formatName(m.format))}</span>
   {m.download_url&&!retiredCandidate(m)&&<ProjectDownloadLink href={m.download_url} filename={memberLabel(m)} ariaLabel={`${t('下载已有成员')} ${memberLabel(m)}`}>{t('下载')}</ProjectDownloadLink>}
  </li>)}</ul>
  <Notices title="必需格式缺口" items={s.gaps.map(displayNotice)}/>
  <Notices title="质量待核对事项" items={s.quality_items.map(displayNotice)}/>
  {Boolean(s.source_notices?.length)&&<div className="analyst-delivery-records"><h4>{t('来源限制与材料声明')}</h4><ReadableDetails value={s.source_notices} readerView/></div>}
  {s.sha256&&<ModuleViews label={t('快照资料')} lazy>
   <ModuleView id="changes" title={t('本次调整')}>
    <p>{s.change_note}</p><p>{t('新增')} {s.changes.added.length} · {t('移除')} {s.changes.removed.length} · {t('替换')} {s.changes.replaced.length}</p>
   </ModuleView>
   <ModuleView id="source" title={t('质量与限制')}>
    <p>{t('本次必需格式')} {s.required_formats.map(format=>t(formatName(format))).join('、')||t('未指定')}</p>
    {s.members.map(m=><div key={m.id} className="analyst-delivery-records">
     <h4>{memberLabel(m)}</h4><ReadableDetails value={{image:m.image,presentation:m.presentation,source_metadata:m.source_metadata}} readerView/>
    </div>)}
   </ModuleView>
  </ModuleViews>}
 </section>
 return <section aria-label={t('冻结成员与缺口核对')}><h4>{t(completenessLabels[s.completeness])}</h4><p>{t('版本')} {s.revision} · {t(stageName(s.stage))} · {t(modeName(s.mode))} · {t(s.sha256?'交付记录已保存':'预览尚未冻结')}</p>
 <ModuleViews label={t('冻结成员与缺口核对')}><ModuleView id="members" title={t('所选成员')}><ul>{s.members.map(m=><li key={m.id}><strong>{m.name}</strong> · {t(formatName(m.format))} · {t(languageName(m.language))} {t(reviewName(m.review_mode))}{m.download_url&&!retiredCandidate(m)&&<ProjectDownloadLink href={m.download_url} filename={m.name}>{t('下载已有成员')} {m.name}</ProjectDownloadLink>}<ReadableDetails value={{image:m.image,presentation:m.presentation,source_metadata:m.source_metadata}}/></li>)}</ul></ModuleView>
 <ModuleView id="quality" title={t('质量与限制')}><p>{t('本次必需格式')} {s.required_formats.map(format=>t(formatName(format))).join('、')||t('未指定')}</p><Notices title="必需格式缺口" items={s.gaps.map(displayNotice)}/><Notices title="质量待核对事项" items={s.quality_items.map(displayNotice)}/><h4>{t('来源限制与材料声明')}</h4><ReadableDetails value={s.source_notices??[]}/><p>{t('最终交付阶段、任务成功与格式齐备均不自动代表客户接受。')}</p></ModuleView>
 <ModuleView id="changes" title={t('版本变更')}><p>{s.change_note} · {s.opinion_round}</p><p>{t('新增')} {s.changes.added.length} · {t('移除')} {s.changes.removed.length} · {t('替换')} {s.changes.replaced.length}</p><p>{s.changes.reason}</p>{s.opinion_round_binding&&<><h4>{t('意见轮次绑定说明')}</h4><ReadableDetails value={s.opinion_round_binding}/></>}</ModuleView></ModuleViews></section>
}
function PackageAndAcceptance({projectId,deliveryId,snapshot:s,active,registerLeaveGuard,analysisOnly}:{projectId:string;deliveryId:string;snapshot:DeliverySnapshot;active:boolean;registerLeaveGuard?:RegisterLeaveGuard;analysisOnly:boolean}){
 const{t,locale}=useI18n(),base=deliveryBase(projectId,deliveryId)+'/snapshots/'+encodeURIComponent(s.id),visible=useDocumentVisible(),[pack,setPack]=useState<DeliveryPackage|null>(null),[events,setEvents]=useState<AcceptanceEvent[]>([]),[error,setError]=useState(''),[reload,setReload]=useState(0),[valid,setValid]=useState(true)
 const containsPdf=s.members.some(retiredCandidate)
 const packageOp=useDeliveryOperation<DeliveryPackage>(projectId,deliveryId,'package:'+s.id),acceptOp=useDeliveryOperation<AcceptanceEvent>(projectId,deliveryId,'acceptance:'+s.id),[accept,setAccept]=useResearchDraft<AcceptanceWrite>(projectId,`delivery-acceptance:${deliveryId}:${s.id}`,()=>({snapshot_sha256:s.sha256,kind:'accept',scope:'',reservations:'',comment:'',customer_reply:null,corrects_event_id:null}))
 useDraftLeaveGuard(registerLeaveGuard,!!accept.scope||!!accept.comment,packageOp.busy||packageOp.unknown||acceptOp.busy||acceptOp.unknown)
 useEffect(()=>onApiSessionChanged(()=>{setValid(false);setEvents([]);setPack(null)}),[])
 useEffect(()=>{if(!active||!visible||!valid)return;const c=new AbortController();let live=true,timer=0;async function read(){try{const [p,a]=await Promise.all([intakeRequest<DeliveryPackage>(base+'/package',{signal:c.signal}),analysisOnly?Promise.resolve({items:[]}):intakeRequest<{items:AcceptanceEvent[]}>(base+'/acceptances',{signal:c.signal})]);if(live){setPack(p);setEvents(a.items);setError('');if(p.task&&['queued','running'].includes(p.task.status))timer=window.setTimeout(()=>void read(),3000)}}catch(e){if(live)setError(safeError(e,'封包或接受历史读取失败，请重试。'))}}void read();return()=>{live=false;c.abort();window.clearTimeout(timer)}},[base,active,visible,valid,reload,analysisOnly])
 useEffect(()=>{if(packageOp.value){setPack(packageOp.value);setReload(r=>r+1)}},[packageOp.value])
 useEffect(()=>{if(acceptOp.value){setEvents(old=>[...old.filter(e=>e.id!==acceptOp.value!.id),acceptOp.value!]);setAccept({...accept,scope:'',reservations:'',comment:'',customer_reply:null,corrects_event_id:null,kind:'accept'})}},[acceptOp.value])
 if(!valid)return null
 return <>{error&&<p role="alert">{t(error)}</p>}<button type="button" disabled={packageOp.busy||acceptOp.busy||!active} onClick={()=>setReload(r=>r+1)}>{t(analysisOnly?'刷新 ZIP 状态':'读回原封包与接受记录')}</button><ModuleViews label={t(analysisOnly?'生成和下载 ZIP':'封包与接受')}><ModuleView id="download" title={t('封包与鉴权下载')}>
  {pack?.task?<><p role="status">{t(pack.task.status==='succeeded'?'已完成':pack.task.status==='failed'?'执行失败':pack.task.status==='queued'?'待执行':'运行中')} · {t(pack.progress?.stage?deliveryStageLabels[pack.progress.stage]??'阶段信息待核对':'尚无阶段记录')}{pack.progress?.stage==='source_verification'&&typeof pack.progress.total_members==='number'&&<span> {pack.progress.completed_members??'—'} / {pack.progress.total_members} {t('所选成员')}</span>}</p>{typeof pack.progress?.stage_elapsed_seconds==='number'&&<p>{t('此阶段已记录耗时')} {pack.progress.stage_elapsed_seconds.toFixed(1)} {t('秒')} · {t('第几次尝试')} {pack.progress.attempt_no??'—'}</p>}{pack.progress?.stages&&<section aria-label={t('已记录阶段与耗时')}><ol>{pack.progress.stages.map((p,i)=><li key={i}>{t(deliveryStageLabels[p.stage]??'阶段信息待核对')} · {p.started_at} → {p.ended_at??t('尚未结束')} · {p.elapsed_seconds.toFixed(1)} {t('秒')}</li>)}</ol></section>}<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(pack.task.id)}`}>{t(pack.task.status==='failed'&&!containsPdf?'查看任务并恢复原任务':'查看原封包任务')}</a></>:!containsPdf&&<button type="button" disabled={!pack||packageOp.busy||packageOp.unknown||!active} onClick={()=>void packageOp.submit('package',base+'/package',{},base+'/package')}>{t('创建此快照的统一 ZIP')}</button>}
  {pack?.download_url&&!containsPdf&&<ProjectDownloadLink href={pack.download_url} filename={analysisOnly?`${t('分析交付')} - ${t(stageName(s.stage))} - ${new Date(s.created_at).toLocaleDateString('sv-SE')} ${new Date(s.created_at).toLocaleTimeString('sv-SE').replaceAll(':','-')}.zip`:`delivery-${s.id}.zip`}>{t('下载此固定交付 ZIP')}</ProjectDownloadLink>}<OperationStatus operation={{...packageOp,retryable:packageOp.retryable&&!containsPdf}}/>
  </ModuleView>{!analysisOnly&&<ModuleView id="history" title={t('接受记录')}><h4>{t('独立接受事件（追加保存）')}</h4><p>{t('由当前有权用户记录；客户回复为所提供文本，不代表客户本人登录。')}</p><ul>{events.map(e=><li key={e.id}>{t(e.kind==='accept'?'接受记录':'纠正记录')} · {t('当前有权用户记录')} · {new Date(e.created_at).toLocaleString(locale)}<p>{e.scope}</p><p>{e.reservations}</p><p>{e.comment}</p>{e.customer_reply&&<blockquote>{e.customer_reply}</blockquote>}<p>{t('已绑定此交付版本')}{e.corrects_event_id&&' · '+t('包含对原接受事件的纠正')}</p></li>)}</ul>
  </ModuleView>}{!analysisOnly&&<ModuleView id="acceptance" title={t('追加接受或纠正记录')}><fieldset disabled={acceptOp.busy||acceptOp.unknown||!active}><legend>{t('追加接受或纠正记录')}</legend><label>{t('记录类型')}<select value={accept.kind} onChange={e=>setAccept({...accept,kind:e.target.value as AcceptanceWrite['kind'],corrects_event_id:null})}><option value="accept">{t('接受明确范围')}</option><option value="correction">{t('追加纠正说明')}</option></select></label>{accept.kind==='correction'&&<label>{t('纠正的原事件')}<select value={accept.corrects_event_id??''} onChange={e=>setAccept({...accept,corrects_event_id:e.target.value||null})}><option value="">{t('请选择原接受事件')}</option>{events.map(e=><option key={e.id} value={e.id}>{new Date(e.created_at).toLocaleString(locale)} · {e.scope}</option>)}</select></label>}
   <label>{t('明确接受范围')}<textarea value={accept.scope} maxLength={8000} onChange={e=>setAccept({...accept,scope:e.target.value})}/></label><label>{t('保留项')}<textarea value={accept.reservations} maxLength={8000} onChange={e=>setAccept({...accept,reservations:e.target.value})}/></label><label>{t('接受或纠正意见')}<textarea value={accept.comment} maxLength={8000} onChange={e=>setAccept({...accept,comment:e.target.value})}/></label><label>{t('所提供的客户回复（可空）')}<textarea value={accept.customer_reply??''} maxLength={16000} onChange={e=>setAccept({...accept,customer_reply:e.target.value||null})}/></label><p>{t('本次记录绑定当前查看的固定交付版本')} {s.revision}</p><button type="button" disabled={!accept.scope.trim()||!accept.comment.trim()||accept.kind==='correction'&&!accept.corrects_event_id} onClick={()=>void acceptOp.submit('acceptance',base+'/acceptances',{...accept,snapshot_sha256:s.sha256},base+'/acceptances')}>{t('追加本次记录')}</button>
  </fieldset></ModuleView>}</ModuleViews>{!analysisOnly&&<OperationStatus operation={acceptOp}/>}</>
}

function DelimitedInput({value,onChange,placeholder}:{value:string[];onChange:(value:string[])=>void;placeholder?:string}){const canonical=value.join(','),[raw,setRaw]=useState(canonical);useEffect(()=>{if(lines(raw).join(',')!==canonical)setRaw(canonical)},[canonical]);return <input value={raw} placeholder={placeholder} onChange={e=>{setRaw(e.target.value);onChange(lines(e.target.value))}}/>}
