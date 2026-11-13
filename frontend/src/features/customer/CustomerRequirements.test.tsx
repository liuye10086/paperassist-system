import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { apiFetch } from '../../shared/api/client'
import type { LeaveGuard, RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import type { Content, Intake, MaterialRef, Version } from '../research-intake/contracts'
import { emptyRequirement } from '../research-intake/state'
import CustomerRequirements from './CustomerRequirements'

vi.mock('../../shared/api/client', () => ({
  apiFetch: vi.fn(), getApiUserId: () => 'customer', onApiSessionChanged: () => () => {},
}))

const projectId = 'customer-project'
const base = `/api/v1/projects/${projectId}`
const singleCell = '单细胞 RNA 测序数据分析'
const bulk = 'RNA 转录组学分析'
const spatial = '空间转录组分析'

type Write = { expected_revision: number; operation: Version['operation']; content: Content; material_refs: MaterialRef[] }
function version(content: Content, operation: Version['operation'] = 'save', refs: MaterialRef[] = [], number = 1): Version {
  return { id: `v${number}`, project_id: projectId, version: number, operation, content,
    material_refs: refs, material_sources: [], sha256: 'a'.repeat(64), created_at: '2026-11-11T01:00:00Z' }
}

function server(current: Version | null = null) {
  const root: Intake = { project_id: projectId, revision: current ? 2 : 1, current_requirement: current,
    current_design: null, deliveries: [{ id: 'analysis-1', kind: 'analysis', name: 'analysis', active: true, origin: 'user_selected', revision: 1 }],
    capabilities: {}, gaps: [] }
  function commit(body: Write) {
    root.revision += 1
    root.current_requirement = version(body.content, body.operation, body.material_refs, (root.current_requirement?.version ?? 0) + 1)
    return Response.json({ project_id: projectId, revision: root.revision, version: root.current_requirement, gaps: [] }, { status: 201 })
  }
  vi.mocked(apiFetch).mockImplementation(async (url, init) => {
    if (url === `${base}/research-intake`) return Response.json(root)
    if (url === `${base}/requirements` && init?.method === 'POST') return commit(JSON.parse(String(init.body)))
    throw new Error(`Unexpected request ${url}`)
  })
  return { root, commit }
}

function writes() {
  return vi.mocked(apiFetch).mock.calls.filter(([url, init]) => url === `${base}/requirements` && init?.method === 'POST').map(([, init]) => ({
    body: JSON.parse(String(init?.body)) as Write,
    key: new Headers(init?.headers).get('Idempotency-Key'),
  }))
}

function checkbox(name: string) {
  return screen.getByRole('checkbox', { name }) as HTMLInputElement
}

function click(name: string) { fireEvent.click(screen.getByRole('button', { name })) }
async function open(onSubmitted = vi.fn(), registerLeaveGuard?: RegisterLeaveGuard) {
  const component = render(<CustomerRequirements projectId={projectId} onSubmitted={onSubmitted} registerLeaveGuard={registerLeaveGuard}/>)
  await screen.findByRole('checkbox', { name: singleCell })
  return component
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); sessionStorage.clear() })

it('shows five unfinished analysis types as disabled choices', async () => {
  server()
  await open()
  const types = within(screen.getByRole('group', { name: '分析类型' }))
  expect(types.getAllByRole('checkbox')).toHaveLength(7)
  expect(checkbox(singleCell).matches(':enabled')).toBe(true)
  expect(checkbox(bulk).matches(':enabled')).toBe(true)
  for (const name of [spatial, '代谢组学分析', '基因组学分析', '多组学联合分析', '肠道菌群16S-rRNA分析']) {
    const option = types.getByRole('checkbox', { name: `${name} 建设中` }) as HTMLInputElement
    expect(option.matches(':disabled')).toBe(true)
    expect(option.checked).toBe(false)
  }
})

