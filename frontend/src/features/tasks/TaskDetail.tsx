import { useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import TaskModelUsage from '../model-usage/TaskModelUsage'
import TaskEvents from './TaskEvents'
import TaskPendingAction from './TaskPendingAction'
import { isWorkspace, phaseNames, taskDisplayName, taskNames, type TaskWorkspace } from './taskTypes'
import { taskRequest, TaskRequestError } from './taskApi'
import { useDocumentVisible } from './useDocumentVisible'

type Props = { projectId: string; taskId: string; onChanged: () => void }
export default function TaskDetail(props: Props) { return <Detail key={`${props.projectId}:${props.taskId}`} {...props} /> }
function Detail({ projectId, taskId, onChanged }: Props) {
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
      <dl className="task-facts"><div><dt>{t('来源文件')}</dt><dd>{data.source.filename}</dd></div>
        <div><dt>{t('输入版本')}</dt><dd><span>{t('分析配置 v{revision}', { revision: data.task.input_version.setup_revision })}</span>
          <small>{t(data.source.is_current ? '当前分析配置' : '历史分析配置')}</small></dd></div>
        <div><dt>{t('处理阶段')}</dt><dd>{t(phaseNames[data.task.phase])}</dd></div>
        <div><dt>{t('建立时间')}</dt><dd><time dateTime={data.task.created_at}>{new Date(data.task.created_at).toLocaleString(locale)}</time></dd></div></dl>
      {data.task.error_code && <p className="warning-panel">{t(apiError({ code: data.task.error_code }, '任务暂未完成，请查看处理说明。'))}</p>}
      <TaskPendingAction workspace={data} blocked={loading || !!error} onChanged={() => { refresh(); onChanged() }} />
      <section className="task-artifacts" aria-label={t('此任务的成果')}><h3>{t('此任务的成果')}</h3>
        {data.artifacts.figure && <article><h4>{data.artifacts.figure.title}</h4><p>{data.artifacts.figure.caption}</p>
          <ProjectDownloadLink href={data.artifacts.figure.download_url} filename="boxplot.png">{t('下载此任务的 PNG')}</ProjectDownloadLink></article>}
        {data.artifacts.explanation && <article className="task-saved-explanation"><p className="warning-panel">{t('AI 草稿，需人工审核。')}</p>
          {data.artifacts.explanation.sections.map((section, index) => <section key={`${section.key}:${index}`}><h4>{section.title}</h4><p>{section.text}</p></section>)}
          {data.artifacts.explanation.limitations.length > 0 && <><h4>{t('解释限制')}</h4><ul>{data.artifacts.explanation.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></>}</article>}
        {data.artifacts.report && <article><h4>{t('Word 分析报告')}</h4>
          <ProjectDownloadLink href={data.artifacts.report.download_url} filename={data.artifacts.report.filename}>{t('下载此任务的 Word')}</ProjectDownloadLink></article>}
        {!data.artifacts.figure && !data.artifacts.explanation && !data.artifacts.report && <p className="task-empty">{t('此任务尚无已保存的成果。')}</p>}
      </section>
      <TaskEvents taskId={taskId} live={live} refreshKey={attempt} />
      <TaskModelUsage taskId={taskId} refreshKey={attempt + data.task.revision} />
    </>}
  </section>
}
