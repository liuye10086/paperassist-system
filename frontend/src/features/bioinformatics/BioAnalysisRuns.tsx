import {useI18n} from '../../shared/i18n'
import {useState} from 'react'
import type {AnalysisNavigation,BioResultTab} from '../projects/analysisViews'
import {projectBase} from './api'
import type {BioRun} from './spatialContracts'
import {useBioRead} from './spatialHooks'
import {taskDisplayName} from '../tasks/taskTypes'
type Props={
 projectId:string;active:boolean;onNavigate:(n:AnalysisNavigation)=>void
 resultsOnly?:boolean;singleCellOnly?:boolean;title?:string;resultTab?:BioResultTab
}
const singleCellRun=(run:BioRun)=>run.raw_source.parser_version==='single_cell_import_v1'

export default function BioAnalysisRuns({projectId,active,onNavigate,resultsOnly=false,singleCellOnly=false,title,resultTab='qc'}:Props){
 const {t}=useI18n(),[page,setPage]=useState(1)
 const read=useBioRead<{items:BioRun[];total:number;page:number;page_size:number}>(active?`${projectBase(projectId)}/bio-analysis-runs?page=${page}&page_size=50`:'')
 const items=read.value?.items.filter(run=>(!singleCellOnly||singleCellRun(run))&&(!resultsOnly||run.task.status==='succeeded'&&!!run.result_source))??[]
 return <section className="bio-workspace bio-run-history">
  <header className="analysis-section-heading"><h3>{t(title??(singleCellOnly?'单细胞分析运行历史':'生信分析运行历史'))}</h3>
   <button type="button" onClick={read.reload}>{t('刷新运行记录')}</button>
  </header>
  {read.error&&<p role="alert">{t(read.error)}</p>}
  {read.value&&<>
   <ul>{items.map(run=><li key={run.id}>
    {t('固定分析运行')} · {t(taskDisplayName(run.task))}{singleCellOnly&&<> · <code>{run.id}</code></>} ·
    <button type="button" onClick={()=>onNavigate({view:'bio-analysis',fileId:'',runId:run.id})}>
     {t(singleCellRun(run)?'查看单细胞分析运行与 QC 确认':run.raw_source.parser_version==='tabular_assay_import_v1'?'查看定量分析运行与 QC 确认':'查看空间分析运行与 QC 确认')}
    </button>
    {run.result_source&&run.task.status==='succeeded'&&<button type="button"
     onClick={()=>onNavigate({view:'bio-result',fileId:'',processedId:run.result_source!.processed_dataset_version_id,tab:resultTab})}>{t('打开固定处理结果')}</button>}
   </li>)}</ul>
   {!items.length&&<p>{t(singleCellOnly?'本页暂无单细胞分析运行。':resultsOnly?'本页暂无已完成的生信分析结果。':'暂无生信分析运行')}</p>}
   <div className="analysis-pagination" hidden={read.value.total<=50}>
    <button type="button" disabled={page===1} onClick={()=>setPage(p=>p-1)}>{t('上一页')}</button>
    <button type="button" disabled={page*50>=read.value.total} onClick={()=>setPage(p=>p+1)}>{t('下一页')}</button>
   </div>
  </>}
 </section>
}
