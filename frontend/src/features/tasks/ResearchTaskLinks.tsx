import {useI18n} from '../../shared/i18n'
import type {TaskWorkspace,TaskView} from './taskTypes'
export default function ResearchTaskLinks({task,artifact,reportReturn}:{
 task:TaskView;artifact?:TaskWorkspace['artifacts']['research_results'];reportReturn?:string
}){
 const {t}=useI18n()
 const id=task.result_research_figure_version_id??task.result_research_report_version_id??task.result_research_candidate_id
  ??artifact?.figure_version_id??artifact?.report_version_id??artifact?.candidate_id
 if(!id)return null
 const route=new URLSearchParams({project:task.project_id})
 if(task.task_type!=='research_report'&&task.task_type!=='research_figure'){
  route.set('section','manuscripts')
  route.set('view','research-candidates')
  route.set('candidate',id)
 }else{
  route.set('section','artifacts')
  route.set('view',task.task_type==='research_figure'?'research-figures':'research-reports')
  route.set('artifact',id)
  if(task.task_type==='research_report'&&reportReturn)route.set('reportReturn',reportReturn)
 }
 return <p><a href={'#'+route}>{t(task.task_type==='research_fact_draft'?'核对结果与方法候选':'查看固定研究成果')}</a></p>
}
