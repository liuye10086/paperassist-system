import {getApiUserId} from '../../shared/api/client'
import useResearchDraft from '../research-results/useResearchDraft'
import {analysisScopes} from './analysisEntryState'
import { useI18n } from '../../shared/i18n'
import type { Version } from '../research-intake/contracts'
import type { ProjectFile } from '../files/fileLibraryApi'
import type { AnalysisNavigation } from './analysisViews'
import AnalysisRequestList from './AnalysisRequestList'
import type {EntryImport} from './analysisEntryState'
import {bulkRoute} from '../bio-insights/bulkWorkflow'

function GuideContent({ projectId, onUpload, version, files, loading, error, filesLoading, filesError, onRefresh, onReloadFiles, onNavigate, onFile, onRequirements, scopeId, imports, importsUnknown, importsError }: {
  projectId?:string;onUpload?:()=>void
  version:Version|null;files:ProjectFile[];loading:boolean;error:string;filesLoading:boolean;filesError:string;onRefresh:()=>void;onReloadFiles:()=>void;onFile:(id:string)=>void;scopeId?:string;onNavigate:(next:AnalysisNavigation)=>void;onRequirements?:(panel?:'materials')=>void
  imports:EntryImport[];importsUnknown:boolean;importsError:string
}) {
  const { t } = useI18n();const [panel,setPanel]=useResearchDraft(projectId??version?.project_id??'unscoped',`analysis-panel:${version?.id??'new'}:${scopeId??'all'}`,()=> 'tasks');const hasTasks=!!version&&analysisScopes(version).length>0
  return <div className="analysis-guide">
    <nav className="analysis-page-tabs" aria-label={t('执行分析视图')}>{[['tasks','本次任务'],['history','已有分析']].map(([key,label])=><button type="button" key={key} aria-pressed={panel===key} onClick={()=>setPanel(key)}>{t(label)}</button>)}</nav>
    <header className="analysis-overview-heading"><h2>{t(panel==='tasks'?'执行分析':'已有分析')}</h2>{panel==='tasks'&&<p>{t('核对任务 → 配置分析 → 检查并运行')}</p>}</header>
    <div className="analysis-guide-body"><div hidden={panel!=='tasks'}>
    <div className="intake-actions"><button type="button" onClick={()=>onNavigate(bulkRoute('design'))}>{t('进入 Bulk RNA-seq 工作流')}</button></div>
    {importsError&&<p role="alert">{t(importsError)} <button type="button" onClick={onReloadFiles}>{t('重新读取材料')}</button></p>}
    {loading&&<p role="status">{t('正在读取已保存的需求……')}</p>}
    {error?<p role="alert">{t('需求读取失败，请重试。')} <button type="button" onClick={onRefresh}>{t('重新读取需求')}</button></p>:version?<AnalysisRequestList projectId={projectId} onUpload={onUpload} focused version={version} scopeId={scopeId} imports={imports} importsUnknown={importsUnknown} files={files} filesLoading={filesLoading} filesError={filesError} onNavigate={onNavigate} onFile={onFile} onRequirements={onRequirements} onReloadFiles={onReloadFiles}/>:!loading&&<section className="analysis-choice-summary"><p>{t('还没有保存分析需求，请先选择并保存需求。')}</p>{onRequirements&&<button type="button" onClick={()=>onRequirements?.()}>{t('填写需求')}</button>}</section>}
    {!hasTasks&&!loading&&!error&&<><section className="analysis-overview-heading"><h3>{t('选择分析类型')}</h3></section>
    <div className="analysis-entry-grid">
      {([
        ['setup', '表格数据与统计', '适合实验指标、临床、行为学等表格；选择文件与分组后分析。'],
        ['bio-datasets', '组学与生信数据', '适合转录组、单细胞、空间、蛋白组等；先核对数据集与样本。'],
        ['bio-insights', '差异、通路与候选筛选', '基于已准备的数据开展组间比较、功能分析与候选筛选。'],
      ] as const).map(([view, title, help]) => <button key={view} type="button" onClick={() => onNavigate({view,fileId:''})}><strong>{t(title)}</strong><span>{t(help)}</span><span aria-hidden="true">→</span></button>)}
    </div>
    </>}</div><div hidden={panel!=='history'}><section className="analysis-tools"><h3>{t('已有分析与工具')}</h3><div className="analysis-tool-grid">{([
      ['bio-insight-plan', '生信计划与运行', '查看已保存的生信计划、运行记录和固定结果。'],
      ['profile', '数据概况', '查看数据质量和字段分布。'],
      ['plan', '分析方案', '核对研究问题、分析方法与方案。'],
      ['statistics', '统计结果', '查看当前分析结果，按需要继续计算。'],
      ['figure', '图表工作台', '根据已有结果出图和调整样式。'],
      ['report', '报告与集合', '组织已有结果并导出报告。'],
      ['research-findings', '研究发现与核对', '核对研究结果，准备后续论文材料。'],
    ] as const).map(([view, title, help]) => <button key={view} type="button" onClick={() => onNavigate({view,fileId:''})}><strong>{t(title)}</strong><span>{t(help)}</span></button>)}</div></section></div></div>
  </div>
}
export default function AnalysisGuide(props:Parameters<typeof GuideContent>[0]){
  return <GuideContent key={`${getApiUserId()}:${props.projectId??props.version?.project_id??'unscoped'}:${props.version?.id??'new'}:${props.scopeId??'all'}`} {...props}/>
}
