import { useEffect, useRef, useState, type FormEvent } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { DateValue, Filters, Pagination, ReadState, Table } from './OperationsCommon'
import { OperationsError, operationsRequest, queryUrl, useOperationsRead, type Account, type Page } from './operationsApi'

const assignmentsPath = '/api/v1/admin/project-assignments'

type Assignment = {
  id: string
  name: string
  research_topic: string
  customer_email: string
  analyst_id: string | null
  analyst_email: string | null
  revision: number
  submitted_version: number | null
  progress_status: string
}
type AssignmentEvent = {
  id: string
  actor_email: string
  previous_analyst_email: string | null
  analyst_email: string | null
  revision: number
  reason: string
  created_at: string
}
type EditorMode = 'assign' | 'revoke'
type Panel = { mode: EditorMode | 'history'; project: Assignment }
type Shared = { active: boolean; onForbidden: () => void }

const progressNames: Record<string, string> = {
  draft: '待提交需求',
  pending_assignment: '待分配',
  assigned: '已分配',
  analyzing: '分析中',
  needs_materials: '待补资料',
  delivered: '已交付',
}

export default function ProjectAssignmentsPanel({ active, onForbidden, registerLeaveGuard }: Shared & {
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [panel, setPanel] = useState<Panel | null>(null)
  const [notice, setNotice] = useState('')
  const read = useOperationsRead<Page<Assignment>>(queryUrl(assignmentsPath, filters, page), onForbidden, active && !panel)

  function open(project: Assignment, mode: Panel['mode']) {
    setNotice('')
    setPanel({ project, mode })
  }

  return <section aria-label={t('项目分配')} className="project-assignments">
    <h2>{t('项目分配')}</h2>
    {notice && <p role="status">{t(notice)}</p>}
    {panel ? (panel.mode === 'history'
      ? <AssignmentHistory key={panel.project.id} project={panel.project} active={active} onForbidden={onForbidden} onBack={() => setPanel(null)} />
      : <AssignmentEditor key={panel.project.id + panel.mode} project={panel.project} mode={panel.mode}
        active={active} onForbidden={onForbidden} registerLeaveGuard={registerLeaveGuard} onBack={() => setPanel(null)}
        onSaved={message => { setPanel(null); setNotice(message); read.reload() }} />) : <>
      <Filters fields={[{ key: 'q', label: '搜索项目或客户', maxLength: 254 }]} applyLabel="搜索项目"
        initial={filters} onApply={value => { setFilters(value); setPage(1) }} />
      <button type="button" onClick={read.reload} disabled={read.loading}>{t('刷新')}</button>
      <ReadState {...read} empty={read.data?.items.length === 0} />
      {read.data && read.data.items.length > 0 && <Table headers={['项目', '客户', '任务进度', '当前分析员', '操作']}>
        {read.data.items.map(project => <tr key={project.id}>
          <td><strong>{project.name}</strong><small>{project.research_topic}</small></td>
          <td>{project.customer_email}</td>
          <td>{t(progressNames[project.progress_status] ?? '未知')}
            {project.submitted_version != null && <small>{t('需求版本 {version}', { version: project.submitted_version })}</small>}
          </td>
          <td>{project.analyst_email ?? t('未分配')}</td>
          <td><div className="assignment-actions">
            <button type="button" onClick={() => open(project, 'assign')}>{t(project.analyst_id ? '更换分析员' : '分配分析员')}</button>
            {project.analyst_id && <button type="button" onClick={() => open(project, 'revoke')}>{t('撤回授权')}</button>}
            <button type="button" onClick={() => open(project, 'history')}>{t('查看分配记录')}</button>
          </div></td>
        </tr>)}
      </Table>}
      {read.data && <Pagination page={page} total={read.data.total} size={read.data.page_size} onChange={setPage} />}
    </>}
  </section>
}

function AssignmentEditor({ project, mode, active, onForbidden, onBack, onSaved, registerLeaveGuard }: Shared & {
  project: Assignment
  mode: EditorMode
  onBack: () => void
  onSaved: (message: string) => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Pick<Account, 'id' | 'email'> | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const candidates = useOperationsRead<Page<Account>>(queryUrl('/api/v1/admin/users', filters, page, {
    role: 'analyst', review_status: 'approved', active: 'true',
  }), onForbidden, active && mode === 'assign')
  useEffect(() => () => request.current?.abort(), [])
  const dirty = !!(reason.trim() || selected)
  useDraftLeaveGuard(registerLeaveGuard, dirty, busy)

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (request.current || (mode === 'assign' && (!selected || selected.id === project.analyst_id))) return
    const trimmed = reason.trim()
    const characters = Array.from(trimmed)
    if (characters.length < 5 || characters.length > 500 || characters.some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) {
      setError('请填写 5 至 500 字的分配理由。')
      return
    }
    const analystId = mode === 'revoke' ? null : selected!.id
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    try {
      const result = await operationsRequest<Assignment>(`${assignmentsPath}/${encodeURIComponent(project.id)}`, controller.signal, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analyst_id: analystId, expected_revision: project.revision, reason: trimmed }),
      })
      if (controller.signal.aborted) return
      if (result.id !== project.id || result.analyst_id !== analystId || result.revision !== project.revision + 1) {
        throw new Error('项目分配结果待确认，请刷新列表核对。')
      }
      onSaved(mode === 'revoke' ? '项目授权已撤回。' : project.analyst_id ? '分析员已更换。' : '项目已分配。')
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof OperationsError && cause.status === 403) onForbidden()
      else setError(safeError(cause, '项目分配保存失败，请刷新后重试。'))
    } finally {
      request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <div className="assignment-detail">
    <h3>{project.name}</h3>
    <p>{t('当前分析员')} · {project.analyst_email ?? t('未分配')}</p>
    {mode === 'assign' && <>
      <Filters fields={[{ key: 'q', label: '搜索分析员邮箱', maxLength: 254 }]} applyLabel="搜索分析员"
        disabled={busy} onApply={value => { setFilters(value); setPage(1) }} />
      <ReadState {...candidates} empty={candidates.data?.items.length === 0} />
      {candidates.data && <>
        <fieldset className="assignment-candidates" disabled={busy}>
          <legend>{t('选择分析员')}</legend>
          {candidates.data.items.map(analyst => <label key={analyst.id}>
            <input type="radio" name="assignment-analyst" checked={selected?.id === analyst.id}
              disabled={analyst.id === project.analyst_id} onChange={() => setSelected(analyst)} />
            {analyst.email}
          </label>)}
        </fieldset>
        <Pagination page={page} total={candidates.data.total} size={candidates.data.page_size} onChange={setPage} disabled={busy} />
      </>}
      {selected && <p>{t('已选分析员')} · {selected.email}</p>}
    </>}
    {mode === 'revoke' && <p>{t('撤回后，当前分析员将失去此项目的访问权限。')}</p>}
    <form className="operations-editor" onSubmit={event => void save(event)} aria-busy={busy}>
      <label>{t('分配理由')}<input required minLength={5} maxLength={500} disabled={busy} value={reason}
        onChange={event => setReason(event.target.value)} /></label>
      {error && <p role="alert" className="error-panel">{t(error)}</p>}
      <div className="assignment-actions">
        <button type="submit" disabled={busy || (mode === 'assign' && !selected)}>
          {t(busy ? '正在保存……' : mode === 'revoke' ? '确认撤回' : project.analyst_id ? '确认更换' : '确认分配')}
        </button>
        <button type="button" disabled={busy} onClick={() => {
          if (!dirty || window.confirm(t('放弃未保存的分配修改？'))) onBack()
        }}>{t('返回项目分配')}</button>
      </div>
    </form>
  </div>
}

