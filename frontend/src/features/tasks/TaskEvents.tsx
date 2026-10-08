import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { taskRequest } from './taskApi'
import { eventNames, isEventPage, phaseNames, type EventPage, type TaskEvent } from './taskTypes'
import { useDocumentVisible } from './useDocumentVisible'

export default function TaskEvents({ taskId, live, refreshKey }: { taskId: string; live: boolean; refreshKey: number }) {
  const { t, locale } = useI18n()
  const visible = useDocumentVisible()
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [hasMore, setHasMore] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const cursor = useRef(0)
  useEffect(() => {
    if (!visible) return
    let mounted = true; let timer = 0
    const controller = new AbortController()
    async function load() {
      const after = cursor.current
      try {
        const result = await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/events?after=${after}&limit=50`, controller,
          (value): value is EventPage => isEventPage(value, taskId, after), '任务记录读取失败，请重试。')
        if (!mounted || controller.signal.aborted) return
        cursor.current = result.next_cursor
        setEvents(previous => [...new Map([...previous, ...result.items].map(event => [event.seq, event])).values()].sort((a, b) => a.seq - b.seq))
        setError(''); setHasMore(result.has_more)
        // Drain only one bounded page each cycle; the cursor never skips an unread page.
        if (live || result.has_more) timer = window.setTimeout(() => void load(), 5000)
      } catch (cause) { if (mounted) setError(safeError(cause, '任务记录读取失败，请重试。')) }
      finally { if (mounted) setLoading(false) }
    }
    void load()
    return () => { mounted = false; controller.abort(); window.clearTimeout(timer) }
  }, [taskId, live, refreshKey, visible, attempt])
  return <section className="task-events" aria-label={t('执行记录')} aria-busy={loading}>
    <div className="task-section-heading"><h3>{t('执行记录')}</h3><button type="button" disabled={loading} onClick={() => { setLoading(true); setError(''); setAttempt(value => value + 1) }}>{t('刷新执行记录')}</button></div>
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {loading && !events.length && <p role="status">{t('正在读取执行记录……')}</p>}
    {!loading && !events.length && !error && <p>{t('尚无已保存的执行记录。')}</p>}
    <ol className="task-event-list">{events.map(event => <li key={event.seq}>
      <span className="task-event-dot" aria-hidden="true" /><div><strong>{t(eventNames[event.event_type])}</strong>
        <p>{t(phaseNames[event.phase])}</p><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString(locale)}</time></div>
    </li>)}</ol>
    {hasMore && <button type="button" disabled={loading} onClick={() => { setLoading(true); setError(''); setAttempt(value => value + 1) }}>{t('继续加载执行记录')}</button>}
  </section>
}
