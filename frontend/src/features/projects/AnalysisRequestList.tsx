import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {ProjectFile} from '../files/fileLibraryApi'
import type {Version} from '../research-intake/contracts'
import type {AnalysisNavigation} from './analysisViews'
import {analysisScopes,entryMethods,entrySources,scopeKind,sourceNavigation,type AnalysisScope,type EntryMethod,type EntrySource,type EntryImport} from './analysisEntryState'

type Props={focused?:boolean;version:Version;files:ProjectFile[];filesLoading?:boolean;filesError?:string;imports?:EntryImport[];importsUnknown?:boolean;onNavigate:(next:AnalysisNavigation)=>void;onFile?:(id:string)=>void;onRequirements?:()=>void;onReloadFiles?:()=>void;scopeId?:string}
const compatible=(source:EntrySource,method:EntryMethod)=>method.source==='table'?source.kind==='table':method.source==='bio'?['bio-original','bio-version'].includes(source.kind):false
export default function AnalysisRequestList(props:Props){
 const {t}=useI18n(),scopes=analysisScopes(props.version).filter(scope=>!props.scopeId||scope.id===props.scopeId)
 const [selected,setSelected]=useState('');const current=scopes.some(s=>s.id===selected)?selected:scopes[0]?.id
 return <section className="analysis-request-list" aria-label={t('本次分析清单')}>
  <header><h3>{t('本次分析清单')}</h3><span>{t('需求版本 {number}',{number:props.version.version})}</span>{props.onRequirements&&<button type="button" className="button-quiet" onClick={props.onRequirements}>{t('调整分析需求')}</button>}{props.onReloadFiles&&<button type="button" className="button-quiet" onClick={props.onReloadFiles}>{t('重新读取材料')}</button>}</header>
  <p className="muted">{t('选择本次要执行的任务，核对来源后进入配置。')}</p>
  {props.filesLoading&&<p role="status">{t('正在核对材料状态……')}</p>}
  {props.filesError&&<p role="alert">{t('材料读取失败，请重试。')} {props.onReloadFiles&&<button type="button" onClick={props.onReloadFiles}>{t('重新读取材料')}</button>}</p>}
  {!scopes.length&&<p>{t(props.scopeId?'该需求版本中没有此分析条目，请重新选择。':'还没有勾选分析项目。你也可以直接从下方的数据类型开始。')}</p>}
  {props.focused&&scopes.length>1&&<nav className="analysis-task-picker" aria-label={t('选择本次任务')}>{scopes.map(scope=><button type="button" key={scope.id} aria-pressed={scope.id===current} onClick={()=>setSelected(scope.id)}>{t(scope.title)}</button>)}</nav>}
  {scopes.map(scope=><div key={`${props.version.id}:${scope.id}`} hidden={props.focused&&scope.id!==current}><RequestRow {...props} scope={scope}/></div>)}
 </section>
}
function RequestRow({version,scope,files,filesLoading,filesError,imports,importsUnknown,onNavigate,onFile,onRequirements}:Props&{scope:AnalysisScope}){
 const {t}=useI18n(),kind=scopeKind(scope),sources=entrySources(version,kind,files,imports),methods=entryMethods(kind)
 const [chosenMethod,setChosenMethod]=useState(''),[chosenSource,setChosenSource]=useState('')
 // Only the declared raw data type can disambiguate QC or a table comparison.
 const inferable=kind==='qc'||kind==='differential'
 const allTable=sources.length>0&&sources.every(s=>s.kind==='table')
 const allBio=sources.length>0&&sources.every(s=>['bio-original','bio-version'].includes(s.kind))
 const needsImport=sources.some(s=>s.kind==='bio-original')
 const defaultId=methods.length===1?methods[0].id:inferable&&allTable?'table':inferable&&allBio?(kind==='qc'||needsImport?'bio':'comparison'):''
 const method=methods.find(m=>m.id===(chosenMethod||defaultId))
 const candidates=method?sources.filter(s=>compatible(s,method)):[]
 const source=chosenSource?candidates.find(s=>s.key===chosenSource):candidates.length===1?candidates[0]:undefined
 const unread=!!filesLoading||!!filesError||!!importsUnknown&&sources.some(s=>files.some(file=>file.id===s.fileId&&file.parse_status==='stored'))
 const blockedSource=method?.source!=='module'&&source&&!source.ready&&source.kind!=='bio-original'
 const canConfigure=!!method&&!unread&&(method.source==='module'||!!source&&!blockedSource)
 const missing=!!method&&method.source!=='module'&&!candidates.length
 const status=unread?'材料状态尚未核实':!method?'需选择分析方式':method.source==='module'?'待在配置中核对适用来源':missing?'待补充适用材料':!source?'需选择本项来源':source.status
 function open(){if(!method||!canConfigure)return;const entry={requirementVersionId:version.id,scopeItemId:scope.id};let next={...method.navigation,entry};if(method.source==='table')next={...next,fileId:source!.fileId!};if(method.source==='bio')next={...next,...sourceNavigation(source!)};onNavigate(next)}
 return <article className="analysis-request-row" aria-label={scope.title}>
  <header><h4>{t(scope.title)||t('未命名分析需求')}</h4><span className="analysis-preparation-status">{t(status)}</span></header>
  <ul className="analysis-entry-sources">{sources.map(item=><li key={item.key}><span>{item.label}</span><small>{t(unread?'材料状态尚未核实':item.status)}</small>{item.fileId&&onFile&&<button type="button" className="button-quiet" onClick={()=>onFile(item.fileId!)}>{t('查看关联文件')}</button>}</li>)}</ul>
  {!sources.length&&<p>{t('尚未关联本项用途的材料；可返回需求补充，或在配置中选择已有来源。')}</p>}
  {methods.length>1&&<label>{t('分析方式')}<select aria-label={t('分析方式')} value={method?.id??''} onChange={e=>{setChosenMethod(e.target.value);setChosenSource('')}}><option value="">{t('请选择')}</option>{methods.map(m=><option key={m.id} value={m.id}>{t(m.label)}</option>)}</select></label>}
  {(candidates.length>1||chosenSource&&!source&&candidates.length>0)&&<label>{t('本项使用的来源')}<select aria-label={t('本项使用的来源')} value={source?.key??''} onChange={e=>setChosenSource(e.target.value)}><option value="">{t('请选择')}</option>{candidates.map(s=><option key={s.key} value={s.key}>{s.label} · {t(s.status)}</option>)}</select></label>}
  {method&&<p className="muted">{t(method.help)}</p>}
  <div className="intake-actions">{blockedSource&&source?.fileId&&onFile?<button type="button" onClick={()=>onFile(source.fileId!)}>{t('查看材料')}</button>:missing&&onRequirements?<button type="button" onClick={onRequirements}>{t('补充材料关联')}</button>:<button type="button" className="button-primary" disabled={!canConfigure} onClick={open}>{t(method?.source==='bio'&&source?.kind==='bio-original'?source.importId?'继续导入核对':'进入导入核对':'进入配置')}</button>}</div>
 </article>
}
