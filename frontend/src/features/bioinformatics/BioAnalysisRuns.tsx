import {useI18n} from '../../shared/i18n'
import {useState,type ReactNode} from 'react'
import type {AnalysisNavigation,BioResultTab} from '../projects/analysisViews'
import {projectBase} from './api'
import type {BioRun} from './spatialContracts'
import {useBioRead} from './spatialHooks'
import {taskDisplayName} from '../tasks/taskTypes'
type Props={
 projectId:string;active:boolean;onNavigate:(n:AnalysisNavigation)=>void
 resultsOnly?:boolean;singleCellOnly?:boolean;title?:string;resultTab?:BioResultTab;headerAction?:ReactNode
}
const singleCellRun=(run:BioRun)=>run.raw_source.parser_version==='single_cell_import_v1'

export default function BioAnalysisRuns({projectId,active,onNavigate,resultsOnly=false,singleCellOnly=false,title,resultTab='qc',headerAction}:Props){
 const {t,locale}=useI18n(),[page,setPage]=useState(1)
 const read=useBioRead<{items:BioRun[];total:number;page:number;page_size:number}>(active?`${projectBase(projectId)}/bio-analysis-runs?page=${page}&page_size=50`:'')
 const items=read.value?.items.filter(run=>(!singleCellOnly||singleCellRun(run))&&(!resultsOnly||run.task.status==='succeeded'&&!!run.result_source))??[]
 return <section className="bio-workspace bio-run-history">
  <header className="analysis-section-heading"><h3>{t(title??(singleCellOnly?'单细胞分析运行历史':'生信分析运行历史'))}</h3>
   {headerAction ? <div className="bio-run-actions">
    {headerAction}
    <button type="button" onClick={read.reload}>{t('刷新运行记录')}</button>
   </div> : <button type="button" onClick={read.reload}>{t('刷新运行记录')}</button>}
  </header>
  {read.error&&<p role="alert">{t(read.error)}</p>}
  {read.value&&<>
   {items.length > 0 && <ul className={resultsOnly?'bio-completed-runs':undefined}>{items.map(run=>{
    const singleCell=singleCellRun(run),tabular=run.raw_source.parser_version==='tabular_assay_import_v1'
    const review=<button type="button" onClick={()=>onNavigate({view:'bio-analysis',fileId:'',runId:run.id})}>
     {t(singleCell?'查看单细胞分析运行与 QC 确认':tabular?'查看定量分析运行与 QC 确认':'查看空间分析运行与 QC 确认')}
    </button>
    const open=run.result_source&&run.task.status==='succeeded'&&<button type="button" className={resultsOnly?'button-primary':undefined}
     onClick={()=>onNavigate({view:'bio-result',fileId:'',processedId:run.result_source!.processed_dataset_version_id,tab:resultTab})}>{t('打开固定处理结果')}</button>
    return <li key={run.id}>{resultsOnly?<>
     <div className="bio-run-identity">
      <strong>{t(singleCell?'单细胞分析处理结果':tabular?'定量分析处理结果':'空间分析处理结果')}</strong>
      <span className="status-badge task-status task-status-succeeded">{t(taskDisplayName(run.task))}</span>
      {run.task.updated_at&&<small>{t('完成时间')} · <time dateTime={run.task.updated_at}>{new Date(run.task.updated_at).toLocaleString(locale)}</time></small>}
     </div>
     <div className="bio-run-actions">{review}{open}</div>
    </>:<>{t(taskDisplayName(run.task))}{run.task.created_at&&<> · <time dateTime={run.task.created_at}>{new Date(run.task.created_at).toLocaleString(locale)}</time></>} · {review}{open}</>}</li>
   })}</ul>}
   {!items.length&&<p>{t(singleCellOnly?'本页暂无单细胞分析运行。':resultsOnly?'本页暂无已完成的生信分析结果。':'暂无生信分析运行')}</p>}
   <div className="analysis-pagination" hidden={read.value.total<=50}>
    <button type="button" disabled={page===1} onClick={()=>setPage(p=>p-1)}>{t('上一页')}</button>
    {resultsOnly && <span>{t('第 {page} / {pages} 页', { page, pages: Math.max(1, Math.ceil(read.value.total / 50)) })}</span>}
    <button type="button" disabled={page*50>=read.value.total} onClick={()=>setPage(p=>p+1)}>{t('下一页')}</button>
   </div>
  </>}
 </section>
}