it('groups dependent choices for every selected type and clears only the deselected type', async () => {
  server()
  await open()
  const analysis = within(screen.getByRole('group', { name: '个性化分析' }))
  const figures = within(screen.getByRole('group', { name: '图件与交付' }))
  expect(analysis.queryByRole('checkbox', { name: '拟时分析' })).toBeNull()
  expect(figures.getByRole('checkbox', { name: 'Word 报告' })).toBeTruthy()
  expect(figures.getByRole('checkbox', { name: '交付包' })).toBeTruthy()

  fireEvent.click(checkbox(singleCell))
  fireEvent.click(checkbox(bulk))
  const bulkAnalysis = within(analysis.getByRole('group', { name: bulk }))
  const singleCellAnalysis = within(analysis.getByRole('group', { name: singleCell }))
  const singleCellFigures = within(figures.getByRole('group', { name: singleCell }))
  expect(analysis.queryByRole('group', { name: spatial })).toBeNull()
  expect(bulkAnalysis.queryByRole('checkbox', { name: '拟时分析' })).toBeNull()
  fireEvent.click(singleCellAnalysis.getByRole('checkbox', { name: '拟时分析' }))
  fireEvent.click(singleCellFigures.getByRole('checkbox', { name: 'UMAP 图' }))
  fireEvent.click(bulkAnalysis.getByRole('checkbox', { name: '差异表达' }))
  fireEvent.click(figures.getByRole('checkbox', { name: 'Word 报告' }))

  fireEvent.click(checkbox(singleCell))
  expect(analysis.queryByRole('group', { name: singleCell })).toBeNull()
  expect(figures.queryByRole('group', { name: singleCell })).toBeNull()
  fireEvent.click(checkbox(singleCell))
  expect(checkbox('拟时分析').checked).toBe(false)
  expect(checkbox('UMAP 图').checked).toBe(false)
  expect((bulkAnalysis.getByRole('checkbox', { name: '差异表达' }) as HTMLInputElement).checked).toBe(true)
  expect(checkbox('Word 报告').checked).toBe(true)
})

it('keeps previously selected spatial scopes read-only and preserves them on save', async () => {
  const scope = [
    { id: 'customer.type.spatial', title: spatial, delivery_kind: 'analysis' },
    { id: 'customer.analysis.spatial.spatial_domains', title: '空间区域识别', delivery_kind: 'analysis' },
    { id: 'customer.figure.spatial.spatial_distribution', title: '空间分布图', delivery_kind: 'analysis' },
  ]
  server(version({ ...emptyRequirement(), scope_items: scope }))
  await open()
  const type = screen.getByRole('checkbox', { name: /^空间转录组分析/ }) as HTMLInputElement
  for (const option of [type, checkbox('空间区域识别'), checkbox('空间分布图')]) {
    expect(option.checked).toBe(true)
    expect(option.matches(':disabled')).toBe(true)
  }
  const analysis = within(screen.getByRole('group', { name: '个性化分析' }))
  expect(analysis.getByRole('checkbox', { name: '差异表达' }).matches(':disabled')).toBe(true)
  fireEvent.click(checkbox(bulk))
  click('保存草稿')
  await screen.findByText('草稿已保存。')
  expect(writes()[0].body.content.scope_items).toEqual([
    expect.objectContaining({ id: 'customer.type.bulk', title: 'RNA 转录组学分析（Bulk RNA-seq）' }),
    ...scope,
  ])
})

