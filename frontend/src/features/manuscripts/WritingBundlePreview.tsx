import {useEffect,useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {object,wireDigest,dollars,type Bundle} from './writingLiveTypes'
import type {Snapshot} from './manuscriptTypes'
import {plannedSectionTitle} from './paperPlan'
export function MaterialTree({value}:{value:unknown}){if(Array.isArray(value))return <ol>{value.map((v,i)=><li key={i}><MaterialTree value={v}/></li>)}</ol>;if(object(value))return <dl>{Object.entries(value).map(([k,v])=><div key={k}><dt>{k}</dt><dd><MaterialTree value={v}/></dd></div>)}</dl>;return <span style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{value===null?'null':String(value)}</span>}
const records=(value:unknown)=>Array.isArray(value)?value.filter(object):[]
const strings=(value:unknown)=>Array.isArray(value)?value.filter((item):item is string=>typeof item==='string'):[]
const omittedLabels:Record<string,string>={
 attachments:'文件附件',binary_images:'图片的像素原件',local_paths:'本机文件路径',private_configuration:'私有配置',
 unselected_sources:'未选择的来源与段落',prior_reviews:'以往复核记录',school_identity:'学校与个人身份字段',
 manual_chapters:'声明、签名等人工章节',school_template:'学校模板原件',
}

function WireText({value}:{value:unknown}){
 return typeof value==='string'&&value?<p className="paper-plan-note">{value}</p>:null
}

function WireTable({columns,rows}:{columns:string[];rows:string[][]}){
 return <div className="field-table-scroll"><table className="field-table">
  <thead><tr>{columns.map((cell,index)=><th scope="col" key={index}>{cell}</th>)}</tr></thead>
  <tbody>{rows.map((row,index)=><tr key={index}>{row.map((cell,column)=><td key={column}>{cell}</td>)}</tr>)}</tbody>
 </table></div>
}

function ReadableWritingBundle({bundle,snapshot,wire,verified,failed}:{bundle:Bundle;snapshot:Snapshot;wire:unknown;verified:boolean;failed:boolean}){
 const {t}=useI18n()
 const [view,setView]=useState<'content'|'omitted'|'request'>('content')
 const input:Record<string,unknown>=object(wire)&&object(wire.input)?wire.input:{}
 const headings=new Map<string,string>()
 for(const section of records(input.article_structure))if(typeof section.id==='string'&&typeof section.heading==='string')headings.set(section.id,section.heading)
 for(const section of records(input.chapters))if(typeof section.alias==='string'&&typeof section.title==='string')headings.set(section.alias,section.title)
 const sectionTitle=(id:unknown)=>typeof id==='string'?(headings.get(id)??plannedSectionTitle(snapshot,id)):undefined
 const targetIds=object(input.writing_scope)?strings(input.writing_scope.output_section_ids):typeof input.target_section==='string'?[input.target_section]:[...headings.keys()]
 const names=targetIds.map(sectionTitle).filter((name):name is string=>!!name)
 const keywords=strings(input.keywords)
 const sources=records(input.sources)
 const sourceLabels=new Map(snapshot.sources.map(source=>[source.id,source.label]))
 const notes=records(input.paper_notes).filter(note=>typeof note.text==='string')
 const evidence=records(input.evidence).filter(item=>typeof item.quote==='string')
 const paragraphs=records(input.context).filter(section=>records(section.paragraphs).length)
 const illustrations=records(input.illustrations)
 const shownText=new Set([
  ...paragraphs.flatMap(section=>records(section.paragraphs).map(paragraph=>paragraph.text)),
  ...notes.map(note=>note.text),
  ...illustrations.flatMap(item=>[item.title,item.caption,...records(item.panels).map(panel=>panel.description)]),
 ])
 const additionalText=[...new Set(records(input.numeric_context)
  .filter(item=>item.origin==='user_provided'&&typeof item.text==='string'&&!shownText.has(item.text))
  .map(item=>String(item.text)))]
 const omitted=strings(bundle.omitted_manifest).filter(key=>Object.hasOwn(omittedLabels,key))
 return <section aria-label={t('完整外发材料')}>
  <h4>{t('完整外发材料')}</h4>
  <p>{snapshot.title} · {t('固定版本 {number}',{number:bundle.request_json.base_revision})}</p>
  <p role={failed?'alert':'status'}>{t(failed?'发送材料未通过完整性核对，无法授权或执行。':verified?'已核对发送材料。此次预览未调用模型。':'正在核对发送材料……')}</p>
  <p>{t('模型')} {bundle.policy_json.model} · {t('单次预留')} {dollars(bundle.reserved_micro_usd)}</p>
  <p>{t('授权并提交后，后台响应会由模型服务商保存。')}</p>
  <nav className="manuscript-view-nav" aria-label={t('发送材料视图')}>
   {([['content','发送内容'],['omitted','未外发材料清单'],['request','完整请求原文']] as const).map(([id,label])=>
    <button type="button" key={id} aria-pressed={view===id} onClick={()=>setView(id)}>{t(label)}</button>)}
  </nav>
  {view==='omitted'&&<ul>{omitted.map(key=><li key={key}>{t(omittedLabels[key])}</li>)}</ul>}
  {view==='request'&&<pre className="paper-plan-note" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{bundle.wire_json}</pre>}
  {view==='content'&&<>
  {names.length>0&&<p><strong>{t('写作章节')}</strong> · {names.join(' · ')}</p>}
  {keywords.length>0&&<p><strong>{t('关键词')}</strong> · {keywords.join(' · ')}</p>}
  {typeof input.instructions==='string'&&input.instructions&&<p className="paper-plan-note"><strong>{t('写作要求')}</strong> · {input.instructions}</p>}
  {typeof input.acknowledgements==='string'&&input.acknowledgements&&<><h5>{t('致谢')}</h5><WireText value={input.acknowledgements}/></>}
  {paragraphs.length>0&&<section><h5>{t('将发送的原稿与方法段落')}</h5>
   {paragraphs.map((section,index)=><article key={index}>
    <h6>{sectionTitle(section.id)??t('正文')}</h6>
    {records(section.paragraphs).map((paragraph,position)=><WireText key={position} value={paragraph.text}/>)}
   </article>)}
  </section>}
  {sources.length>0&&<section><h5>{t('已选来源')}</h5>
   {sources.map((source,index)=>{
    const label=typeof source.alias==='string'?sourceLabels.get(bundle.local_manifest.sources[source.alias]):undefined
    const facts=records(source.facts),labels=records(source.labels),methods=records(source.methods)
    return <article key={index}>
     <h6>{label??t('来源 {number}',{number:index+1})}</h6>
     <WireText value={source.report_text}/>
     {source.report_text_truncated===true&&<p>{t('发送的是固定报告摘录。')}</p>}
     {methods.map((method,position)=><div key={position}>
      <WireText value={method.title}/><WireText value={method.description}/>
      {method.parameters!==undefined&&<><strong>{t('方法参数')}</strong><MaterialTree value={method.parameters}/></>}
      {method.software!==undefined&&<><strong>{t('软件')}</strong><MaterialTree value={method.software}/></>}
     </div>)}
     {labels.map((item,position)=><WireText key={position} value={item.value}/>)}
     {facts.length>0&&<WireTable columns={[t('数值位置'),t('数值')]} rows={facts.map(fact=>[
      String(fact.label??fact.fact_path??''),String(fact.value??''),
     ])}/>}
     {[...strings(source.gaps),...strings(source.warnings)].map((value,position)=><WireText key={position} value={value}/>)}
    </article>
   })}
  </section>}
  {additionalText.length>0&&<section><h5>{t('将发送的补充方法与结果')}</h5>
   {additionalText.map(value=><WireText key={value} value={value}/>)}
  </section>}
  {notes.length>0&&<><h5>{t('已选的写作材料')}</h5>{notes.map((note,index)=><article key={index}>{sectionTitle(note.section_id)&&<strong>{sectionTitle(note.section_id)}</strong>}<p className="paper-plan-note">{String(note.text)}</p></article>)}</>}
  {illustrations.length>0&&<section><h5>{t('将发送的图表文字与数值')}</h5>
   {illustrations.map((item,index)=><article key={index}>
    <h6>{t(item.kind==='table'?'表':'图')} {String(item.number??'')} {sectionTitle(item.section_id)}</h6>
    <WireText value={item.title}/><WireText value={item.caption}/>
    {item.kind==='table'?<WireTable columns={strings(item.columns)} rows={Array.isArray(item.rows)?item.rows.map(strings):[]}/>:<>
     {records(item.panels).map((panel,position)=><p key={position} className="paper-plan-note"><strong>{String(panel.label??'')}</strong> {String(panel.description??'')}</p>)}
    </>}
   </article>)}
  </section>}
  <h5>{t('已选引用证据')}</h5>{evidence.length?evidence.map((item,index)=>{
   const bibliography=object(item.bibliography)?item.bibliography:{}
   const reference=[...strings(bibliography.authors),bibliography.journal,bibliography.year,bibliography.doi].filter(Boolean).join(' · ')
   return <article key={index}>
    {typeof bibliography.title==='string'&&<strong>{bibliography.title}</strong>}
    <WireText value={reference}/><blockquote>{String(item.quote)}</blockquote><WireText value={item.reading_scope}/>
   </article>
  }):<p>{t('未选择已核验的引用证据。')}</p>}
  </>}
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
