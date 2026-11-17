import {validFrontMatter,type Section} from '../school-templates/contracts'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {ManuscriptVersion} from './manuscriptTypes'
import {manualFieldLabels,type SchoolExportOptions,type SchoolExportPlan,type SchoolExportResult} from './schoolExportTypes'
const pageNumberLabels:Record<string,string>={
 decimal:'阿拉伯数字',upperRoman:'大写罗马数字',lowerRoman:'小写罗马数字',
 upperLetter:'大写字母',lowerLetter:'小写字母',
}
export function SchoolExportDetails({plan,report=plan.report,fieldUpdate,customerView=false}:{plan:SchoolExportPlan;report?:SchoolExportPlan['report'];fieldUpdate?:SchoolExportResult['field_update'];customerView?:boolean}){
 const {t}=useI18n()
 const issueText=(issue:SchoolExportPlan['report']['issues'][number])=>{
  const field=plan.front_matter?.fields.find(f=>issue.id==='school:field:'+f.id||issue.id==='school:signature-review:'+f.id)
  if(field)return t(issue.id.startsWith('school:field:')?'{label}未提供，保留待填写。':'{label}仅为用户提供的文字，签名真实性仍须本人核对。',{label:field.label})
  if(issue.id.startsWith('school:required-content:')){const chapter=plan.chapters.find(c=>!!c&&typeof c==='object'&&'id'in c&&c.id===issue.location) as {title?:string}|undefined;return t('{title}正文待用户提供。',{title:chapter?.title??(customerView?t('稿件章节'):issue.location)})}
  return t(issue.message)
 }
 if(customerView){
  const pages=plan.sections as (Pick<Section,'page_number'>&{chapter_id:string})[]
  const chapters=plan.chapters as {id:string;title:string}[]
  const checks=Array.from(new Map(report.issues.map(issue=>{
   const message=issueText(issue)
   return [issue.severity+'\n'+message,{...issue,message}] as const
  })).values())
  return <section className="school-export-details" aria-label={t('学校缺项与限制')}>
   <h4>{t('学校缺项与限制')}</h4>
   <p role={report.can_export?'status':'alert'}>{t(report.can_export?'学校检查允许工程导出。':'学校检查存在阻止导出的错误。')}</p>
   {checks.length>0&&<ul>{checks.map(issue=><li key={issue.id}>
    <strong>{t({error:'错误',warning:'警告',human_review:'人工核对'}[issue.severity])}</strong> · {issue.message}
   </li>)}</ul>}
   <h4>{t('分节与目录')}</h4>
   <p>{t(plan.toc.enabled?'包含目录':'不含目录')}{plan.toc.enabled&&<> · {t('目录深度')} {plan.toc.depth}</>}</p>
   <ul>{pages.map((page,index)=><li key={index}>
    {chapters.find(chapter=>chapter.id===page.chapter_id)?.title??t('第 {index} 节',{index:index+1})}
    {' · '}{t(page.page_number?.format?pageNumberLabels[page.page_number.format]??'其他编号格式':'未注明')}
    {' · '}{t(page.page_number?.mode==='restart'?'从 {start} 重新编号':'延续或默认编号',{start:page.page_number?.start??'—'})}
   </li>)}</ul>
   {fieldUpdate&&<p>{t('目录更新回执')} · {t(fieldUpdate.status==='updated'?'已实际更新':fieldUpdate.status==='pending'?'待更新':'未请求更新')}</p>}
  </section>
 }
 return <div className="school-export-details"><p>{t(report.can_export?'学校检查允许工程导出。':'学校检查存在阻止导出的错误。')}</p><p>{t('学校检查不等同科学有效性证明。')}</p><details><summary>{t('规则与冻结来源')}</summary><p>{plan.rules_version} · {plan.confirmation_id}</p><p>{t('原稿 SHA256')} <code>{plan.snapshot_sha256}</code></p><p>{t('模板分析 SHA256')} <code>{plan.analysis_sha256}</code></p><p>{t('确认 SHA256')} <code>{plan.confirmation_sha256}</code></p>{plan.rule_decisions?.map((r,i)=><ReadableValue key={`decision-${i}`} value={r}/>)}{plan.requirements.map((r,i)=><ReadableValue key={i} value={r}/>)}<ReadableValue value={plan.styles}/>{plan.front_matter&&<><ReadableValue value={plan.front_matter}/><ReadableValue value={plan.front_matter_sources}/></>}</details><details><summary>{t('分节与目录')}</summary><p>{t(plan.toc.enabled?'包含目录':'不含目录')} · {t('目录深度')} {plan.toc.depth}</p>{plan.sections.map((s,i)=><ReadableValue key={i} value={s}/>)}</details><details open={report.issues.length>0}><summary>{t('学校缺项与限制')}</summary>{report.issues.map(i=><article key={i.id}><strong>{t({content:'内容',format:'格式',manual:'人工核对',unsupported:'暂不支持'}[i.kind])} · {t({error:'错误',warning:'警告',human_review:'人工核对'}[i.severity])}</strong><p>{i.location} · {issueText(i)}</p>{i.source_evidence.map((s,n)=><ReadableValue key={n} value={s}/>)}</article>)}</details>{fieldUpdate&&<details open><summary>{t('目录更新回执')}</summary><p>{t('回执仅表示本地渲染器状态，Word/WPS 仍需人工核对。')}</p><ReadableValue value={fieldUpdate}/></details>}</div>
}
export default function SchoolExportPanel({version,value,onChange,onPreview,busy,disabled,plan,readOnly=false,customerView=false,revisedResult=false}:{version:Pick<ManuscriptVersion,'snapshot'|'revision'>;value:SchoolExportOptions;onChange:(v:SchoolExportOptions)=>void;onPreview:()=>void;busy:boolean;disabled:boolean;plan:SchoolExportPlan|null;readOnly?:boolean;customerView?:boolean;revisedResult?:boolean}){
 const {t}=useI18n();const context=version.snapshot.thesis_context!;const chapters=context.chapters;const candidate=context.confirmation?.front_matter;const front=validFrontMatter(candidate)?candidate:null
 const reviewed=version.snapshot.writing_provenance?.school_final_render as {docx_renderer_version?:string}|undefined
 const reviewedForms=typeof reviewed?.docx_renderer_version==='string'&&reviewed.docx_renderer_version.endsWith('+bsu_gs501_submission_v1')
 const officialForms=context.confirmation?.format_profile==='bsu-gs501-academic-masters-2026'&&
  (Boolean(plan?.submission_forms_source_sha256)||!readOnly||reviewedForms)
 const signingSections=new Set(['section-3','section-4'])
 const fixedChapters=new Set(front?.fields.filter(field=>field.kind==='signature'&&signingSections.has(field.section_id)).map(field=>field.chapter_id))
 const fields=front?.fields.filter(field=>!officialForms||
  (!signingSections.has(field.section_id)&&!(field.section_id==='section-2'&&field.label.replace(/\s/g,'')==='答辩委员会')))
 const manualChapters=chapters.filter(chapter=>(chapter.purpose==='manual'||chapter.purpose==='acknowledgements')&&
  (!officialForms||(!fixedChapters.has(chapter.id)&&
   !['北京体育大学学位论文原创性声明','北京体育大学学位论文使用授权书'].includes(chapter.title.replace(/\s/g,'')))))
 const formNotice=officialForms
  ? '答辩版由本人在 Word 中插入电子签名。最终版还须填齐委员会姓名、职称及单位。'
  : '未填写内容显示待补充，可生成工程样稿；不编造身份或签名。'
 const description=revisedResult
  ? readOnly?'封面、正文和关键词沿用语言审核确认的内容。':'封面、补充内容和目录设置仅用于本次 Word。'
  : readOnly?'封面、正文和关键词沿用此版本语言审核时确认的内容。':'导出固定稿件版本 {revision}；人工字段仅保存到本次导出。'
 return <div className="manuscript-review school-export-panel"><h4>{t(revisedResult?'学校排版':'学校固定版本导出')}</h4>
 <p>{t(description,{revision:version.revision})}</p><p className="warning-panel">{t(formNotice)}</p><fieldset disabled={disabled||busy||readOnly}><legend>{t('本次导出内容')}</legend><div className="manuscript-group-options">{fields?fields.map(field=><label key={field.id}>{t(field.required?'{label} · 必填':'{label} · 可选',{label:field.label})}<input aria-label={t(field.required?'{label} · 必填':'{label} · 可选',{label:field.label})} maxLength={2000} value={value.field_values?.[field.id]??''} onChange={e=>onChange({...value,field_values:{...value.field_values,[field.id]:e.target.value}})}/><small>{t(({text:'普通文本',identity:'身份信息',signature:'签名文字',date:'日期'} as const)[field.kind])}</small></label>):Object.entries(manualFieldLabels).map(([key,label])=><label key={key}>{t(label)}<input maxLength={300} value={value.manual_fields[key as keyof typeof manualFieldLabels]} onChange={e=>onChange({...value,manual_fields:{...value.manual_fields,[key]:e.target.value}})}/></label>)}</div><label>{t('英文题名')}<input maxLength={1000} value={value.english_title} onChange={e=>onChange({...value,english_title:e.target.value})}/></label>{manualChapters.map(c=><label key={c.id}>{t('{title} · 人工文本',{title:c.title})}<textarea maxLength={30000} value={value.manual_chapters.find(x=>x.chapter_id===c.id)?.text??''} onChange={e=>onChange({...value,manual_chapters:[...value.manual_chapters.filter(x=>x.chapter_id!==c.id),...(e.target.value.trim()?[{chapter_id:c.id,text:e.target.value}]:[])]})}/></label>)}{chapters.filter(c=>c.purpose==='abstract').map(c=><label key={c.id}>{t('{title} · 关键词',{title:c.title})}<KeywordInput value={value.keywords.find(k=>k.chapter_id===c.id)?.values??[]} label={t('{title} · 关键词',{title:c.title})} onChange={values=>onChange({...value,keywords:[...value.keywords.filter(x=>x.chapter_id!==c.id),...(values.length?[{chapter_id:c.id,values}]:[])]})}/><small>{t('使用分号分隔关键词。')}</small></label>)}<label><input type="checkbox" checked={value.include_toc} onChange={e=>onChange({...value,include_toc:e.target.checked})}/>{t('包含目录')}</label><label>{t('目录深度')}<select value={value.toc_depth} onChange={e=>onChange({...value,toc_depth:Number(e.target.value)})}>{[1,2,3].map(n=><option key={n} value={n}>{n}</option>)}</select></label></fieldset><button type="button" disabled={disabled||busy} onClick={onPreview}>{t('预览学校排版')}</button>{plan&&<SchoolExportDetails plan={plan} customerView={customerView}/>}</div>
}