it('saves readable choices and restores them with legacy fields, delivery types and material references', async () => {
  const legacyScope = { id: 'legacy', title: '原有分析范围', delivery_kind: 'sci_draft', status: 'completed', source: '旧需求' }
  const refs = [{ file_id: 'file-1', purpose: 'sample_sheet', availability: 'provided', note: '已经关联' }] satisfies MaterialRef[]
  const previous = { ...emptyRequirement(), contact: { alias: { state: 'known', value: '旧称呼' } },
    services: ['sci_draft'], notes: '原说明', scope_items: [legacyScope] }
  server(version(previous, 'confirm', refs))
  const onSubmitted = vi.fn()
  const first = await open(onSubmitted)
  expect(screen.queryByRole('textbox', { name: '补充说明' })).toBeNull()
  fireEvent.click(checkbox(singleCell))
  fireEvent.click(checkbox('拟时分析'))
  fireEvent.click(checkbox('UMAP 图'))
  fireEvent.click(checkbox('Word 报告'))
  click('保存草稿')
  await screen.findByText('草稿已保存。')
  expect(writes()).toEqual([{ key: expect.any(String), body: {
    expected_revision: 2, operation: 'save', material_refs: [expect.objectContaining(refs[0])],
    content: { ...previous, services: ['sci_draft', 'analysis'], scope_items: expect.arrayContaining([
      legacyScope,
      expect.objectContaining({ id: 'customer.type.single_cell', title: singleCell, delivery_kind: 'analysis' }),
      expect.objectContaining({ id: 'customer.analysis.single_cell.pseudotime', title: expect.stringContaining('拟时分析') }),
      expect.objectContaining({ id: 'customer.figure.single_cell.umap', title: expect.stringContaining('UMAP 图') }),
      expect.objectContaining({ id: 'customer.delivery.word', title: 'Word 报告' }),
    ]) },
  } }])
  expect(onSubmitted).not.toHaveBeenCalled()
  first.unmount()

  await open(onSubmitted)
  expect(checkbox(singleCell).checked).toBe(true)
  expect(checkbox('拟时分析').checked).toBe(true)
  expect(checkbox('UMAP 图').checked).toBe(true)
  expect(checkbox('Word 报告').checked).toBe(true)
  fireEvent.click(checkbox(singleCell))
  click('提交需求')
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledOnce())
  expect(writes()[1].body).toMatchObject({ expected_revision: 3, operation: 'confirm', content: {
    notes: '原说明',
    scope_items: [legacyScope, expect.objectContaining({ id: 'customer.delivery.word' })],
  } })
})

it('allows an empty draft and requires an analysis type for a new submission', async () => {
  server(version({ ...emptyRequirement(), services: [] }))
  const onSubmitted = vi.fn()
  await open(onSubmitted)
  click('保存草稿')
  await screen.findByText('草稿已保存。')
  expect(writes()[0].body).toMatchObject({ operation: 'save', content: { notes: '', services: [], scope_items: [] } })

  fireEvent.click(checkbox('交付包'))
  click('提交需求')
  expect(screen.getByRole('alert').textContent).toContain('请选择至少一种分析类型。')
  expect(writes()).toHaveLength(1)
  expect(onSubmitted).not.toHaveBeenCalled()

  fireEvent.click(checkbox('交付包'))
  fireEvent.click(checkbox(bulk))
  click('提交需求')
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledOnce())
  expect(writes()[1].body).toMatchObject({ operation: 'confirm', content: {
    notes: '', services: ['analysis'], scope_items: [expect.objectContaining({ id: 'customer.type.bulk' })],
  } })
})

it('restores an unfinished request and retries its original confirmation after reopening', async () => {
  const { root, commit } = server()
  vi.mocked(apiFetch).mockImplementation(async (url, init) => {
    if (url === `${base}/research-intake`) return Response.json(root)
    if (writes().length === 1) throw new TypeError('response lost')
    return commit(JSON.parse(String(init?.body)))
  })
  const onSubmitted = vi.fn()
  const first = await open(onSubmitted)
  fireEvent.click(checkbox(bulk))
  click('提交需求')
  await screen.findByRole('button', { name: '按原请求重试' })
  expect(onSubmitted).not.toHaveBeenCalled()
  first.unmount()

  await open(onSubmitted)
  expect(checkbox(bulk).checked).toBe(true)
  expect(checkbox(bulk).matches(':disabled')).toBe(true)
  click('按原请求重试')
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledOnce())
  expect(writes()).toHaveLength(2)
  expect(writes()[1]).toEqual(writes()[0])
})

