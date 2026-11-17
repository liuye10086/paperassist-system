import {useI18n} from '../../shared/i18n'
import {purposeLabels,schoolPurposes,type ChapterMapping,type SchoolPurpose,type ThesisReadiness} from './thesisTypes'
import type {ManuscriptInput} from './manuscriptTypes'
const readinessMessages:Record<string,string>={school_template_not_bound:'请先绑定学校模板',school_confirmation_unavailable:'学校确认版本不可用，请核对学校模板。',school_template_not_ready:'学校模板尚未处理完成。',school_template_source_changed:'学校模板来源已变化，请重新确认。'}
type Props={disabled?:boolean;projectId:string;readiness:ThesisReadiness|null;input:ManuscriptInput;hasReportedResult?:boolean;onOpenSchoolTemplate?:()=>void;onChange:(update:(previous:ManuscriptInput)=>ManuscriptInput)=>void}
export default function ThesisChapterFields({disabled=false,projectId,readiness,input,hasReportedResult=false,onOpenSchoolTemplate,onChange}:Props){
 const {t}=useI18n()
 const mappings=readiness?.chapters.map(c=>input.thesis?.chapter_mappings.find(m=>m.chapter_id===c.id)??{chapter_id:c.id,purpose:'' as SchoolPurpose,output_language:'project' as const,result_group_ids:[]})??[]
 const resultGroups=hasReportedResult?[{id:'reported-result',title:t('用户提供的结果与出处')},...input.results_groups]:input.results_groups
 function change(index:number,patch:Partial<ChapterMapping>){if(!readiness?.confirmation_id)return;onChange(old=>({...old,thesis:{confirmation_id:readiness.confirmation_id!,profile_revision:readiness.profile.revision,chapter_mappings:mappings.map((m,i)=>i===index?{...m,...patch}:m)}}))}
 return <section className="manuscript-panel" aria-label={t('学校章节配置')}>
  <h3>{t('学校章节配置')}</h3>
  <p>{t('学校模板仅作章节与格式依据，不作为研究事实。')}</p>
  {onOpenSchoolTemplate?<button type="button" onClick={onOpenSchoolTemplate}>{t('配置学校模板')}</button>:
    <a href={`#project=${encodeURIComponent(projectId)}&section=school-templates`}>{t('配置学校模板')}</a>}
  {!readiness?.ready?<div role="alert">{readiness?.blocking_reasons.map((reason,i)=><p key={i}>{t(readinessMessages[reason]??reason)}</p>)??<p>{t('请先绑定学校模板')}</p>}</div>:<>
   <p>{[readiness.profile.school,readiness.profile.degree_type,readiness.profile.applicable_version,
     !onOpenSchoolTemplate&&readiness.confirmation_id].filter(Boolean).join(' · ')}</p>
   <p>{t('逐章明确内容用途和语言；不会按模板示例推断研究内容。')}</p>
   {readiness.chapters.map((chapter,index)=>{
    const mapping=mappings[index]
    return <fieldset disabled={disabled} key={chapter.id} aria-label={chapter.title}>
     <legend>{chapter.title}</legend><p>{t('章节层级 {number}',{number:chapter.level})}</p>
     <label>{t('内容用途')}<select value={mapping.purpose}
      onChange={e=>change(index,{purpose:e.target.value as SchoolPurpose,result_group_ids:e.target.value==='results'?mapping.result_group_ids:[]})}>
      <option value="">{t('请选择内容用途')}</option>
      {schoolPurposes.map(purpose=><option key={purpose} value={purpose}>{t(purposeLabels[purpose])}</option>)}
     </select></label>
     <label>{t('章节语言')}<select value={mapping.output_language}
      onChange={e=>change(index,{output_language:e.target.value as ChapterMapping['output_language']})}>
      <option value="project">{t('沿用稿件语言')}</option><option value="zh-CN">{t('简体中文')}</option><option value="en">English</option>
     </select></label>
     {mapping.purpose==='results'&&<div><p>{t('明确关联结果组；同一结果组只能分配到一个结果章。')}</p>
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
