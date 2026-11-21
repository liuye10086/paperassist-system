import {useI18n} from '../../shared/i18n'
import {purposeLabels,schoolPurposes,type ChapterMapping,type SchoolPurpose,type ThesisReadiness} from './thesisTypes'
import type {ManuscriptInput,PaperPlan} from './manuscriptTypes'
const readinessMessages:Record<string,string>={school_template_not_bound:'请先绑定学校模板',school_confirmation_unavailable:'学校确认版本不可用，请核对学校模板。',school_template_not_ready:'学校模板尚未处理完成。',school_template_source_changed:'学校模板来源已变化，请重新确认。'}
// Customers read why the chapters wait for a template in plain words (B04 task 8, wireframe 13b).
const customerReadinessMessages:Record<string,string>={...readinessMessages,school_template_not_bound:'还没有采用学校模板。采用后才能按学校格式核对本章标题和级别。'}
export type TemplateTripChapter={id:string;title:string}
type Props={disabled?:boolean;projectId:string;readiness:ThesisReadiness|null;input:ManuscriptInput;hasReportedResult?:boolean;paperPlan?:PaperPlan
 /** Customer only: plain wording, no chapter level, and a trip to the template page that returns to the chapter. */
 customerView?:boolean
 /** Customer only: chapters of a newly adopted template that no saved chapter matched by title. */
 pendingChapterIds?:readonly string[]
 onOpenSchoolTemplate?:(chapter?:TemplateTripChapter)=>void;onChange:(update:(previous:ManuscriptInput)=>ManuscriptInput)=>void}
export default function ThesisChapterFields({disabled=false,projectId,readiness,input,hasReportedResult=false,paperPlan,customerView=false,pendingChapterIds=[],onOpenSchoolTemplate,onChange}:Props){
 const {t}=useI18n()
 const customerTrip=customerView&&!!onOpenSchoolTemplate
 const tripButton=(chapter?:TemplateTripChapter,change=false)=><button type="button" className={change?undefined:'button-primary'} onClick={()=>onOpenSchoolTemplate?.(chapter)}>
  {t(change?'改用学校模板（完成后回到{place}）':'去采用学校模板（完成后回到{place}）',{place:chapter?.title??t('章节与复核')})}</button>
 const mappings=readiness?.chapters.map(c=>input.thesis?.chapter_mappings.find(m=>m.chapter_id===c.id)??{chapter_id:c.id,purpose:'' as SchoolPurpose,output_language:'project' as const,result_group_ids:[]})??[]
 const resultGroups=hasReportedResult?[{id:'reported-result',title:t('用户提供的结果与出处')},...input.results_groups]:input.results_groups
 function change(index:number,patch:Partial<ChapterMapping>){if(!readiness?.confirmation_id)return;onChange(old=>({...old,thesis:{confirmation_id:readiness.confirmation_id!,profile_revision:readiness.profile.revision,chapter_mappings:mappings.map((m,i)=>i===index?{...m,...patch}:m)}}))}
 return <section className="manuscript-panel" aria-label={t('学校章节配置')}>
  <h3 id="thesis-chapters" tabIndex={-1}>{t('学校章节配置')}</h3>
  <p>{t('学校模板仅作章节与格式依据，不作为研究事实。')}</p>
  {customerTrip?readiness?.ready&&tripButton(undefined,true):onOpenSchoolTemplate?<button type="button" onClick={()=>onOpenSchoolTemplate()}>{t('配置学校模板')}</button>:
    <a href={`#project=${encodeURIComponent(projectId)}&section=school-templates`}>{t('配置学校模板')}</a>}
  {!readiness?.ready?<><div role="alert">{readiness?.blocking_reasons.map((reason,i)=><p key={i}>{t((customerView?customerReadinessMessages:readinessMessages)[reason]??reason)}</p>)??<p>{t(customerView?customerReadinessMessages.school_template_not_bound:'请先绑定学校模板')}</p>}</div>
   {customerTrip&&readiness&&(readiness.chapters.length?readiness.chapters.map(chapter=><fieldset key={chapter.id} id={`thesis-chapter-${chapter.id}`} tabIndex={-1} aria-label={chapter.title}>
    <legend>{chapter.title}</legend>{tripButton({id:chapter.id,title:chapter.title})}</fieldset>):tripButton())}</>:<>
   <p>{[readiness.profile.school,readiness.profile.degree_type,readiness.profile.applicable_version,
     !onOpenSchoolTemplate&&readiness.confirmation_id].filter(Boolean).join(' · ')}</p>
   <p>{t(paperPlan?'已选的章沿用保存的用途，请为其余章节指定用途。':'逐章明确内容用途和语言；不会按模板示例推断研究内容。')}</p>
   {readiness.chapters.map((chapter,index)=>{
    const mapping=mappings[index]
    const planned=paperPlan?.sections.find(section=>section.chapter_id===chapter.id)
    const protectedPurpose=paperPlan&&readiness.protected_chapter_purposes?.[chapter.id]
    return <fieldset disabled={disabled} key={chapter.id} id={`thesis-chapter-${chapter.id}`} tabIndex={-1} aria-label={chapter.title}>
     <legend>{chapter.title}</legend>{!customerView&&<p>{t('章节层级 {number}',{number:chapter.level})}</p>}
     {pendingChapterIds.includes(chapter.id)&&!mapping.purpose&&<p className="warning-panel">{t('待选择')}</p>}
     {protectedPurpose?<p><strong>{t('内容用途')}</strong> · {t(purposeLabels[protectedPurpose])} · {t('沿用学校模板确认的用途')}</p>
      :planned?.purpose?<p><strong>{t('内容用途')}</strong> · {t(purposeLabels[planned.purpose])} · {t('沿用已保存的写作要求')}</p>:<label>{t('内容用途')}<select value={mapping.purpose}
      onChange={e=>change(index,{purpose:e.target.value as SchoolPurpose,result_group_ids:e.target.value==='results'?mapping.result_group_ids:[]})}>
      <option value="">{t('请选择内容用途')}</option>
      {schoolPurposes.map(purpose=><option key={purpose} value={purpose}>{t(purposeLabels[purpose])}</option>)}
     </select></label>}
     <label>{t('章节语言')}<select value={mapping.output_language}
      onChange={e=>change(index,{output_language:e.target.value as ChapterMapping['output_language']})}>
      <option value="project">{t('沿用稿件语言')}</option><option value="zh-CN">{t('简体中文')}</option><option value="en">English</option>
     </select></label>
     {mapping.purpose==='results'&&(planned||resultGroups.length>0||!paperPlan)&&<div>{planned&&<p>{t('已关联的结果和图表随本章带入。')}</p>}{(resultGroups.length>0||!paperPlan)&&<p>{t('明确关联结果组；同一结果组只能分配到一个结果章。')}</p>}
      {resultGroups.map(group=><label key={group.id}><input type="checkbox" checked={mapping.result_group_ids.includes(group.id)}
       disabled={mappings.some((entry,i)=>i!==index&&entry.result_group_ids.includes(group.id))}
       onChange={e=>change(index,{result_group_ids:e.target.checked?[...mapping.result_group_ids,group.id]:mapping.result_group_ids.filter(id=>id!==group.id)})}/>
       {group.title||t('未命名结果组')}</label>)}
     </div>}
    </fieldset>
   })}
  </>}
 </section>
}
