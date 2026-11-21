import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import type { Project } from '../projects/projectTypes'
import { analysisTypeChoices } from '../customer/customerRequirementChoices'
import { Filters, Pagination, ReadState, Table } from './OperationsCommon'
import { OperationsError, operationsRequest, queryUrl, useOperationsRead, type Account, type Page } from './operationsApi'

const assignmentsPath = '/api/v1/admin/project-assignments'
const headers = ['项目', '客户', '所需分析', '任务进度', '当前分析员', '操作']
// Interface design section five: each filter maps to repeated status parameters; "all" sends none.
const statusFilters = [
  { key: 'pending', label: '待分配', statuses: ['pending_assignment'] },
  { key: 'active', label: '处理中', statuses: ['assigned', 'analyzing', 'needs_materials', 'materials_submitted'] },
  { key: 'all', label: '全部', statuses: [] },
] as const
type StatusFilter = typeof statusFilters[number]['key']

type Assignment = {
  id: string
  name: string
  research_topic: string
  project_type: Project['project_type']
  customer_email: string
  analyst_id: string | null
  analyst_email: string | null
  revision: number
  submitted_version: number | null
  progress_status: string
  required_analyses?: string[]
}
type AssignmentTarget = { mode: 'assign' | 'revoke'; project: Assignment }
type Overrides = { source: Page<Assignment> | null; rows: Record<string, Assignment> }
type Shared = { active: boolean; onForbidden: () => void }

const progressNames: Record<string, string> = {
  draft: '待提交需求',
  pending_assignment: '待分配',
  assigned: '已分配',
  analyzing: '分析中',
  needs_materials: '待补资料',
  materials_submitted: '已补交，等待核对',
  delivered: '已交付',
}

// Same labels as the customer requirements page shows for each analysis type.
const analysisLabels = new Map(analysisTypeChoices.map(choice => [choice.id.slice('customer.type.'.length), choice.label]))

function useAnalysisNames() {
  const { t } = useI18n()
  return (project: Assignment) => project.required_analyses?.length
    ? project.required_analyses.map(key => t(analysisLabels.get(key) ?? '未知')).join('、')
    : '—'
}

const assignable = (project: Assignment) => project.project_type === 'research' && !project.analyst_id