function AssignmentHistory({ project, active, onForbidden, onBack }: Shared & { project: Assignment; onBack: () => void }) {
  const { t } = useI18n()
  const [page, setPage] = useState(1)
  const path = `${assignmentsPath}/${encodeURIComponent(project.id)}/events`
  const read = useOperationsRead<Page<AssignmentEvent>>(queryUrl(path, {}, page), onForbidden, active)
  return <div className="assignment-detail">
    <button type="button" onClick={onBack}>{t('返回项目分配')}</button>
    <h3>{t('分配记录')} · {project.name}</h3>
    <ReadState {...read} empty={read.data?.items.length === 0} />
    {read.data && read.data.items.length > 0 && <>
      <Table headers={['时间', '操作人', '原分析员', '新分析员', '分配理由', '版本']}>
        {read.data.items.map(event => <tr key={event.id}>
          <td><DateValue value={event.created_at} /></td><td>{event.actor_email}</td>
          <td>{event.previous_analyst_email ?? t('未分配')}</td><td>{event.analyst_email ?? t('未分配')}</td>
          <td>{event.reason}</td><td>{event.revision}</td>
        </tr>)}
      </Table>
      <Pagination page={page} total={read.data.total} size={read.data.page_size} onChange={setPage} />
    </>}
  </div>
}
