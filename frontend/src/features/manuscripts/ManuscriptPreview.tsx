import {systemCheckText} from '../../shared/i18n/systemChecks'
import {useId,useState,useEffect,type CSSProperties} from 'react'
import ReviewSnapshot from './ReviewSnapshot'
import ManuscriptImage from './ManuscriptImage'
import { useI18n, translateForLocale } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { methodFields, methodLabels, sectionLabels, type SectionId, type MethodField, type Paragraph, type Snapshot } from './manuscriptTypes'
import PaperPlanSummary from './PaperPlanSummary'
import {chapterGroups,plannedSectionTitle} from './paperPlan'
type Props={customerSci?:boolean;customerView?:boolean;snapshot:Snapshot;label?:string;presentation?:'full'|'body'|'evidence'}
const savedScopeNotice = '根据项目需求和关联资料整理的事实稿。请核对发现及其依据，再继续写作。'
export default function ManuscriptPreview({snapshot,label='事实稿预览',presentation='full',customerSci=false,customerView=false}:Props){
 const {t,locale}=useI18n();const referencePrefix=useId();const out=(s:string)=>translateForLocale(s,snapshot.output_language)
 const [referenceTarget,setReferenceTarget]=useState<{number:number}|null>(null)
 useEffect(()=>{if(!referenceTarget)return;const node=document.getElementById(`${referencePrefix}-reference-${referenceTarget.number}`);node?.scrollIntoView?.({block:'center'});node?.focus()},[referenceTarget,referencePrefix])
 function openReference(number:number){if(presentation==='body')setChapter(snapshot.sections?.find(s=>s.purpose==='references')?.id??'references');setReferenceTarget({number})}
 const origin=(p:Paragraph)=>out(p.origin==='model_generated'?(snapshot.writing_provenance?.schema_version===2&&p.verification_status==='scientific_reviewed'?'已记录新文本人工科学审核':'写作候选，尚未经研究人员核实'):p.origin==='image_observation'?'图像观察，不作为统计结论':p.origin==='computed_result'?'本研究固定统计结果':p.origin==='literature'?'外部文献发现':'用户提供资料')
 const labels=new Map(snapshot.sources.map(s=>[s.id,s.label]))
 const display=snapshot.journal_display_context
 const frontiers=display?.frontiers_review
 const visibleIssues=(customerSci||customerView)&&snapshot.article_type==='narrative_review'&&!snapshot.thesis_context
  ? snapshot.issues.filter(issue=>!(issue.kind==='missing'&&issue.id==='missing:'+issue.field
    &&(issue.field==='results'||methodFields.includes(issue.field as MethodField))))
  : snapshot.issues
 function issueText(issue:Snapshot['issues'][number]){
  if(customerView&&issue.id==='scope'&&issue.kind==='limitation'&&(
   issue.message===savedScopeNotice||issue.message===translateForLocale(savedScopeNotice,'en')
  ))return t('这些材料来自项目需求和已关联的资料。继续写作前，请核对结果与来源。')
  const provenance=snapshot.writing_provenance
  if(customerView&&snapshot.thesis_context&&issue.id==='scope'&&issue.field==='scope'&&issue.kind==='limitation'&&
   provenance?.school_content_version==='school-live-v1'&&['openai_live','synthetic_fixture'].includes(provenance.provider_provenance)){
   const live=provenance.provider_provenance==='openai_live'
   const source=live?'真实模型回执；研究数据来源仍须独立核对。':'合成模型调用替身，未执行真实模型调用。'
   for(const state of ['科学审核已完成；逐章语言与学校导出仍待核对。','科学与逐章语言审核待完成。']){
    const matches=(['zh-CN','en'] as const).some(language=>{
     const saved=(text:string)=>translateForLocale(text,language)
     return issue.message===saved('冻结学校章节候选')+'. '+saved(state)+' '+saved(source)
    })
    if(matches){
     const status=provenance.verification_status==='scientific_and_language_reviewed'
      ?'这份稿件按学校章节整理，已完成科学与语言核对。'
      :state==='科学审核已完成；逐章语言与学校导出仍待核对。'
       ?'这份稿件按学校章节整理，已完成科学核对。请继续核对各章语言和 Word 排版。'
       :'这份稿件按学校章节整理，请核对科学内容和各章语言。'
     return [t(status),t(live?'内容由模型生成，数据来源仍需独立核对。':'这份示例使用模拟内容，未调用模型。')].join(locale==='en'?' ':'')
    }
   }
  }
  return systemCheckText(issue.message)||t('检查说明不可用，请核对原始记录。')
 }
 const completedSchool=snapshot.thesis_context&&snapshot.writing_provenance?.schema_version===2&&snapshot.writing_provenance.school_content_version==='school-live-v1'&&snapshot.writing_provenance.verification_status==='scientific_and_language_reviewed'
 const chapters=snapshot.sections?.map(section=>({id:section.id,title:plannedSectionTitle(snapshot,section.id)??out(sectionLabels[section.id as SectionId]??section.id)}))??[{id:'results',title:out('结果')},{id:'materials_and_methods',title:out('材料与方法')},...(snapshot.references.length?[{id:'references',title:out('参考文献')}]:[])]
 const [chapter,setChapter]=useState(()=>chapters.some(c=>c.id==='abstract')?'abstract':snapshot.sections?.[0]?.id??(snapshot.results_groups.length?'results':'materials_and_methods'))
 const showSection=(id:string)=>presentation!=='body'||chapter==='all'||chapter===id||!!snapshot.sections?.some(section=>section.id===id&&section.parent_id===chapter)
 const titleParagraphIds=new Set(display?snapshot.sections?.find(section=>section.id==='title')?.paragraphs.map(p=>p.id):[])
 const single=frontiers?.single_spacing?{lineHeight:1}:undefined
 const style=(scope:'heading'|'body'):CSSProperties|undefined=>{if(!display)return undefined;const s=display.styles;return {fontSize:s[`${scope}_font_size_pt`]===undefined?undefined:`${s[`${scope}_font_size_pt`]}pt`,lineHeight:single?.lineHeight??s[`${scope}_line_spacing`],marginTop:s[`${scope}_space_before_pt`]===undefined?undefined:`${s[`${scope}_space_before_pt`]}pt`,marginBottom:s[`${scope}_space_after_pt`]===undefined?undefined:`${s[`${scope}_space_after_pt`]}pt`}}
 const paragraph=(p:Paragraph)=><div key={p.id} className="manuscript-paragraph"><p style={titleParagraphIds.has(p.id)?single:style('body')}>{p.text}{p.citations.length>0&&<small className="manuscript-reference-links"> {p.citations.map(c=>typeof c==='number'?c:snapshot.references.find(r=>r.project_reference_id===c.project_reference_id)?.number).filter((n):n is number=>typeof n==='number').map(n=><a key={n} href={`#${referencePrefix}-reference-${n}`} onClick={event=>{event.preventDefault();openReference(n)}}>{out('引用依据')} {n}</a>)}</small>}</p><small>{origin(p)}{p.source_ids.length>0&&<> · {p.source_ids.map(id=>labels.get(id)??out('已冻结来源')).join('; ')}</>}</small>{p.cross_references?.length? <p><small>{out(customerSci||customerView?'文中引用的图表':'冻结图表引用')} · {p.cross_references.map((r,i)=><span key={i}>{i>0?'；':''}{out(r.kind==='figure'?'图':'表')} {r.number}{r.panel_label??''}</span>)}</small></p>:null}</div>
 const renderGroup=(g:Snapshot['results_groups'][number],omitHeading=false)=><section key={g.id} className="manuscript-results">{!omitHeading&&<h5>{g.title}</h5>}{!snapshot.sections&&g.paragraphs.map(paragraph)}
 {g.tables.map(table=><div className="field-table-scroll" key={table.id}><table className="field-table"><caption>{table.number!==undefined&&!new RegExp(`^\\s*(?:表\\s*|Table\\s+)${table.number}(?=$|[\\s.．:：、])`,'i').test(table.title)?`${out('表')} ${table.number}. `:''}{table.title}</caption><thead><tr>{table.columns.map((c,i)=><th key={i} scope="col">{c}</th>)}</tr></thead><tbody>{table.rows.map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>)}
 {g.figures.map(f=>{const source=snapshot.sources.find(s=>s.id===f.id||f.source_ids.includes(s.id));const imageUrl=f.preview_url??f.download_url??(source&&['original','figure','figure_language_version'].includes(source.kind)?source.download_url:null);return <figure key={f.id}>{imageUrl&&<ManuscriptImage key={imageUrl} url={imageUrl} title={f.title}/>}<figcaption><strong>{out('图')} {f.number}. {f.title}</strong><p>{f.caption}</p>{f.panels?.map((p,i)=><p key={i}><b>{p.label}</b> {p.description}</p>)}<small>{out(f.caption_status==='candidate'?'候选图注，需人工补充与确认':f.caption_status==='missing'?'图注缺失，待补充':f.caption_status==='supplied'||f.caption_origin==='user_provided'?'用户提供图注':'来源图注')}</small>{source?.download_url&&<p><ProjectDownloadLink href={source.download_url} filename={source.label}>{t('查看来源文件')}</ProjectDownloadLink></p>}</figcaption></figure>})}
 </section>
 const articleGroups=(id:string)=>{
  const section=snapshot.sections?.find(s=>s.id===id)
  if(section?.result_group_ids)return snapshot.results_groups.filter(group=>section.result_group_ids?.includes(group.id)&&(!section.parent_id||group.figures.length||group.tables.length)).map(group=>renderGroup(group,!!section.parent_id))
  return id==='results'||id==='validation'?snapshot.results_groups.map(group=>renderGroup(group)):null
 }
 const showKeywords=showSection('title')||!!snapshot.paper_plan&&(!snapshot.sections||showSection('abstract')||!!snapshot.sections.some(section=>section.purpose==='abstract'&&showSection(section.id)))
 return <section data-presentation={presentation} className="manuscript-preview manuscript-panel" aria-label={t(label)} lang={snapshot.output_language}>
 <h3 style={single}>{snapshot.title}</h3>{!customerView&&!completedSchool&&<p className="warning-panel">{snapshot.notice}</p>}
 {snapshot.writing_provenance?.schema_version===2&&<div>{!customerView&&<p>{t(snapshot.writing_provenance.provider_provenance==='openai_live'?'真实 provider 回执':'离线模拟回执 / 演示用量')}</p>}<p>{t(customerView?'请对照本版资料，独立核对研究数据的来源。':'研究数据属性须按冻结来源独立核对。')}</p><p>{t(snapshot.writing_provenance.verification_status==='scientific_and_language_reviewed'?'已记录人工科学与语言审核；不等同科学有效性证明。':snapshot.writing_provenance.verification_status==='scientific_reviewed_language_pending'?'已记录人工科学审核；完整语言审核待完成。':'科学审核待完成。')}</p></div>}
 {snapshot.writing_provenance?.provider_provenance==='synthetic_fixture'&&<p className="warning-panel">{t('合成模拟材料，仅验证流程，不代表真实模型效果。')}</p>}
 {snapshot.journal_adaptation_provenance?.synthetic===true&&<p className="warning-panel">{t('期刊适配使用了合成指南或稿件输入，仅验证离线工程，不代表真实期刊适配验收。')}</p>}
 {snapshot.journal_adaptation_provenance&&<p><a href={customerSci?`#customer-project=${encodeURIComponent(snapshot.project_id)}&step=journals&view=adaptation&adaptation=${encodeURIComponent(snapshot.journal_adaptation_provenance.adaptation_id)}`:`#project=${encodeURIComponent(snapshot.project_id)}&section=journals&adaptation=${encodeURIComponent(snapshot.journal_adaptation_provenance.adaptation_id)}`}>{t('查看期刊适配依据')}</a>{!customerView&&<> · {snapshot.journal_adaptation_provenance.base_version_id} · {snapshot.journal_adaptation_provenance.display_version}</>}</p>}
 {presentation==='body'&&<label className="manuscript-chapter-picker">{t('正文章节')}<select value={chapter} onChange={e=>{setChapter(e.target.value);setReferenceTarget(null)}}>{chapters.map(item=><option key={item.id} value={item.id}>{item.title}</option>)}<option value="all">{t('全文阅读')}</option></select></label>}
 <div hidden={presentation==='evidence'}>
 {display?<>{display.order.filter(showSection).map(id=>{const s=snapshot.sections?.find(s=>s.id===id),Heading=s?.level===2||frontiers?.headings&&id==='conclusion'?'h5':'h4';return <section key={id} data-section-id={id}><Heading style={id==='title'||Heading==='h5'?single:style('heading')}>{display.names[id]}</Heading>{id!=='references'&&s?.paragraphs.map(paragraph)}{articleGroups(id)}{id==='references'&&<ol style={single}>{snapshot.references.map((r,index)=><li key={r.number} tabIndex={-1} id={`${referencePrefix}-reference-${r.number}`} value={r.number}>{frontiers?.reference_texts?.[index]??r.text}</li>)}</ol>}</section>})}</>:snapshot.thesis_context?<>{snapshot.sections?.filter(s=>showSection(s.id)).map(s=><section key={s.id} lang={s.output_language} data-chapter-id={s.id}><h4 aria-level={Math.min(6,3+(s.level??1))}>{s.title}</h4>{s.purpose!=='references'&&s.paragraphs.map(paragraph)}{chapterGroups(snapshot,s).map(group=>renderGroup(group,!!snapshot.paper_plan&&group.title===s.title))}{s.purpose==='references'&&<ol>{snapshot.references.map(r=><li key={r.number} tabIndex={-1} id={`${referencePrefix}-reference-${r.number}`} value={r.number}>{r.text}</li>)}</ol>}</section>)}{snapshot.school_content_report&&<section aria-label={t('学校内容检查')}><h4>{t('学校内容检查')}</h4><p>{t('内容检查不等同于学校排版验收或科学有效性证明。')}</p>{snapshot.school_content_report.issues.map(i=><p key={i.id} role={i.severity==='error'?'alert':undefined}>{(systemCheckText(i.message)||t('检查说明不可用，请核对原始记录。'))}</p>)}</section>}</>:snapshot.article_type?<>{snapshot.sections?.filter(s=>s.id!=='references'&&showSection(s.id)).map(s=><section key={s.id} data-section-id={s.id}>{s.level===2?<h5>{plannedSectionTitle(snapshot,s.id)}</h5>:<h4>{plannedSectionTitle(snapshot,s.id)}</h4>}{s.paragraphs.map(paragraph)}{articleGroups(s.id)}</section>)}</>:<> {snapshot.sections?.filter(s=>['title','abstract','introduction'].includes(s.id)&&showSection(s.id)).map(s=><section key={s.id}><h4>{out(sectionLabels[s.id as SectionId])}</h4>{s.paragraphs.map(paragraph)}</section>)}
 {showSection('results')&&<><h4>{out('结果')}</h4>{snapshot.sections?.find(s=>s.id==='results')?.paragraphs.map(paragraph)}{snapshot.results_groups.map(group=>renderGroup(group))}</>}
 {snapshot.sections?.filter(s=>s.id==='discussion'&&showSection(s.id)).map(s=><section key={s.id}><h4>{out(sectionLabels[s.id as SectionId])}</h4>{s.paragraphs.map(paragraph)}</section>)}
 {showSection('materials_and_methods')&&<><h4>{out('材料与方法')}</h4>{(snapshot.sections?.find(s=>s.id==='materials_and_methods')?.paragraphs??snapshot.methods).map(paragraph)}</>}
</>}
 </div>
 <div hidden={presentation==='body'}><h4>{out('资料问题与待办')}</h4>{visibleIssues.length===0?<p>{out('未发现待补充项；仍需核对原始资料。')}</p>:<ul className="manuscript-issues">{visibleIssues.map(issue=><li key={issue.id}><strong>{out(issue.kind==='conflict'?'待核实':issue.kind==='missing'?'待补充':'范围限制')}</strong>{' · '}{out(methodLabels[issue.field as MethodField]??'研究资料')}<p>{issueText(issue)}</p>{issue.values.length>0&&<ul>{issue.values.map((v,i)=><li key={i}>{v}</li>)}</ul>}</li>)}</ul>}
 </div><div hidden={presentation==='evidence'}>
 {showSection('references')&&!display&&!snapshot.thesis_context&&(snapshot.references.length>0||snapshot.sections)&&<><h4>{out('参考文献')}</h4><ol>{snapshot.references.map(r=><li key={r.number} tabIndex={-1} id={`${referencePrefix}-reference-${r.number}`} value={r.number}>{r.text}</li>)}</ol></>}
 {showKeywords&&snapshot.keywords&&<><h4>{out('关键词')}</h4><p>{snapshot.keywords.join('; ')}</p></>}{showSection('title')&&!snapshot.thesis_context&&snapshot.acknowledgements&&<><h4>{out('致谢')}</h4><p>{snapshot.acknowledgements}</p></>}
 </div><div hidden={presentation==='body'}>
 {presentation==='evidence'&&snapshot.paper_plan&&<PaperPlanSummary plan={snapshot.paper_plan} heading="本版写作要求和图表材料"/>}{snapshot.review&&<ReviewSnapshot review={snapshot.review} customerView={customerView}/>}{snapshot.review_history?.map((history,i)=><ReviewSnapshot key={i} review={history.review} historical customerView={customerView}/>)}
 {!customerView&&completedSchool&&<p>{snapshot.notice}</p>}{snapshot.thesis_context&&<section><h4>{t(customerView?'本版使用的学校模板':'冻结学校配置')}</h4><p>{snapshot.thesis_context.profile.school}{!customerView&&' · '+snapshot.thesis_context.profile.applicable_version}</p></section>}<section><h4>{t(customerView?'本版资料与依据':'冻结来源与依据')}</h4><ul>{snapshot.sources.map(s=><li key={`${s.kind}:${s.id}`}><strong>{s.label}</strong>{' · '}{out(s.role==='computed_results'?'本研究固定统计结果':s.role==='literature'?'外部文献发现':s.role==='image_observation'?'图像观察，不作为统计结果':'用户提供资料')}{s.download_url&&<> · <ProjectDownloadLink href={s.download_url} filename={s.label}>{t('查看来源文件')}</ProjectDownloadLink></>}</li>)}</ul></section>
 </div></section>
}