function KeywordInput({label,value,onChange}:{label:string;value:string[];onChange:(v:string[])=>void}){const joined=value.join('; ');const [raw,setRaw]=useState(joined),[previous,setPrevious]=useState(joined);if(previous!==joined){setPrevious(joined);setRaw(joined)}return <input aria-label={label} value={raw} onChange={e=>{const values=e.target.value.split(/[;；,，]/).map(x=>x.trim()).filter(Boolean);setRaw(e.target.value);setPrevious(values.join('; '));onChange(values)}}/>}

const detailLabels:Record<string,string>={id:'标识',message:'说明',source_evidence:'来源依据',source:'来源',location:'位置',status:'状态',renderer:'渲染器',rules_version:'规则版本',title:'标题',text:'文本',purpose:'用途',level:'层级',font:'字体',font_name:'字体',font_size_pt:'字号（磅）',line_spacing:'行距',start:'起始页码',page_number:'页码',page_number_format:'页码格式',header:'页眉',footer:'页脚',section_id:'分节',chapter_id:'章节',required:'必需',value:'值',expected:'期望值',actual:'实际值',name:'名称',updated:'已实际更新',pending:'待更新',not_requested:'未请求更新'}
function ReadableValue({value}:{value:unknown}){const {t}=useI18n();if(Array.isArray(value))return <div>{value.map((v,i)=><ReadableValue key={i} value={v}/>)}</div>;if(value&&typeof value==='object')return <dl className="school-export-values">{Object.entries(value).map(([k,v])=><div key={k}><dt>{t(detailLabels[k]??k)}</dt><dd><ReadableValue value={v}/></dd></div>)}</dl>;return <span>{typeof value==='boolean'?t(value?'是':'否'):value===null?'—':t(detailLabels[String(value)]??String(value))}</span>}
