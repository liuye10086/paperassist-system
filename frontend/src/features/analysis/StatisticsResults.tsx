import {useAnalysisLeaveGuard} from './analysisActivityContext'
import StatisticsTaskObserver from './StatisticsTaskObserver'
import {pendingStatisticsKey,saveStatisticsKey} from './statisticsRequestIdentity'
import {taskMatchesStatisticsContext,type StatisticsTaskContext} from './statisticsTaskContracts'
import {isTask,type TaskView} from '../tasks/taskTypes'
import {taskRequest,TaskRequestError} from '../tasks/taskApi'
import ModelResults from './ModelResults'
import {modelMethods} from './modelSelection'
import type {ModelResult} from './modelResult'
import ComparisonResults from './ComparisonResults'
import type {ComparisonResult} from './comparisonResult'
import CorrelationResults from './CorrelationResults'
import type {CorrelationResult} from './correlationResult'
import type {AnalysisSelection} from './analysisSelection'
import ResearchRequestSummary from '../analysisPlan/ResearchRequestSummary'
import {validStatisticsContext,type AnalysisContext} from './statisticsContext'
import SourceSummary from './SourceSummary'
import QualityProvenance from '../datasetPreparation/QualityProvenance'
import { isDatasetSource, sameSource, validOptionalSource, type DatasetAnalysisSource } from './datasetSource'
import { useI18n, apiError, safeError } from '../../shared/i18n'
import { workflowNotice } from '../../shared/i18n/workflowMessages'
import { apiFetch } from '../../shared/api/client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Check, Selection } from './AnalysisSetup'
import BoxplotFigure from '../figures/BoxplotFigure'
import { WorkflowStage, WorkflowEmptyResults, WorkflowReadStatus } from './AnalysisWorkflow'
import { useWorkflowNavigation } from './analysisWorkflowContext'
import ConfirmedRunArtifacts from './ConfirmedRunArtifacts'

type Summary = { n: number; mean: number; std: number | null; min: number; q1: number; median: number
  q3: number; max: number; iqr: number | null; warnings: string[] }
type DescriptiveResult = { file_id?:string; result_type?:never;schema_version?:2|3;analysis_context?:AnalysisContext; source?: DatasetAnalysisSource; id: string; filename: string; source_sha256: string; setup_revision: number; selection: Selection
  check: Check; numeric_name: string; group_name: string | null; started_at: string; completed_at: string
  engine: { execution_contract?: 'fixed_statistics_v2'; id: string; python_version: string; openpyxl_version?: string; parser_version?: string }; overall: Summary
  groups: { label: string; statistics: Summary }[] }
export type Result=DescriptiveResult|CorrelationResult|ComparisonResult|ModelResult
type ResultState = { current_revision: number | null; is_current: boolean; result: Result | null; active_task?:TaskView|null; execution_verification?:'verified'|'legacy_unverified'|null }

function formatted(value: number | null, locale: string) {
  if (value === null) return '—'
  return new Intl.NumberFormat(locale, { maximumSignificantDigits: 6,
    notation: value !== 0 && (Math.abs(value) < 0.0001 || Math.abs(value) >= 1e9) ? 'scientific' : 'standard',
    useGrouping: false }).format(value)
}

async function request<T>(url: string, signal: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, { ...init, signal })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(apiError(body, '统计请求失败，请重新读取结果后重试。'))
  return body
}

function explain(cause: unknown, timedOut: boolean) {
  if (timedOut) return '等待统计请求超时。后端可能仍在处理，请先重新读取统计结果，再决定是否重试。'
  if (cause instanceof TypeError) return '无法连接后端，请确认服务正常并重新读取统计结果。'
  return safeError(cause, '统计请求失败，请重新读取结果后重试。')
}

