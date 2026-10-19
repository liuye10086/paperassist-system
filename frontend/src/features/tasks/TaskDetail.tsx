import AssistanceResult from '../literature/AssistanceResult'
import StatisticsTaskArtifact from '../analysis/StatisticsTaskArtifact'
import StatisticsTaskRecovery from '../analysis/StatisticsTaskRecovery'
import SourceSummary from '../analysis/SourceSummary'
import { useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { apiError, safeError, translateForLocale, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import TaskModelUsage from '../model-usage/TaskModelUsage'
import TaskEvents from './TaskEvents'
import TaskPendingAction from './TaskPendingAction'
import { isWorkspace, taskPhaseName, taskDisplayName, taskNames, type TaskWorkspace } from './taskTypes'
import { taskRequest, TaskRequestError } from './taskApi'
import { useDocumentVisible } from './useDocumentVisible'

type Props = { projectId: string; taskId: string; onChanged: () => void; onOpenFiles?: () => void; onOpenLiterature?: (searchId:string)=>void }
const historicalErrorReasons: Record<string, string> = {
  task_failed: '旧任务执行失败。',
  explanation_invalid: '旧任务的解释未通过事实核验，未保存内容。',
  model_provider_unavailable: '旧任务执行时模型服务不可用。',
  model_submission_unknown: '旧任务的模型提交结果无法确认。',
}
function historicalErrorReason(code: string) {
  return Object.hasOwn(historicalErrorReasons, code) ? historicalErrorReasons[code] : '旧系统记录了任务异常，具体原因无法确认。'
}
export default function TaskDetail(props: Props) { return <Detail key={`${props.projectId}:${props.taskId}`} {...props} /> }
function Detail({ projectId, taskId, onChanged, onOpenFiles, onOpenLiterature }: Props) {
  const { t, locale } = useI18n()
  const visible = useDocumentVisible()
  const [data, setData] = useState<TaskWorkspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [sessionValid, setSessionValid] = useState(true)
  const request = useRef<AbortController | null>(null)
  const heading = useRef<HTMLHeadingElement | null>(null)
  useEffect(() => { heading.current?.focus({ preventScroll: true }) }, [])
  useEffect(() => onApiSessionChanged(() => {
    request.current?.abort(); setSessionValid(false); setData(null); setError(''); setLoading(false)
  }), [])
  useEffect(() => {
    if (!sessionValid || !visible) return
    let mounted = true; let timer = 0
    const controller = new AbortController(); request.current = controller
    async function load() {
      try {
        const value = await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/workspace`, controller,
          (result): result is TaskWorkspace => isWorkspace(result, projectId, taskId), '任务详情读取失败，请重试。')
        if (!mounted || controller.signal.aborted) return
        setData(value); setError('')
        if (!['succeeded', 'failed'].includes(value.task.status)) timer = window.setTimeout(() => void load(), 5000)
      } catch (cause) {
        if (!mounted) return
        if (cause instanceof TaskRequestError && cause.status === 404) setData(null)
        setError(cause instanceof TaskRequestError && cause.status === 404 ? '任务不存在或无权访问，请选择其他任务。'
          : safeError(cause, '任务详情读取失败，请重试。'))
      } finally { if (mounted) setLoading(false) }
    }
    void load()
    return () => { mounted = false; controller.abort(); window.clearTimeout(timer) }
  }, [projectId, taskId, sessionValid, visible, attempt])
  function refresh() { request.current?.abort(); setLoading(true); setError(''); setAttempt(value => value + 1) }
  const live = !!data && !['succeeded', 'failed'].includes(data.task.status)
  return <section className="task-detail" aria-label={t('任务详情')} aria-busy={loading}>
    <div className="task-section-heading"><h2 ref={heading} tabIndex={-1}>{t('任务详情')}</h2>
      <button type="button" disabled={loading || !sessionValid} onClick={refresh}>{t('重新读取任务')}</button></div>
    {loading && !data && <p role="status">{t('正在读取任务详情……')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {!sessionValid && <p role="alert">{t('会话已失效，请重新登录。')}</p>}
    {data && sessionValid && <>
      <div className="task-detail-title"><h3>{t(taskNames[data.task.task_type])}</h3>
        <span className={`task-status task-status-${data.task.status}`}>{t(taskDisplayName(data.task))}</span></div>
      {data.task.origin === 'legacy' && <><p className="task-scope-note">{t('历史任务')}</p>
        <p className="task-scope-note">{t('旧系统未记录此任务的完整执行步骤和模型用量。')}</p></>}
      {['literature_search','literature_assistance'].includes(data.task.task_type)?null:!['parse_file', 'extract_dataset', 'review_ocr'].includes(data.task.task_type) && data.task.input_version.kind==='analysis_plan'&&data.task.input_version.source===null?<p>{t('研究材料；尚无可计算数据。')}</p>:<SourceSummary source={data.source.dataset_source} filename={data.source.filename} />}
      <dl className="task-facts"><div><dt>{t(['literature_search','literature_assistance'].includes(data.task.task_type)?'来源研究主题':'来源文件')}</dt><dd>{data.source.filename||t('研究材料')}</dd></div>
        <div><dt>{t('输入版本')}</dt><dd><span>{data.task.input_version.kind==='literature_assistance'?t('冻结的文献建议输入'):data.task.input_version.kind==='literature_search'?t('已冻结的文献检索条件'):data.task.input_version.kind==='report_collection'?t('集合导出版本 {number}',{number:data.task.input_version.export_revision}):['figure_projection','figure_workbench','figure_explanation'].includes(data.task.task_type)?t('冻结的图表配置与来源'):['parse_file', 'extract_dataset', 'review_ocr'].includes(data.task.task_type) ? t(data.task.task_type === 'review_ocr' ? '原图转录核对' : data.task.task_type === 'extract_dataset' ? '本地 Excel 结构提取' : '本地文件解析') : data.task.task_type === 'prepare_dataset' ? t('本地数据整理') : data.task.task_type === 'analysis_recommendation'?t('受限分析建议'):data.task.task_type === 'analysis_plan' ? t('整理数据分析计划') : t('分析配置 v{revision}', { revision: data.task.input_version.setup_revision ?? 0 })}</span>
          {!['literature_assistance','literature_search','figure_projection','figure_workbench','figure_explanation','collection_word_report','parse_file', 'extract_dataset', 'prepare_dataset', 'analysis_plan', 'analysis_recommendation', 'review_ocr'].includes(data.task.task_type) && <small>{t(data.source.is_current ? '当前分析配置' : '历史分析配置')}</small>}</dd></div>
        <div><dt>{t('处理阶段')}</dt><dd>{t(taskPhaseName(data.task))}</dd></div>
        <div><dt>{t('建立时间')}</dt><dd><time dateTime={data.task.created_at}>{new Date(data.task.created_at).toLocaleString(locale)}</time></dd></div></dl>
      {['figure_projection','figure_workbench','figure_explanation','collection_word_report','parse_file', 'extract_dataset', 'prepare_dataset', 'analysis_plan', 'analysis_recommendation', 'review_ocr'].includes(data.task.task_type) && onOpenFiles && <button type="button" onClick={onOpenFiles}>{t('查看项目文件')}</button>}
      {data.task.task_type==='literature_assistance'&&<p className="muted">{translateForLocale(data.source.is_current?'模型建议与人工决定独立保存；历史建议只读，不能自动确认或改写新版本。':'历史版本只读；旧判定和模型建议不能确认新论述。',data.task.input_version.output_language??locale)}</p>}
      {data.task.task_type==='literature_search'&&<p>{onOpenLiterature?<button type="button" onClick={()=>onOpenLiterature(data.task.id)}>{t('查看文献与候选')}</button>:<a href={`#project=${encodeURIComponent(projectId)}&section=literature&search=${encodeURIComponent(data.task.id)}`}>{t('查看文献与候选')}</a>}</p>}
      {data.task.error_code && (data.task.origin === 'legacy' ? <div className="warning-panel">
        <p>{t(historicalErrorReason(data.task.error_code))}</p><p>{t('此历史任务仅供查看，不支持恢复或重试。')}</p>
      </div> : <p className="warning-panel">{t(apiError({ code: data.task.error_code }, '任务暂未完成，请查看处理说明。'))}</p>)}
      {data.verification_failure&&<div className="warning-panel"><p>{t('云端图表数值未通过独立核对，下游成果已停止。')}</p><div className="field-table-scroll"><table className="field-table"><caption>{t('图表数值核对差异')}</caption><thead><tr>{['核对项目','本地期望','云端返回','差异原因'].map(k=><th key={k} scope="col">{t(k)}</th>)}</tr></thead><tbody>{data.verification_failure.differences.filter(d=>!/(?:sha256|digest|provenance|response|container|model_call|\.id$)/i.test(d.path)).map((d,i)=><tr key={i}><th scope="row">{d.path}</th><td>{String(d.expected??'—')}</td><td>{String(d.actual??'—')}</td><td>{d.reason??'—'}</td></tr>)}</tbody></table></div><p>{t('记录时间：')}{new Date(data.verification_failure.recorded_at).toLocaleString(locale)}</p></div>}
      {data.task.origin!=='legacy'&&data.task.task_type==='statistics_compute'&&<StatisticsTaskRecovery workspace={data} blocked={loading||!!error} onChanged={()=>{refresh();onChanged()}}/>}
      {data.task.origin !== 'legacy' && data.task.task_type!=='statistics_compute' && <TaskPendingAction workspace={data} blocked={loading || !!error} onChanged={() => { refresh(); onChanged() }} />}
      {data.task.task_type!=='review_ocr'&&<section className="task-artifacts" aria-label={t('此任务的成果')}><h3>{t('此任务的成果')}</h3>
        {data.artifacts.literature_assistance?.result&&<article><p className="warning-panel">{translateForLocale('模型建议，尚非人工决定',data.task.input_version.output_language??locale)}</p><AssistanceResult outputLanguage={data.task.input_version.output_language} kind={data.artifacts.literature_assistance.kind} result={data.artifacts.literature_assistance.result}/></article>}
        {data.artifacts.literature&&<p>{t('检索结果：已获取 {retrieved} 篇；匹配 {matched} 篇。',{retrieved:data.artifacts.literature.retrieved_count,matched:data.artifacts.literature.matched_count??t('尚未返回')})}</p>}
        {data.artifacts.analysis&&<StatisticsTaskArtifact result={data.artifacts.analysis}/>}
        {data.artifacts.figure && <article><h4>{data.artifacts.figure.title}</h4><p>{data.artifacts.figure.caption}</p>
          <ProjectDownloadLink href={data.artifacts.figure.download_url} filename={data.task.task_type==='figure_workbench'?'figure-package.zip':'boxplot.png'}>{t(data.task.task_type==='figure_workbench'?'下载图表与说明包':'下载此任务的 PNG')}</ProjectDownloadLink></article>}
        {data.artifacts.explanation && <article className="task-saved-explanation"><p className="warning-panel">{t('AI 草稿，需人工审核。')}</p>
          {data.artifacts.explanation.sections.map((section, index) => <section key={`${section.key}:${index}`}><h4>{section.title}</h4><p>{section.text}</p></section>)}
          {data.artifacts.explanation.limitations.length > 0 && <><h4>{t('解释限制')}</h4><ul>{data.artifacts.explanation.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></>}</article>}
        {data.artifacts.report && <article><h4>{t('Word 分析报告')}</h4>
          <ProjectDownloadLink href={data.artifacts.report.download_url} filename={data.artifacts.report.filename}>{t('下载此任务的 Word')}</ProjectDownloadLink></article>}
        {data.artifacts.dataset && <ProjectDownloadLink href={data.artifacts.dataset.download_url} filename={data.artifacts.dataset.filename}>{t('下载完整 JSON')}</ProjectDownloadLink>}
        {!data.artifacts.literature_assistance?.result && !data.artifacts.literature && !data.artifacts.analysis && !data.artifacts.dataset && !data.artifacts.figure && !data.artifacts.explanation && !data.artifacts.report && <p className="task-empty">{t(data.task.origin === 'legacy'
          ? '无法确认此历史任务关联的成果。' : ['parse_file', 'extract_dataset', 'review_ocr'].includes(data.task.task_type) && data.task.status === 'succeeded' ? (data.task.task_type === 'extract_dataset' ? '结构版本已保存，请到项目文件区查看。' : '文件已解析，请到项目文件区查看预览。') : '此任务尚无已保存的成果。')}</p>}
      </section>}
      {data.task.origin !== 'legacy' && <><TaskEvents taskId={taskId} taskType={data.task.task_type} live={live} refreshKey={attempt} />
        {!['literature_search','statistics_compute','parse_file', 'extract_dataset', 'prepare_dataset', 'analysis_plan', 'analysis_recommendation', 'review_ocr'].includes(data.task.task_type) && <TaskModelUsage taskId={taskId} refreshKey={attempt + data.task.revision} />}</>}
    </>}
  </section>
}
