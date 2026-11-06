import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {projectBase} from './api'
import {useInsightRead} from './hooks'
import {ReadState} from './InsightShared'
import type {Result} from './contracts'

type FigureChoice={id:string;title:string;figure_type:string;manifest_sha256:string}
export default function InsightDelivery({projectId,result}:{projectId:string;result:Result}){
 const {t}=useI18n(),base=`${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(result.id)}`
 const topic=!!result.summary.topic_method,[selected,setSelected]=useState<string[]>([])
 const figures=useInsightRead<{items:FigureChoice[]}>(topic?`${base}/figures`:'',topic,true)
 const available=figures.data?.items??[],chosen=selected.filter(id=>available.some(figure=>figure.id===id))
 const query=new URLSearchParams(chosen.map(id=>['figure_version_ids',id])).toString()
 const word=['comparison','ora','gsea_prerank'].includes(result.kind)||topic
 return <section className="analysis-detail"><h3>{t('成果下载与复现')}</h3>
  {topic&&<><ReadState {...figures}/>{available.length>0&&<fieldset><legend>{t('Word 中使用的重绘图')}</legend>
   <p>{t('选择已完成的重绘图；报告记录原结果与图件来源，科学数值保持不变。')} {t('每份 Word 最多选择10张重绘图。')}</p>
   {available.map(figure=><label className="insight-check" key={figure.id}><input type="checkbox" checked={chosen.includes(figure.id)} disabled={!chosen.includes(figure.id)&&chosen.length>=10} onChange={event=>setSelected(value=>event.target.checked?[...value,figure.id]:value.filter(id=>id!==figure.id))}/>{figure.title||figure.figure_type}</label>)}
  </fieldset>}</>}
  <div className="intake-actions">{word&&<ProjectDownloadLink href={`${base}/report.docx${query?'?'+query:''}`} filename="bio-insight-report.docx" timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}>{t('下载 Word 分析报告')}</ProjectDownloadLink>}
   <ProjectDownloadLink href={`${base}/reproducibility-package`} filename="bio-insight-reproduction.zip" timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}>{t('下载离线复现包')}</ProjectDownloadLink></div>
  {chosen.length>0&&<ul>{available.filter(figure=>chosen.includes(figure.id)).map(figure=><li key={figure.id}><ProjectDownloadLink href={`${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(figure.id)}/reproducibility-package`} filename="figure-reproduction.zip" timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}>{t('{title}：下载重绘复现包',{title:figure.title||figure.figure_type})}</ProjectDownloadLink></li>)}</ul>}
  {topic&&<p>{t('原计算复现包需要匹配原运行环境；若环境已变化，可下载保存的表、参数和日志。重绘复现包只重现所选图表，不重新计算专题。')}</p>}
  <p>{t('完整表、对象、参数和日志见下方文件；复现包需要匹配的计算环境，工程复现不等于独立队列或实验验证。')}</p>
 </section>
}