type Props={base: string; savedRevision: number | null; savedSelection?:AnalysisSelection; savedPlan?:{plan_id:string;sha256:string}; savedSource?: DatasetAnalysisSource; fieldsMatch: boolean; disabled: boolean; onBusyChange: (value: boolean) => void}
function ResearchBasis(props: Parameters<typeof ResearchRequestSummary>[0]) {
  const {t}=useI18n()
  return <details className="statistics-provenance"><summary>{t('研究需求与分析依据')}</summary><ResearchRequestSummary {...props}/></details>
}
function RunFigure({ onRunBusyChange, ...props }: Omit<Parameters<typeof BoxplotFigure>[0], 'onBusyChange'> & { onRunBusyChange: (id: string, busy: boolean) => void }) {
  const change = useCallback((busy: boolean) => onRunBusyChange(props.runId, busy), [onRunBusyChange, props.runId])
  return <BoxplotFigure {...props} onBusyChange={change}/>
}
export default function StatisticsResults(props:Props){return <Results key={JSON.stringify([props.base,props.savedRevision,props.savedSource,props.savedPlan])} {...props}/>}
function Results({ base, savedRevision, savedSelection, savedSource, savedPlan, fieldsMatch, disabled, onBusyChange }:Props) {
  const { t, locale } = useI18n()
  const navigation = useWorkflowNavigation()
  const [state, setState] = useState<ResultState | null>(null)
  const [loading, setLoading] = useState(!!savedRevision)
  const [submitting, setSubmitting] = useState(false)
  const [activeTask,setActiveTask]=useState<TaskView|null>(null)
  const language=activeTask?.input_version.kind==='statistics_compute'?activeTask.input_version.output_language:state?.is_current?state.result?.analysis_context?.plan.research_request?.output_language??'zh-CN':savedPlan?undefined:'zh-CN'
  const context:StatisticsTaskContext=useMemo(()=>({base,revision:savedRevision??0,source:savedSource,plan:savedPlan,language,selection:savedSelection}),[base,savedRevision,savedSource,savedPlan,language,savedSelection])
  const identityContext=JSON.stringify([base,savedRevision,savedSource?.dataset_id,savedPlan?.plan_id])
  const [initialKey]=useState(()=>pendingStatisticsKey(identityContext))
  const replay=useRef<string|null>(initialKey)
  const [unconfirmed,setUnconfirmed]=useState(!!initialKey)
  const running=submitting||!!activeTask&&['queued','running'].includes(activeTask.status)
  const [plotActivity, setPlotActivity] = useState<Record<string,boolean>>({})
  const plotBusy=Object.values(plotActivity).some(Boolean)
  const onRunBusyChange=useCallback((id:string,busy:boolean)=>setPlotActivity(previous=>previous[id]===busy?previous:{...previous,[id]:busy}),[])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [historicalSelection,setHistoricalSelection]=useState(false)
  useAnalysisLeaveGuard(false, submitting || unconfirmed)
  const action = useRef<AbortController | null>(null)
  const result = state?.result
  const [artifactMode,setArtifactMode]=useState<'current'|'workbench'>('current')
  const [legacyRuns,setLegacyRuns]=useState<Result[]>([])
  const [legacyRunId,setLegacyRunId]=useState('')
  if(result&&!legacyRuns.some(run=>run.id===result.id)) { setLegacyRuns(runs=>[...runs,result]); if(!legacyRunId)setLegacyRunId(result.id) }
  const descriptive=result&&result.result_type===undefined?result:undefined
  const correlation=result?.result_type==='correlation'?result:undefined
  const comparison=result?.result_type==='group_comparison'?result:undefined
  const modeling=result&&(result.result_type==='regression'||result.result_type==='roc'||result.result_type==='survival')?result:undefined
  const modelMethod=modeling?.selection.method??(savedSelection&&(savedSelection.task_type==='regression'||savedSelection.task_type==='roc'||savedSelection.task_type==='survival')?savedSelection.method:undefined)
  const isComparison=!!comparison||savedSelection?.task_type==='group_comparison'
  const isCorrelation=!!correlation||savedSelection?.task_type==='correlation'
  const requestGeneration=useRef(0)
  const revisionMatches = !!savedRevision && state?.current_revision === savedRevision

  useEffect(() => {
    if (!savedRevision) return
    const controller = new AbortController()
    const generation=++requestGeneration.current
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 30_000)
    request<ResultState>(`${base}/analysis-result`, controller.signal)
      .then(value => { if (active && !controller.signal.aborted&&generation===requestGeneration.current) { if (value.result && (Object.hasOwn(value.result, 'source') && (!isDatasetSource(value.result.source) || !validOptionalSource(value.result, value.result.source) || value.result.source.sheet_name !== value.result.selection.sheet_name) || !validStatisticsContext(value.result,base,value.is_current?savedPlan:undefined) || value.is_current && (!sameSource(value.result.source, savedSource)||value.result.setup_revision!==savedRevision||value.current_revision!==savedRevision))) throw new Error('数据来源或版本不一致，请重新载入配置。'); if(value.active_task!=null&&(!isTask(value.active_task,decodeURIComponent(base.split('/')[4]))||!taskMatchesStatisticsContext(value.active_task,context)))throw new Error('数据来源或版本不一致，请重新载入配置。'); setState(value);setActiveTask(value.active_task??null);if(value.active_task&&replay.current===null)setUnconfirmed(false) } })
      .catch(cause => { if (active) setError(explain(cause, controller.signal.aborted)) })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false) })
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [base, savedRevision, savedSelection, savedSource, savedPlan, attempt,context,identityContext])
  useEffect(() => () => action.current?.abort(), [])
  useEffect(() => { onBusyChange(running || plotBusy) }, [running, plotBusy, onBusyChange])

  async function execute() {
    if (action.current || loading || error&&!unconfirmed || disabled || plotBusy || running&&!unconfirmed || !fieldsMatch || !revisionMatches) return
    const controller = new AbortController()
    const generation=requestGeneration.current
    action.current = controller
    if(!replay.current){replay.current=crypto.randomUUID();saveStatisticsKey(identityContext,replay.current)}
    setSubmitting(true);setError('');setNotice('')
    try {
      const task=await taskRequest(`${base}/analysis-runs`,controller,
        (value):value is TaskView=>isTask(value,decodeURIComponent(base.split('/')[4]))&&taskMatchesStatisticsContext(value,context),
        '统计提交尚未确认，请核实并继续同一请求。',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:savedRevision,idempotency_key:replay.current})})
      if(!controller.signal.aborted&&generation===requestGeneration.current){
        setActiveTask(task);setUnconfirmed(false);replay.current=null;saveStatisticsKey(identityContext,null)
      }
    } catch(cause) {
      if(generation===requestGeneration.current){const definitive=cause instanceof TaskRequestError&&[400,403,404,409,410,422].includes(cause.status);setUnconfirmed(!definitive);if(definitive){replay.current=null;saveStatisticsKey(identityContext,null)}setError(safeError(cause,'统计提交尚未确认，请核实并继续同一请求。'))}
    } finally {
      if(action.current===controller)action.current=null
      if(generation===requestGeneration.current)setSubmitting(false)
    }
  }

  const rows = descriptive ? [{ label: t('总体（完整记录）'), statistics: descriptive.overall }, ...descriptive.groups] : []
  function reload() {
    setNotice(''); setError(''); setLoading(true); setAttempt(value => value + 1)
  }
  return <>
    <WorkflowReadStatus stages={['figure', 'explanation', 'report']} loading={loading} error={error}
      loadingMessage="正在读取统计结果……" reloadLabel="重新读取统计结果" onReload={reload}
      disabled={disabled || plotBusy || running || !savedRevision} />
    <WorkflowStage stage="statistics"><section className="statistics-results" aria-labelledby="statistics-title" aria-busy={loading || running}>
    <div className="section-heading">
      <h3 id="statistics-title">{t(modelMethod?modelMethods[modelMethod]:isComparison?"组间比较":isCorrelation?"相关分析":"描述统计")}</h3>
      <p>{t(modelMethod?'按已确认计划计算模型效应或固定曲线，并保留诊断与排除记录。':isComparison?'按已确认计划计算组间或两次配对比较。':isCorrelation?'按已确认的计划计算相关系数及适用的推断结果。':'按已保存的字段配置，计算所选数据的总体和各分组统计量。')}</p>
    </div>
    {!savedRevision ? <p className="muted">{t("请先检查字段并保存分析配置。")}</p>
      : !fieldsMatch && <p className="warning-panel">{t("当前字段尚未保存，请先检查并保存，再执行统计。")}</p>}
    {state && savedRevision && !revisionMatches && <p className="warning-panel">{t("配置已在其他页面变化，请点击“重新载入分析配置”后再执行。")}</p>}
    <div className="analysis-actions">
      <button type="button" className="button-primary" disabled={unconfirmed || disabled || plotBusy || loading || running || !!error || !fieldsMatch || !revisionMatches} onClick={() => void execute()}>{t(modelMethod?"执行已确认分析":isComparison?"执行组间比较":isCorrelation?"执行相关分析":"执行描述统计")}</button>
      <button type="button" disabled={disabled || plotBusy || loading || running || !savedRevision} onClick={reload}>{t("重新读取统计结果")}</button>
    </div>
    {unconfirmed&&<><p className="warning-panel">{t('统计提交尚未确认，请核实并继续同一请求。')}</p><button type="button" disabled={loading||submitting||disabled||!fieldsMatch||!revisionMatches} onClick={()=>void execute()}>{t('核实并继续同一统计请求')}</button></>}
    {activeTask&&<StatisticsTaskObserver task={activeTask} context={context} onTask={setActiveTask} onError={setError} onResult={value=>{setState({current_revision:savedRevision,is_current:true,result:value,execution_verification:'verified'});setError('');setNotice('结果已保存，刷新或重启后可再次查看。重复执行同一配置会返回已保存结果。')}}/>}
    {state?.execution_verification==='legacy_unverified'&&result&&<p className="warning-panel">{t('此历史结果没有新版隔离执行回执；阅读不会自动重新计算。')}</p>}
    {loading && <p role="status">{t("正在读取统计结果……")}</p>}
    {running && <p role="status">{t(modelMethod?'正在计算已确认分析，请稍候……':isComparison?'正在计算组间比较，请稍候……':isCorrelation?'正在计算相关分析，请稍候……':'正在计算描述统计，请稍候……')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {notice && <p role="status" className="saved-notice">{t(notice)}</p>}
    {state && !result && <p>{t(modelMethod?'尚未执行当前已确认的分析。':isComparison?'尚未执行当前配置的组间比较。':isCorrelation?'尚未执行当前配置的相关分析。':'尚未执行当前配置的描述统计。')}</p>}
    {result?.source && result.source.schema_version >= 2 && <QualityProvenance projectId={decodeURIComponent(base.split('/')[4])} source={result.source} />}
    {descriptive && <>
      {!state?.is_current && <p className="warning-panel">{t("以下为历史结果。设置已变更，请重新分析。")}</p>}
      <SourceSummary source={descriptive.source} filename={descriptive.filename} />
      {descriptive.analysis_context?.plan.research_request&&<><ResearchBasis selection={descriptive.selection} value={descriptive.analysis_context.plan.research_request}/><p className="muted">{t(['paired','repeated'].includes(descriptive.analysis_context.plan.research_request.observation_structure)?'统计按行描述，未进行配对或重复测量推断，也未作相关性调整。':'统计按行描述，仅计算总体与分组数据分布。')}</p><p className="muted">{t('P 值、效应量和置信区间未计算，因为本次为描述统计。')}</p></>}
      <p>{t("工作表：")}{descriptive.selection.sheet_name}{t("；完成时间：")}{new Date(descriptive.completed_at).toLocaleString(locale)}</p>
      <p>{t("数值：")}{descriptive.selection.numeric_column} · {descriptive.numeric_name}{t("；单位：")}{descriptive.selection.unit || t("未填写")}{t("； 分组：")}{descriptive.selection.group_column ? `${descriptive.selection.group_column} · ${descriptive.group_name}` : t("不分组")}</p>
      <p>{t((descriptive.source?.schema_version??0) >= 2 ? '当前整理保留 {total} 行 − 本分析排除 {excluded} 行 = 本分析有效 {valid} 行。' : descriptive.source?.kind === 'prepared_dataset_version' ? '本次使用 {valid} 行，排除 {excluded} 行；所选整理区域共 {total} 行。' : '本次使用 {valid} 行，排除 {excluded} 行；原始数据共 {total} 行。', { valid: descriptive.check.valid_count, excluded: descriptive.check.excluded_count, total: descriptive.check.row_count })}</p>
      <div className="field-table-scroll" role="region" aria-label={t("统计结果，可横向滚动")} tabIndex={0}>
        <table className="field-table statistics-table"><caption>{t("描述统计结果")}</caption>
          <thead><tr>{[t("范围 / 分组"), t("样本数 n"), t("均值"), t("样本标准差"), t("最小值"), 'Q1', t("中位数"), 'Q3', t("最大值"), t("四分位距")].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index}><th scope="row">{row.label}</th><td>{row.statistics.n}</td>
            {(['mean', 'std', 'min', 'q1', 'median', 'q3', 'max', 'iqr'] as const).map(metric =>
              <td key={metric} title={row.statistics[metric] === null ? t("无法计算，详见下方提示") : String(row.statistics[metric])}>{formatted(row.statistics[metric], locale)}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
      {rows.some(row => row.statistics.warnings.length > 0) && <ul className="warning-panel">{rows.flatMap((row, index) => row.statistics.warnings.map(note =>
        <li key={`${index}:${note}`}><strong>{row.label}：</strong><span>{workflowNotice(note, t)}</span></li>))}</ul>}
      {descriptive.check.warnings.length > 0 && <ul className="warning-panel">{descriptive.check.warnings.map(note => <li key={note}>{workflowNotice(note, t)}</li>)}</ul>}
      <p className="muted">{t((descriptive.source?.schema_version??0) >= 2 ? "统计在当前整理保留记录上按所选变量执行完整记录规则，不填补或额外去重、删异常；上游质量处理见该版本回执。样本标准差使用 n−1 分母，分位数采用线性插值；不足或无法计算的指标显示“—”。" : "样本标准差使用 n−1 分母；Q1、中位数、Q3 按位置 (n−1)p 线性插值；四分位距 = Q3 − Q1。 有效样本不足 2 条时标准差为“—”。数值溢出也显示“—”并提示。总体与分组使用相同的完整记录规则，未插补、未去重、未剔除离群值。")}</p>
      <p className="muted">{t("表格显示最多 6 位有效数字，悬停可查看保存值。此步仅描述数据分布，未进行显著性检验。")}</p>
      <details className="statistics-provenance"><summary>{t("计算来源与方法记录")}</summary>
        <p>{t("文件：")}{descriptive.filename}</p>
        <p>{t("开始时间：")}{descriptive.started_at}{t("；完成时间：")}{descriptive.completed_at}</p>
      </details>
    </>}
    {correlation&&<><SourceSummary source={correlation.source} filename={correlation.filename}/>{!state?.is_current&&<p className="warning-panel">{t('以下为历史结果。设置已变更，请重新分析。')}</p>}<ResearchBasis selection={correlation.selection} value={correlation.analysis_context.plan.research_request!}/><CorrelationResults result={correlation}/></>}
    {modeling&&<><SourceSummary source={modeling.source} filename={modeling.filename}/>{!state?.is_current&&<p className="warning-panel">{t('以下为历史结果。设置已变更，请重新分析。')}</p>}<ResearchBasis selection={modeling.selection} value={modeling.analysis_context.plan.research_request!}/><ModelResults result={modeling}/></>}
    {comparison&&<><SourceSummary source={comparison.source} filename={comparison.filename}/>{!state?.is_current&&<p className="warning-panel">{t('以下为历史结果。设置已变更，请重新分析。')}</p>}<ResearchBasis selection={comparison.selection} value={comparison.analysis_context.plan.research_request!}/><ComparisonResults result={comparison}/></>}
  </section></WorkflowStage>
  {navigation&&['figure','explanation','report'].includes(navigation.stage)&&<nav className="analysis-workflow-nav" aria-label={t('成果任务')}><button type="button" aria-current={artifactMode==='current'?'step':undefined} onClick={()=>setArtifactMode('current')}>{t('当前结果成果')}</button><button type="button" aria-current={artifactMode==='workbench'?'step':undefined} onClick={()=>setArtifactMode('workbench')}>{t('图表工作台与集合')}</button></nav>}
  <div hidden={!!navigation&&artifactMode!=='current'}>
   {legacyRuns.length>1&&(!navigation||['figure','explanation','report'].includes(navigation.stage))&&<label>{t('单次运行成果')}<select value={legacyRunId} onChange={e=>setLegacyRunId(e.target.value)}>{legacyRuns.map(run=><option key={run.id} value={run.id}>{t('配置修订 {number}',{number:run.setup_revision})} · {run.source?.sheet_name??run.selection.sheet_name} · {new Date(run.completed_at).toLocaleString(locale)}</option>)}</select></label>}
   {legacyRuns.map(run=><div key={run.id} hidden={legacyRunId!==run.id}>
      <RunFigure base={base} runId={run.id} revision={run.setup_revision} source={run.source} filename={run.filename}
        legacyFallbackAllowed={run.schema_version===2&&run.analysis_context?.plan.research_request?.output_language==='en'} artifactVersion={run.result_type==='regression'||run.result_type==='roc'||run.result_type==='survival'?4:undefined} figureKind={run.result_type==='regression'?'forest':run.result_type==='roc'?'roc_curve':run.result_type==='survival'?'kaplan_meier':run.result_type==='group_comparison'?(run.selection.design==='paired'?'paired_connected':'group_boxplot'):run.result_type==='correlation'?(run.selection.mode==='pair'?'scatter':'correlation_heatmap'):'boxplot'} outputLanguage={run.analysis_context?.plan.research_request?.output_language??'zh-CN'} comparison={run.result_type==='group_comparison'} planSha={run.analysis_context?.plan.sha256} modern={run.schema_version===5||run.schema_version===4||run.schema_version===3||run.schema_version===2&&run.analysis_context?.plan.research_request?.output_language==='en'}
        canGenerate={run.id===result?.id&&fieldsMatch && revisionMatches && !!state?.is_current} disabled={disabled || loading || running || !!error} onRunBusyChange={onRunBusyChange} />
   </div>)}
  </div>
  <div hidden={!!navigation&&artifactMode!=='workbench'}><ConfirmedRunArtifacts base={base} current={result} disabled={disabled||running} onHistoricalSelection={setHistoricalSelection}/></div>
  {!result && !historicalSelection && !loading && !error && navigation && <WorkflowEmptyResults message={modelMethod?'请先完成已确认分析，再生成图表、解释和报告。':isComparison?'请先完成组间比较，再生成图表、解释和报告。':isCorrelation?'请先完成相关分析，再生成图表、解释和报告。':'请先完成描述统计，再生成图表、解释和报告。'} />}
  </>
}
