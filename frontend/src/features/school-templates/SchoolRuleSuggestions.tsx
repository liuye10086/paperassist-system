import {useCallback,useEffect,useRef,useState} from 'react'
import {apiFetch} from '../../shared/api/client'
import {apiError,safeError,useI18n} from '../../shared/i18n'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {readable,type Template} from './contracts'
import {isSuggestionList,isSuggestionPreview,isSuggestionView,suggestionSelection,type SuggestionPreview,type SuggestionSelection,type SuggestionView} from './suggestionContracts'

type Props={projectId:string;item:Template;active:boolean;busy:boolean;onSelection:(selection:SuggestionSelection|null)=>void;onPendingChange:(pending:boolean)=>void;onFork:()=>Promise<void>;onUnavailable:()=>void;registerLeaveGuard?:RegisterLeaveGuard}
const statuses:Record<string,string>={queued:'待执行',running:'运行中',waiting_input:'待补充资料',waiting_confirmation:'待用户确认',succeeded:'已完成',failed:'执行失败'}
const candidateStatuses={proposed:'建议值',conflict:'与原属性冲突',unknown:'无法确定',unsupported:'暂不支持'} as const
const provenance={synthetic_fixture:'合成离线样例',openai_live:'真实 OpenAI 调用'} as const

export default function SchoolRuleSuggestions({projectId,item,active,busy,onSelection,onPendingChange,onFork,onUnavailable,registerLeaveGuard}:Props){
 const {t}=useI18n();const visible=useDocumentVisible()
 const [noteIds,setNoteIds]=useState<string[]>([]);const [preview,setPreview]=useState<SuggestionPreview|null>(null)
 const [views,setViews]=useState<SuggestionView[]>([]);const [selectedId,setSelectedId]=useState('');const [selectedView,setSelectedView]=useState<SuggestionView|null>(null)
 const selectedViewRef=useRef(selectedView);selectedViewRef.current=selectedView
 const [decisions,setDecisions]=useState<Record<string,{action:string;reason:string}>>({})
 const [error,setError]=useState('');const [pending,setPending]=useState(false);const [unknown,setUnknown]=useState(false);const [refresh,setRefresh]=useState(0)
 const life=useRef(new AbortController());const lock=useRef(false);const replay=useRef<{body:string;key:string}|null>(null)
 const base=`/api/v1/projects/${encodeURIComponent(projectId)}`;const templateBase=`${base}/school-templates/${encodeURIComponent(item.id)}`
 const frozen=!!item.confirmation;const analysisSha=item.analysis_sha256??''
 const eligibleIds=item.rule_suggestion_note_eligibility?.eligible_note_ids
 const eligible=(id:string)=>eligibleIds===undefined||eligibleIds.includes(id)
 useEffect(()=>{
  if(pending||unknown||eligibleIds===undefined||!noteIds.some(id=>!eligibleIds.includes(id)))return
  setNoteIds(old=>old.filter(id=>eligibleIds.includes(id)));setPreview(null);replay.current=null
 },[eligibleIds,noteIds,pending,unknown])
 const selection=suggestionSelection(selectedView,decisions)
 useDraftLeaveGuard(registerLeaveGuard,!frozen&&(noteIds.length>0||!!selectedId),pending||unknown)
 useEffect(()=>{if(life.current.signal.aborted)life.current=new AbortController();const controller=life.current;return()=>controller.abort()},[])
 const request=useCallback(async(path:string,init?:RequestInit):Promise<unknown>=>{
  const parent=life.current;const local=new AbortController();const cancel=()=>local.abort();parent.signal.addEventListener('abort',cancel,{once:true});const timer=window.setTimeout(cancel,15000)
  try{
   const response=await apiFetch(path,{...init,signal:local.signal});const value=await response.json().catch(()=>null)
   if(parent.signal.aborted)throw new DOMException('Aborted','AbortError')
   if([401,403].includes(response.status)||response.status===404&&value?.detail?.code==='project_not_found'){onUnavailable();throw new DOMException('Unavailable','AbortError')}
   if(!response.ok)throw new Error(apiError(value,'学校规范建议请求失败，请重试。'))
   return value
  }finally{window.clearTimeout(timer);parent.signal.removeEventListener('abort',cancel)}
 },[onUnavailable])
 useEffect(()=>{
  if(!active||!visible||!analysisSha)return
  let current=true;let timer=0
  async function load(){try{
   const value=await request(`${templateBase}/rule-suggestions`)
   if(!current)return
   if(!isSuggestionList(value,item.id,analysisSha))throw new Error('学校规范建议响应不完整，请刷新核对。')
   setViews(value.items);setError('')
   if(value.items.some(view=>['queued','running'].includes(view.task.status)))timer=window.setTimeout(()=>void load(),3000)
  }catch(cause){if(current&&!life.current.signal.aborted)setError(safeError(cause,'学校规范建议请求失败，请重试。'))}}
  void load();return()=>{current=false;window.clearTimeout(timer)}
 },[active,visible,analysisSha,templateBase,item.id,refresh,request])
 useEffect(()=>{
  if(!active||!visible||!selectedId)return
  let current=true
  void request(`${base}/school-rule-suggestions/${encodeURIComponent(selectedId)}`).then(value=>{
   if(!current)return
   if(!isSuggestionView(value,item.id,analysisSha)||value.id!==selectedId)throw new Error('学校规范建议响应不完整，请刷新核对。')
   if(selectedViewRef.current&&selectedViewRef.current.artifact_sha256!==value.artifact_sha256){onSelection(null);onPendingChange(true);setDecisions({})}
   setSelectedView(value);setError('')
  }).catch(cause=>{if(current&&!life.current.signal.aborted){onSelection(null);onPendingChange(true);setSelectedView(null);setError(safeError(cause,'学校规范建议请求失败，请重试。'))}})
  return()=>{current=false}
 },[active,visible,selectedId,base,item.id,analysisSha,refresh,request,onSelection,onPendingChange])
 useEffect(()=>{
  onSelection(frozen?null:selection);onPendingChange(!frozen&&!!selectedId&&!selection)
  // The serialized payload avoids invalidating a complete selection on unrelated renders.
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[JSON.stringify(selection),frozen,selectedId,onSelection,onPendingChange])
 function invalidate(){onSelection(null);setPreview(null);replay.current=null;setUnknown(false)}
 function selectArtifact(id:string){onSelection(null);onPendingChange(!!id);setSelectedId(id);setSelectedView(null);setDecisions({})}
 function editDecision(id:string,change:Partial<{action:string;reason:string}>){onSelection(null);onPendingChange(true);setDecisions(old=>({...old,[id]:{action:old[id]?.action??'',reason:old[id]?.reason??'',...change}}))}
 async function run(action:()=>Promise<void>){if(lock.current||busy)return;lock.current=true;setPending(true);setError('');try{await action()}catch(cause){if(!life.current.signal.aborted)setError(safeError(cause,'学校规范建议请求失败，请重试。'))}finally{lock.current=false;if(!life.current.signal.aborted)setPending(false)}}
 async function loadPreview(){
  const ids=noteIds.filter(eligible);setPreview(null)
  const value=await request(`${templateBase}/rule-suggestion-preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_sha256:analysisSha,note_ids:ids})})
  if(!isSuggestionPreview(value,item.id,analysisSha,ids))throw new Error('学校规范建议响应不完整，请刷新核对。')
  setPreview(value)
 }
 async function create(){
  if(!preview?.real_calls_enabled||noteIds.some(id=>!eligible(id)))return
  const body=JSON.stringify({analysis_sha256:analysisSha,note_ids:noteIds,bundle_sha256:preview.bundle_sha256,confirmed:true})
  if(replay.current?.body!==body)replay.current={body,key:crypto.randomUUID()}
  try{
   const value=await request(`${templateBase}/rule-suggestions`,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':replay.current.key},body})
   if(!isSuggestionView(value,item.id,analysisSha)||value.bundle_sha256!==preview.bundle_sha256)throw new Error('学校规范建议响应不完整，请刷新核对。')
   setViews(old=>[value,...old.filter(view=>view.id!==value.id)]);setUnknown(false);setRefresh(n=>n+1)
  }catch(cause){setUnknown(true);throw cause}
 }
 async function refreshList(){
  const value=await request(`${templateBase}/rule-suggestions`)
  if(!isSuggestionList(value,item.id,analysisSha))throw new Error('学校规范建议响应不完整，请刷新核对。')
  setViews(value.items);if(preview&&value.items.some(view=>view.bundle_sha256===preview.bundle_sha256))setUnknown(false)
  setRefresh(n=>n+1)
 }
 return <section aria-label={t('学校规范建议')}>
  <h4>{t('学校规范建议')}</h4><p>{t('仅发送明确勾选的规范说明原文；已识别的身份字段来源会排除，原 DOCX 不发送。模型建议须逐项人工决定，不会自动确认或绑定模板。')}</p>
  {error&&<p role="status" className="error-panel">{t(error)}</p>}
  {frozen?<><p>{t('此模板已确认；请基于冻结原件创建修订版后再处理建议。')}</p><button type="button" disabled={busy||pending} onClick={()=>void onFork()}>{t('基于冻结原件创建修订版')}</button></>:<fieldset disabled={busy||pending||unknown}><legend>{t('选择发送的说明原文')}</legend>
   {(item.analysis?.notes??[]).map((note,index)=>{
    const id=typeof note==='string'?undefined:note.id;const text=typeof note==='string'?note:note.text??note.source?.text??readable(note.value??note.message)
    return <div key={id??index}>{id?<label><input type="checkbox" disabled={!eligible(id)} checked={eligible(id)&&noteIds.includes(id)} onChange={event=>{invalidate();setNoteIds(old=>event.target.checked?[...old,id]:old.filter(value=>value!==id))}}/>{text}</label>:<><p>{text}</p><small>{t('此条说明缺少稳定标识，暂不能发送。')}</small></>}{id&&!eligible(id)&&<p>{t('此条含已识别的身份字段来源，不能外发；如同段混有格式规则，请单独补充规范文字。')}</p>}{typeof note!=='string'&&note.source&&<details><summary>{t('查看说明完整原文和位置')}</summary><p className="template-text">{note.source.text}</p><small>{note.source.part} · {note.source.path}</small></details>}</div>
   })}
   {!item.analysis?.notes.length&&<p>{t('没有可选的内嵌说明。')}</p>}
   <button type="button" disabled={!noteIds.some(eligible)||!analysisSha} onClick={()=>void run(loadPreview)}>{t('预览建议发送内容')}</button>
  </fieldset>}
  {preview&&<div><h5>{t('发送预览')}</h5><p>{t('模型')}：{preview.policy.model} · {t('输入 token 上限')}：{preview.input_token_allowance} · {t('费用预留（micro USD）')}：{preview.reserved_micro_usd}</p><details><summary>{t('查看模型政策与价格')}</summary><pre className="template-text">{JSON.stringify(preview.policy,null,2)}</pre></details><p>{t('发送内容 SHA-256')}：{preview.bundle_sha256}</p>
   {preview.notes.map(note=><article key={note.id}><strong>{note.alias}</strong><p className="template-text">{note.text}</p><p>{note.source.path}</p><small>{note.source.part} · {note.sha256}</small></article>)}
   <details><summary>{t('查看可建议的能力与原属性')}</summary><ul>{preview.material.capabilities.map(capability=><li key={capability.id}>{capability.id} · {capability.kind} · {readable(capability.current_value)}</li>)}</ul></details>
   {!preview.real_calls_enabled&&<p role="status">{t('真实模型调用已关闭')}</p>}
   <button type="button" disabled={busy||pending||frozen||!preview.real_calls_enabled||unknown} onClick={()=>void run(create)}>{t('确认发送并生成建议')}</button>
  </div>}
  {unknown&&<><p role="status">{t('建议请求结果尚未确认；请刷新建议列表核对，勿重复创建。')}</p><button type="button" disabled={busy||pending} onClick={()=>void run(create)}>{t('重试同一建议请求')}</button></>}
  <button type="button" disabled={busy||pending} onClick={()=>void run(refreshList)}>{t('刷新建议列表')}</button>
  <ul>{views.map(view=><li key={view.id}>{view.id} · {t(statuses[view.task.status]??'状态未知')}{view.model_calls.map(call=><p key={call.id}>{call.model} · {call.status} · {t(call.provider_provenance?provenance[call.provider_provenance]:'调用来源未记录')} · {call.estimated_cost_micro_usd??'—'} micro USD</p>)}</li>)}</ul>
  <label>{t('纳入确认的建议产物')}<select value={selectedId} disabled={frozen||busy||pending} onChange={event=>selectArtifact(event.target.value)}><option value="">{t('不使用建议产物')}</option>{views.map(view=><option key={view.id} value={view.id} disabled={view.task.status!=='succeeded'||!view.artifact_sha256||!view.result}>{view.id} · {t(statuses[view.task.status]??'状态未知')}</option>)}</select></label>
  {selectedView&&<><p>{t('建议产物 SHA-256')}：{selectedView.artifact_sha256}</p>{selectedView.result?.candidates.map((candidate,index)=><fieldset key={candidate.id} disabled={frozen||busy||pending}><legend>{t('建议 {index}',{index:index+1})} · {t(candidateStatuses[candidate.status])}</legend><p>{candidate.target_id??t('目标未确定')} · {t('建议值')}：{candidate.value??'—'} · {t('原属性')}：{readable(candidate.current_value)}</p><p>{candidate.reason}</p><p>{t('来源引用')} {candidate.note_alias} [{candidate.start}, {candidate.end})：{candidate.quote}</p><details><summary>{t('查看说明完整原文和位置')}</summary><p className="template-text">{candidate.source.text}</p><small>{candidate.source.part} · {candidate.source.path}</small></details>
   {candidate.status==='conflict'&&<p>{t('接受表示采用建议值；拒绝表示保持原属性。')}</p>}
   <label>{t('建议处置 {index}',{index:index+1})}<select value={decisions[candidate.id]?.action??''} onChange={event=>editDecision(candidate.id,{action:event.target.value})}><option value="">{t('请选择处置')}</option>{['proposed','conflict'].includes(candidate.status)&&candidate.source_verified&&<option value="accept">{t('接受建议值')}</option>}<option value="reject">{t('拒绝并保留原属性')}</option><option value="defer">{t('暂缓')}</option></select></label>
   <label>{t('处置理由 {index}',{index:index+1})}<textarea maxLength={2000} value={decisions[candidate.id]?.reason??''} onChange={event=>editDecision(candidate.id,{reason:event.target.value})}/></label>
  </fieldset>)}<p role="status">{t(selection?'逐项处置已完整，将随“确认模板规则”提交。':'请逐项选择处置并填写理由，再确认模板规则。')}</p></>}
 </section>
}