it('opens progress after finding the submitted version by its original request key', async () => {
  const { root, commit } = server()
  vi.mocked(apiFetch).mockImplementation(async (url, init) => {
    if (url === `${base}/research-intake`) return Response.json(root)
    if (url === `${base}/requirements/requests/${writes()[0].key}`) return Response.json(root.current_requirement)
    if (url === `${base}/requirements` && init?.method === 'POST') {
      commit(JSON.parse(String(init.body)))
      throw new TypeError('response lost after write')
    }
    throw new Error(`Unexpected request ${url}`)
  })
  const onSubmitted = vi.fn()
  await open(onSubmitted)
  fireEvent.click(checkbox(bulk))
  click('提交需求')
  await screen.findByRole('button', { name: '核对保存结果' })
  expect(onSubmitted).not.toHaveBeenCalled()
  click('核对保存结果')
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledOnce())
  expect(writes()).toHaveLength(1)
})

it('retains local edits on revision conflict and uses the latest unrelated fields on the next write', async () => {
  const singleCellScope = { id: 'customer.type.single_cell', title: singleCell, delivery_kind: 'analysis' }
  const bulkScope = { id: 'customer.type.bulk', title: bulk, delivery_kind: 'analysis' }
  const { root, commit } = server(version({ ...emptyRequirement(), scope_items: [singleCellScope] }))
  const baseline = { selected: [singleCellScope.id], notes: '' }
  sessionStorage.setItem(`paperassist.research-draft.v1:customer:${projectId}:customer-requirements`, JSON.stringify({
    draft: { revision: root.revision, baseline, input: { ...baseline, notes: '我的补充说明' } },
    pending: null,
  }))
  const addedScope = { id: 'server-only', title: '服务器新增范围', delivery_kind: 'analysis' }
  const addedRef = { file_id: 'new-file', purpose: 'other', availability: 'provided' } satisfies MaterialRef
  vi.mocked(apiFetch).mockImplementation(async (url, init) => {
    if (url === `${base}/research-intake`) return Response.json(root)
    if (writes().length !== 1) return commit(JSON.parse(String(init?.body)))
    root.revision = 3
    root.current_requirement = version({ ...emptyRequirement(), services: ['sci_draft'], scope_items: [addedScope, bulkScope] }, 'save', [addedRef], 2)
    return Response.json({ detail: { code: 'research_revision_conflict' } }, { status: 409 })
  })
  await open()
  expect(checkbox(singleCell).checked).toBe(true)
  fireEvent.click(checkbox('拟时分析'))
  click('保存草稿')
  await screen.findByRole('button', { name: '读取服务器版本并保留草稿' })
  expect(writes()[0].body.content.notes).toBe('我的补充说明')
  click('读取服务器版本并保留草稿')
  await screen.findByRole('button', { name: '合并本地修改' })
  click('合并本地修改')
  expect(checkbox(singleCell).checked).toBe(true)
  expect(checkbox(bulk).checked).toBe(true)
  expect(checkbox('拟时分析').checked).toBe(true)
  click('保存草稿')
  await screen.findByText('草稿已保存。')
  expect(writes()[1].key).not.toBe(writes()[0].key)
  expect(writes()[1].body).toMatchObject({ expected_revision: 3, material_refs: [addedRef], content: {
    services: ['sci_draft', 'analysis'], notes: '我的补充说明', scope_items: expect.arrayContaining([addedScope, bulkScope,
      expect.objectContaining({ id: 'customer.type.single_cell' }), expect.objectContaining({ id: 'customer.analysis.single_cell.pseudotime' })]),
  } })
})

it('warns before leaving a dirty project and retains its draft across steps', async () => {
  server()
  let guard: LeaveGuard | undefined
  const register: RegisterLeaveGuard = (next) => { guard = next; return () => { guard = undefined } }
  const ask = vi.spyOn(window, 'confirm').mockReturnValue(false)
  const first = await open(vi.fn(), register)
  expect(guard?.()).toBe(true)
  fireEvent.click(checkbox(singleCell))
  expect(guard?.()).toBe(false)
  expect(ask).toHaveBeenCalledOnce()
  expect(guard?.(true)).toBe(true)
  first.unmount()

  await open(vi.fn(), register)
  expect(checkbox(singleCell).checked).toBe(true)
  expect(writes()).toHaveLength(0)
})
