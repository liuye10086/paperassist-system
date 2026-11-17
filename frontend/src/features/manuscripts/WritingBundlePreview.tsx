import {useEffect,useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {object,wireDigest,dollars,type Bundle} from './writingLiveTypes'
import type {Snapshot} from './manuscriptTypes'
import {plannedSectionTitle} from './paperPlan'
export function MaterialTree({value}:{value:unknown}){if(Array.isArray(value))return <ol>{value.map((v,i)=><li key={i}><MaterialTree value={v}/></li>)}</ol>;if(object(value))return <dl>{Object.entries(value).map(([k,v])=><div key={k}><dt>{k}</dt><dd><MaterialTree value={v}/></dd></div>)}</dl>;return <span style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{value===null?'null':String(value)}</span>}
const records=(value:unknown)=>Array.isArray(value)?value.filter(object):[]
const strings=(value:unknown)=>Array.isArray(value)?value.filter((item):item is string=>typeof item==='string'):[]

function ReadableWritingBundle({bundle,snapshot,wire,verified,failed}:{bundle:Bundle;snapshot:Snapshot;wire:unknown;verified:boolean;failed:boolean}){
 const {t}=useI18n()
 const input:Record<string,unknown>=object(wire)&&object(wire.input)?wire.input:{}
 const headings=new Map<string,string>()
 for(const section of records(input.article_structure))if(typeof section.id==='string'&&typeof section.heading==='string')headings.set(section.id,section.heading)
 for(const section of records(input.chapters))if(typeof section.alias==='string'&&typeof section.title==='string')headings.set(section.alias,section.title)
 const sectionTitle=(id:unknown)=>typeof id==='string'?(headings.get(id)??plannedSectionTitle(snapshot,id)):undefined
 const targetIds=object(input.writing_scope)?strings(input.writing_scope.output_section_ids):typeof input.target_section==='string'?[input.target_section]:[...headings.keys()]
 const names=targetIds.map(sectionTitle).filter((name):name is string=>!!name)
 const keywords=strings(input.keywords)
 const sourceIds=new Set(Object.values(bundle.local_manifest.sources))
 const sources=snapshot.sources.filter(source=>sourceIds.has(source.id))
 const notes=records(input.paper_notes).filter(note=>typeof note.text==='string')
 const evidence=records(input.evidence).filter(item=>typeof item.quote==='string')
 return <section aria-label={t('完整外发材料')}>
  <h4>{t('完整外发材料')}</h4>
  <p>{snapshot.title} · {t('固定版本 {number}',{number:bundle.request_json.base_revision})}</p>
  <p role={failed?'alert':'status'}>{t(failed?'发送材料未通过完整性核对，无法授权或执行。':verified?'已核对发送材料。此次预览未调用模型。':'正在核对发送材料……')}</p>
  <p>{t('模型')} {bundle.policy_json.model} · {t('单次预留')} {dollars(bundle.reserved_micro_usd)}</p>
  <p>{t('授权并提交后，后台响应会由模型服务商保存。')}</p>
  {names.length>0&&<p><strong>{t('写作章节')}</strong> · {names.join(' · ')}</p>}
  {keywords.length>0&&<p><strong>{t('关键词')}</strong> · {keywords.join(' · ')}</p>}
  {typeof input.instructions==='string'&&input.instructions&&<p className="paper-plan-note"><strong>{t('写作要求')}</strong> · {input.instructions}</p>}
  {sources.length>0&&<><h5>{t('已选来源')}</h5><ul>{sources.map(source=><li key={source.id}>{source.label}</li>)}</ul></>}
  {notes.length>0&&<><h5>{t('已选的写作材料')}</h5>{notes.map((note,index)=><article key={index}>{sectionTitle(note.section_id)&&<strong>{sectionTitle(note.section_id)}</strong>}<p className="paper-plan-note">{String(note.text)}</p></article>)}</>}
  <h5>{t('已选引用证据')}</h5>{evidence.length?evidence.map((item,index)=><article key={index}>{object(item.bibliography)&&typeof item.bibliography.title==='string'&&<strong>{item.bibliography.title}</strong>}<blockquote>{String(item.quote)}</blockquote></article>):<p>{t('未选择已核验的引用证据。')}</p>}
 </section>
}

export default function WritingBundlePreview({bundle,onVerified,customerThesis=false,readableSnapshot}:{bundle:Bundle;onVerified?:(sha:string)=>void;customerThesis?:boolean;readableSnapshot?:Snapshot}){
 const {t}=useI18n(),[verified,setVerified]=useState(false),[failed,setFailed]=useState(false)
 useEffect(()=>{let current=true;void wireDigest(bundle.wire_json).then(hash=>{if(!current)return;const matches=hash===bundle.bundle_sha256&&new TextEncoder().encode(bundle.wire_json).length===bundle.wire_bytes;setVerified(matches);setFailed(!matches);if(matches)onVerified?.(hash)}).catch(()=>{if(current)setFailed(true)});return()=>{current=false}},[bundle,onVerified])
 let wire:unknown;try{wire=JSON.parse(bundle.wire_json);if(object(wire)&&typeof wire.input==='string')wire={...wire,input:JSON.parse(wire.input)}}catch{wire=null}
 function download(){const url=URL.createObjectURL(new Blob([bundle.wire_json],{type:'application/json;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=`writing-wire-${bundle.id}.json`;link.click();URL.revokeObjectURL(url)}
 const price=bundle.policy_json.price
 const [reviewView,setReviewView]=useState<'wire'|'raw'|'omitted'>('wire')
 const reviewViews=[
  ['wire','逐项查看外发材料与响应格式',<MaterialTree key="wire" value={wire}/>],
  ['raw','完整 wire（无截断）',<pre key="raw" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{bundle.wire_json}</pre>],
  ['omitted','未外发材料清单',<MaterialTree key="omitted" value={bundle.omitted_manifest}/>],
 ] as const
 if(readableSnapshot)return <ReadableWritingBundle bundle={bundle} snapshot={readableSnapshot} wire={wire} verified={verified} failed={failed}/>
 return <section aria-label={t('完整外发材料')}><h4>{t('完整外发材料')}</h4><p>{t('稿件')} {bundle.manuscript_id} · {t('基础版本')} {bundle.request_json.base_revision} · {bundle.request_json.output_language}</p><p>SHA-256: <code>{bundle.bundle_sha256}</code> · {bundle.wire_bytes} {t('字节')}</p><p role={failed?'alert':'status'}>{t(failed?'完整 wire 哈希校验失败，禁止授权或执行。':verified?'完整 wire 字节与 SHA 已核对。':'正在核对完整 wire……')}</p><p>{bundle.policy_json.model} · {price.version}</p><p>{t('每百万 token：输入 / 缓存输入 / 输出')} {dollars(price.input_micro_usd_per_million)} / {dollars(price.cached_input_micro_usd_per_million)} / {dollars(price.output_micro_usd_per_million)}</p><p>{t('输入保守上限')} {bundle.input_token_allowance} · {t('输出上限')} {bundle.policy_json.max_output_tokens} · {t('单次预留')} {dollars(bundle.reserved_micro_usd)}</p><p><code>https://api.openai.com/v1/responses</code></p><p>{t('固定官方端点；服务等级 default；无工具；不自动重试 POST。后台响应由供应商保存。账户模型可用性未验证。')}</p>{customerThesis?<>
  <nav className="manuscript-view-nav" aria-label={t('完整外发材料')}>{reviewViews.map(([key,label])=><button key={key} type="button" aria-pressed={reviewView===key} onClick={()=>setReviewView(key)}>{t(label)}</button>)}</nav>
  {reviewViews.find(([key])=>key===reviewView)?.[2]}
 </>:reviewViews.map(([key,label,content])=><details key={key}><summary>{t(label)}</summary>{content}</details>)}
 <button type="button" disabled={!verified} onClick={download}>{t('下载完整 wire')}</button></section>
}