export default function ProjectAssignmentsPanel({ active, onForbidden, registerLeaveGuard }: Shared & {
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const analysisNames = useAnalysisNames()
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending')
  const [page, setPage] = useState(1)
  const [target, setTarget] = useState<AssignmentTarget | null>(null)
  const [overrides, setOverrides] = useState<Overrides>({ source: null, rows: {} })
  const [finished, setFinished] = useState(false)
  const panel = useRef<HTMLElement>(null)
  const opener = useRef<HTMLButtonElement>(null)
  const assignButtons = useRef(new Map<string, HTMLButtonElement>())
  const statusQuery = new URLSearchParams(statusFilters.find(item => item.key === statusFilter)!.statuses.map(status => ['status', status])).toString()
  const read = useOperationsRead<Page<Assignment>>(queryUrl(assignmentsPath, filters, page) + (statusQuery ? `&${statusQuery}` : ''), onForbidden, active)
  // A new assignment stays on its row (the list is not re-read) until the next read replaces the page.
  const items = read.data?.items.map(project => (overrides.source === read.data ? overrides.rows[project.id] : undefined) ?? project)

  function open(project: Assignment, mode: AssignmentTarget['mode'], button: HTMLButtonElement) {
    opener.current = button
    setFinished(false)
    setTarget({ project, mode })
  }

  function chooseFilter(key: StatusFilter) {
    setStatusFilter(key)
    setPage(1)
    setFinished(false)
  }

  function close(saved: Assignment | null) {
    const previous = target
    const button = opener.current
    setTarget(null)
    opener.current = null
    if (!saved) {
      button?.focus({ preventScroll: true })
      return
    }
    if (previous?.mode === 'assign' && !previous.project.analyst_id && items && read.data) {
      const source = read.data
      setOverrides(current => ({ source, rows: { ...current.source === source ? current.rows : {}, [saved.id]: saved } }))
      const index = items.findIndex(project => project.id === saved.id)
      const next = items.slice(index + 1).find(assignable) ?? items.slice(0, Math.max(index, 0)).find(assignable)
      const nextButton = next && assignButtons.current.get(next.id)
      if (nextButton) nextButton.focus({ preventScroll: true })
      else {
        setFinished(source.page * source.page_size >= source.total)
        panel.current?.focus({ preventScroll: true })
      }
      return
    }
    read.reload()
    panel.current?.focus({ preventScroll: true })
  }

  return <section aria-label={t('项目分配')} className="admin-account-panel project-assignments" ref={panel} tabIndex={-1}>
    <h2>{t('项目分配')}</h2>
    <div className="admin-account-filters">
      <Filters fields={[{ key: 'q', label: '搜索项目或客户', maxLength: 254 }]} applyLabel="搜索项目"
        initial={filters} onApply={value => { setFilters(value); setPage(1); setFinished(false) }} />
      <button type="button" onClick={read.reload} disabled={read.loading}>{t('刷新')}</button>
    </div>
    <div className="assignment-status-filter" role="group" aria-label={t('筛选项目')}>
      {statusFilters.map(item => <button key={item.key} type="button" aria-pressed={statusFilter === item.key}
        className={statusFilter === item.key ? 'button-primary' : undefined} onClick={() => chooseFilter(item.key)}>{t(item.label)}</button>)}
    </div>
    {finished && <p role="status" className="assignment-finished">{t('待分配项目已处理完。')}</p>}
    <Table headers={headers}>
      {items?.map(project => <tr key={project.id}>
        <td><strong>{project.name}</strong><small>{project.research_topic}</small></td>
        <td>{project.customer_email}</td>
        <td>{analysisNames(project)}</td>
        <td>{t(progressNames[project.progress_status] ?? '未知')}
          {project.submitted_version != null && <small>{t('需求版本 {version}', { version: project.submitted_version })}</small>}
        </td>
        <td>{project.analyst_email ?? t('未分配')}</td>
        <td><div className="assignment-actions">
          {project.project_type === 'research' && <button type="button" aria-haspopup="dialog"
            ref={element => {
              if (element && !project.analyst_id) assignButtons.current.set(project.id, element)
              else assignButtons.current.delete(project.id)
            }}
            onClick={event => open(project, 'assign', event.currentTarget)}>
            {t(project.analyst_id ? '更换分析员' : '分配分析员')}
          </button>}
          {project.analyst_id && <button type="button" aria-haspopup="dialog" onClick={event => open(project, 'revoke', event.currentTarget)}>
            {t('撤回授权')}
          </button>}
        </div></td>
      </tr>)}
      {!read.data?.items.length && <tr><td colSpan={headers.length}><ReadState {...read} empty={read.data?.items.length === 0} /></td></tr>}
    </Table>
    <div className="admin-account-pager">
      {read.data && <Pagination page={page} total={read.data.total} size={read.data.page_size} onChange={setPage} />}
    </div>
    {target && <AssignmentDialog {...target} active={active} onForbidden={onForbidden}
      registerLeaveGuard={registerLeaveGuard} onClose={close} />}
  </section>
}

function AssignmentDialog({ project, mode, active, onForbidden, onClose, registerLeaveGuard }: Shared & AssignmentTarget & {
  onClose: (saved: Assignment | null) => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const analysisNames = useAnalysisNames()
  const id = useId()
  const dialog = useRef<HTMLDialogElement>(null)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Pick<Account, 'id' | 'email'> | null>(null)
  const [revokeReason, setRevokeReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const assigning = mode === 'assign'
  const analystId = assigning ? selected?.id : null
  const title = assigning ? (project.analyst_id ? '更换分析员' : '分配分析员') : '撤回授权'
  const candidates = useOperationsRead<Page<Account>>(queryUrl('/api/v1/admin/users', {}, page, {
    role: 'analyst', review_status: 'approved',
  }), onForbidden, active && assigning)
  const analysts = candidates.data?.items ?? []
  useEffect(() => () => request.current?.abort(), [])
  useLayoutEffect(() => {
    const element = dialog.current
    if (!active || !element) return
    element.showModal()
    return () => { if (element.open) element.close() }
  }, [active])
  useDraftLeaveGuard(registerLeaveGuard, !!(selected || revokeReason.trim()), busy)

  function dismiss(saved: Assignment | null) {
    dialog.current?.close()
    onClose(saved)
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (request.current || analystId === undefined || analystId === project.analyst_id) return
    const reason = assigning ? (project.analyst_id ? '权限管理更换分析员' : '权限管理分配分析员') : revokeReason.trim()
    if (!assigning) {
      const characters = Array.from(reason)
      if (characters.length < 5 || characters.length > 500 || characters.some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) {
        setError('请填写 5 至 500 字的撤回理由。')
        return
      }
    }
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    try {
      const result = await operationsRequest<Assignment>(`${assignmentsPath}/${encodeURIComponent(project.id)}`, controller.signal, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analyst_id: analystId, expected_revision: project.revision, reason }),
      })
      if (controller.signal.aborted) return
      if (result.id !== project.id || result.analyst_id !== analystId || result.revision !== project.revision + 1) {
        throw new Error('项目分配结果待确认，请刷新列表核对。')
      }
      dismiss(result)
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof OperationsError && cause.status === 403) onForbidden()
      else setError(safeError(cause, '项目分配保存失败，请刷新后重试。'))
    } finally {
      request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <dialog ref={dialog} className="assignment-dialog" aria-labelledby={`${id}-title`} aria-describedby={`${id}-project`}
    aria-busy={busy} onCancel={event => { event.preventDefault(); if (!request.current) dismiss(null) }}>
    <h2 id={`${id}-title`}>{t(title)}</h2>
    <p id={`${id}-project`}><strong>{project.name}</strong> · {project.customer_email}</p>
    {project.analyst_email && <p>{t('当前分析员')} · {project.analyst_email}</p>}
    {assigning && <p className="muted">{t('所需分析：{names}', { names: analysisNames(project) })}</p>}
    {assigning && <>
      <ReadState {...candidates} empty={candidates.data?.items.length === 0} />
      {analysts.length > 0 && <fieldset className="assignment-candidates" disabled={busy}>
        <legend>{t('选择分析员')}</legend>
        {analysts.map(analyst => <label key={analyst.id}>
          <input type="radio" name="assignment-analyst" checked={selected?.id === analyst.id}
            disabled={!analyst.active || analyst.id === project.analyst_id} onChange={() => setSelected(analyst)} />
          {analyst.email}
          {!analyst.active && <span className="status-badge">{t('停用')}</span>}
        </label>)}
      </fieldset>}
      {analysts.length > 0 && analysts.every(analyst => !analyst.active) &&
        <p className="assignment-availability">{t('在账号管理启用分析员后即可分配。')}</p>}
      {candidates.data && (page > 1 || candidates.data.total > candidates.data.page_size) &&
        <div className="admin-account-pager">
          <Pagination page={page} total={candidates.data.total} size={candidates.data.page_size} onChange={setPage} disabled={busy} />
        </div>}
      {selected && !analysts.some(analyst => analyst.id === selected.id) && <p>{t('已选分析员')} · {selected.email}</p>}
    </>}
    {!assigning && <p>{t('撤回后，当前分析员将失去此项目的访问权限。')}</p>}
    <form onSubmit={event => void save(event)}>
      {!assigning && <label>{t('撤回理由')}<input required minLength={5} maxLength={500} disabled={busy} value={revokeReason}
        onChange={event => setRevokeReason(event.target.value)} /></label>}
      {error && <p role="alert" className="error-panel">{t(error)}</p>}
      <div className="assignment-dialog-actions">
        <button type="button" disabled={busy} onClick={() => dismiss(null)}>{t('取消')}</button>
        <button type="submit" className={assigning ? 'button-primary' : 'button-destructive'} disabled={busy || analystId === undefined || analystId === project.analyst_id}>
          {t(busy ? '正在保存……' : assigning ? '确认分配' : '确认撤回')}
        </button>
      </div>
    </form>
  </dialog>
}
