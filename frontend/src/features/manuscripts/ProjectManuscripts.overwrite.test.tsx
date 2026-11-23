// B03 task 4 (D2): customer paper projects keep one manuscript; saving the writing materials again
// appends a version to it instead of creating another manuscript.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { taskFixture, workspaceFixture } from '../tasks/taskFixtures'
import { setLocale } from '../../shared/i18n'
import type { ManuscriptView } from '../projects/manuscriptViews'
import ProjectManuscripts from './ProjectManuscripts'
import { candidatesFixture, exportFixture, inputFixture, manuscriptFixture, snapshotFixture } from './manuscriptFixtures'
import { rawSnapshot } from './writingLiveFixtures'
import { isAdoptedSnapshot, type Snapshot, type SourceSelection } from './manuscriptTypes'

const base = '/api/v1/projects/p1/manuscripts'
const token = '3f1a9c27b84e6d05c2f7a1b93e8d4c60a5b2f7e19c3d8a4b06e2f5c9a7d1b3e4'
const paperPlan = { kind: 'research' as const, title: 'Planned article', keywords: ['lineage'], sections: [], materials: [], token, omitted_count: 0 }
const candidates = { ...candidatesFixture, paper_plan: paperPlan }
type Version = Omit<typeof manuscriptFixture.versions[number], 'parent_version_id' | 'input'> & {
  parent_version_id: string | null
  input: Omit<typeof inputFixture, 'sources'> & { sources: SourceSelection[] }
}
type Stored = Omit<typeof manuscriptFixture, 'versions'> & { versions: Version[] }

function version(revision: number, extra: Partial<Version> = {}): Version {
  return { ...manuscriptFixture.versions[0], id: `v${revision}`, revision, parent_version_id: revision > 1 ? `v${revision - 1}` : null,
    task_id: `draft-${revision}`, created_at: `2026-11-19T0${revision}:15:00Z`, exports: [],
    input: { ...inputFixture, title: 'Planned article', methods: { ...inputFixture.methods, research_question: `Question ${revision}` } }, ...extra }
}
function manuscript(id: string, revisions: Version[], updated = '2026-11-19T01:15:00Z'): Stored {
  return { ...manuscriptFixture, id, title: id === 'm1' ? 'Planned article' : 'Older article', current_revision: revisions.at(-1)!.revision,
    updated_at: updated, versions: revisions }
}

type Options = { items?: Stored[]; writingRequests?: unknown[] | 'fail'; conflict?: string }
function serve({ items = [], writingRequests = [], conflict }: Options = {}) {
  const state = { items: structuredClone(items) }
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === `${base}/candidates`) return Response.json(candidates)
    if (url === base && !init?.method) return Response.json({ items: state.items })
    if (url.endsWith('/writing-requests') && !init?.method) {
      if (writingRequests === 'fail') return Response.json({ detail: { code: 'internal_error' } }, { status: 500 })
      return Response.json({ items: writingRequests })
    }
    if (url === `${base}/preview`) return Response.json(snapshotFixture)
    if (init?.method === 'POST' && conflict) return Response.json({ detail: { code: conflict, message: 'conflict' } }, { status: 409 })
    if (url === base && init?.method === 'POST') {
      if (state.items.length) return Response.json({ detail: { code: 'manuscript_exists', message: '这个项目已经有稿件。请覆盖之前的写作材料。' } }, { status: 409 })
      const created = manuscript('m1', [version(1)]); state.items = [created]; return Response.json(created, { status: 201 })
    }
    const append = url.match(/\/manuscripts\/([^/]+)\/versions$/)
    if (append && init?.method === 'POST') {
      const target = state.items.find(item => item.id === append[1])!
      if (JSON.parse(String(init.body)).expected_revision !== target.current_revision)
        return Response.json({ detail: { code: 'manuscript_revision_conflict' } }, { status: 409 })
      const next = version(target.current_revision + 1)
      const updated = { ...target, current_revision: next.revision, updated_at: next.created_at, versions: [...target.versions, next] }
      state.items = [updated, ...state.items.filter(item => item.id !== updated.id)]
      return Response.json(updated, { status: 201 })
    }
    return Response.json({ items: [] })
  })
  vi.stubGlobal('fetch', fetcher)
  return { fetcher, state }
}
const posts = (fetcher: ReturnType<typeof serve>['fetcher']) => fetcher.mock.calls.filter(([, init]) => init?.method === 'POST' && !String(init?.body).includes('"kind":"preview"'))
const saves = (fetcher: ReturnType<typeof serve>['fetcher']) => posts(fetcher).filter(([url]) => url === base || url.endsWith('/versions'))

function Harness({ select = vi.fn(), initial = 'materials' as ManuscriptView, revision }: { select?: (id: string, revision: number) => void; initial?: ManuscriptView; revision?: number }) {
  const [view, setView] = useState<ManuscriptView>(initial)
  const [selected, setSelected] = useState<{ id: string; revision: number } | null>(revision ? { id: 'm1', revision } : null)
  return <ProjectManuscripts projectId="p1" researchTopic="Topic" outputLanguage="en" active projectType="sci"
    customerSci={{ settings: null, wordOnly: false }} view={view} onViewChange={setView}
    initialManuscript={selected?.id} initialRevision={selected?.revision}
    onSelectVersion={(id, revision) => { setSelected({ id, revision }); select(id, revision) }} />
}
const openMaterials = () => fireEvent.click(within(screen.getByRole('navigation', { name: '稿件任务视图' })).getByRole('button', { name: '写作材料' }))
const ready = async () => { await screen.findByRole('region', { name: '已保存的写作要求' }); await waitFor(() => expect(screen.getByRole('button', { name: /覆盖之前的写作材料|确认并继续/ }).closest('fieldset')?.disabled).toBe(false)) }

beforeEach(() => {
  sessionStorage.clear()
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true } },
    close: { configurable: true, value(this: HTMLDialogElement) { this.open = false } },
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN'); sessionStorage.clear() })

it('creates the first manuscript with “确认并继续” and never mentions overwriting', async () => {
  const { fetcher } = serve()
  render(<Harness />)
  await ready()
  expect(document.body.textContent).not.toContain('覆盖')
  fireEvent.click(screen.getByRole('button', { name: '确认并继续' }))
  await waitFor(() => expect(saves(fetcher)).toHaveLength(1))
  expect(saves(fetcher)[0][0]).toBe(base)
  expect(JSON.parse(String(saves(fetcher)[0][1]?.body))).toMatchObject({ expected_revision: 0, paper_plan_token: token })
  expect(await screen.findByText('已保存为第 1 版。')).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('appends versions to the one manuscript, keeps the input and moves the address 2 → 3', async () => {
  const select = vi.fn()
  const { fetcher, state } = serve({ items: [manuscript('m1', [version(1)])] })
  render(<Harness select={select} />)
  await ready(); expect(screen.getByRole('button', { name: '覆盖之前的写作材料' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '确认并继续' })).toBeNull()
  // The current version's input fills the empty draft.
  fireEvent.click(screen.getByRole('button', { name: /补充方法/ }))
  expect(screen.getByLabelText('研究问题')).toHaveProperty('value', 'Question 1')
  expect(screen.getByText(/将覆盖：/).textContent).toMatch(/Planned article.*第 1 版 · /)
  fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: 'Edited question' } })
  fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  expect(await screen.findByText('已保存为第 2 版。')).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
  const first = saves(fetcher)[0]
  expect(first[0]).toBe(`${base}/m1/versions`)
  expect(JSON.parse(String(first[1]?.body))).toMatchObject({ expected_revision: 1, paper_plan_token: token, methods: { research_question: 'Edited question' } })
  expect(select).toHaveBeenLastCalledWith('m1', 2)
  openMaterials()
  fireEvent.click(screen.getByRole('button', { name: /补充方法/ }))
  expect(screen.getByLabelText('研究问题')).toHaveProperty('value', 'Edited question')
  fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  expect(await screen.findByText('已保存为第 3 版。')).toBeTruthy()
  expect(JSON.parse(String(saves(fetcher)[1][1]?.body))).toMatchObject({ expected_revision: 2 })
  expect(select).toHaveBeenLastCalledWith('m1', 3)
  expect(state.items).toHaveLength(1)
  expect(saves(fetcher).every(([url]) => url === `${base}/m1/versions`)).toBe(true)
})

it('asks before overwriting when this version already has a written body, and cancel sends nothing', async () => {
  const { fetcher } = serve({ items: [manuscript('m1', [version(1)])], writingRequests: [{ schema_version: 2, base_revision: 1 }] })
  render(<Harness />)
  await ready(); fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  const dialog = await screen.findByRole('dialog', { name: '覆盖之前的写作材料？' })
  expect(dialog.textContent).toContain('保存后，这份稿件会按新材料更新为第 2 版。第 1 版已生成的正文和核对结果不会带到新版本，需要重新生成正文并重新核对，重新生成会再次产生写作费用。')
  expect(dialog.textContent).toContain('第 1 版、已下载的 Word 和已开始的返修保持原样，可以在历史中查看。')
  fireEvent.click(within(dialog).getByRole('button', { name: '取消' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(saves(fetcher)).toHaveLength(0)
})

it('overwrites once after confirming, even when “覆盖并保存” is clicked twice, and offers to generate again', async () => {
  const views: string[] = []
  const { fetcher } = serve({ items: [manuscript('m1', [version(1)])], writingRequests: [{ schema_version: 2, base_revision: 1 }] })
  function Watch() { const [view, setView] = useState<ManuscriptView>('materials'); views.push(view)
    return <ProjectManuscripts projectId="p1" researchTopic="Topic" outputLanguage="en" active projectType="sci"
      customerSci={{ settings: null, wordOnly: false }} view={view} onViewChange={setView} onSelectVersion={() => {}} /> }
  render(<Watch />)
  await ready(); fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  const dialog = await screen.findByRole('dialog')
  const confirm = within(dialog).getByRole('button', { name: '覆盖并保存' })
  fireEvent.click(confirm); fireEvent.click(confirm)
  expect(await screen.findByText('已保存为第 2 版。下一步需要重新生成正文，会产生写作费用。')).toBeTruthy()
  expect(saves(fetcher)).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '生成正文初稿' }))
  expect(views.at(-1)).toBe('writing')
})

it('treats an adopted current version as written without reading writing requests', async () => {
  const written = version(2, { snapshot: { ...snapshotFixture, writing_provenance: { schema_version: 2, provider_provenance: 'synthetic_fixture', verification_status: 'scientific_and_language_reviewed', base_version_id: 'v1' } } as never })
  const { fetcher } = serve({ items: [manuscript('m1', [version(1), written])] })
  render(<Harness />)
  await ready(); fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  expect(await screen.findByRole('dialog')).toBeTruthy()
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/writing-requests'))).toBe(false)
})

it('asks before overwriting when writing requests cannot be read', async () => {
  serve({ items: [manuscript('m1', [version(1)])], writingRequests: 'fail' })
  render(<Harness />)
  await ready(); fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  expect(await screen.findByRole('dialog')).toBeTruthy()
})

it('shows the overwrite question in English', async () => {
  setLocale('en')
  serve({ items: [manuscript('m1', [version(1)])], writingRequests: [{ schema_version: 2, base_revision: 1 }] })
  render(<Harness />)
  await screen.findByRole('region', { name: 'Saved writing requirements' })
  const save = screen.getByRole('button', { name: 'Replace the previous writing materials' })
  await waitFor(() => expect(save.closest('fieldset')?.disabled).toBe(false))
  fireEvent.click(save)
  expect(await screen.findByRole('dialog', { name: 'Replace the previous writing materials?' })).toBeTruthy()
})

it.each([
  ['manuscript_exists', '这个项目已经有稿件。请覆盖之前的写作材料。'],
  ['manuscript_revision_conflict', '这份稿件已有更新。你输入的内容仍在，请核对后再保存。'],
])('keeps the input and explains a %s conflict', async (code, message) => {
  const { fetcher } = serve({ items: [manuscript('m1', [version(1)])], conflict: code })
  render(<Harness />)
  await ready()
  fireEvent.click(screen.getByRole('button', { name: /补充方法/ }))
  fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: 'Keep me' } })
  const reads = fetcher.mock.calls.filter(([url, init]) => url === base && !init?.method).length
  fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  expect((await screen.findByRole('alert')).textContent).toBe(message)
  expect(screen.getByLabelText('研究问题')).toHaveProperty('value', 'Keep me')
  await waitFor(() => expect(fetcher.mock.calls.filter(([url, init]) => url === base && !init?.method).length).toBeGreaterThan(reads))
})

it('lists the current and previous manuscripts read-only, with minute-level version labels', async () => {
  serve({ items: [manuscript('m1', [version(1), version(2)], '2026-11-19T02:15:00Z'), manuscript('m0', [version(1)], '2026-11-18T01:15:00Z')] })
  const select = vi.fn()
  render(<Harness initial="list" select={select} />)
  const list = await screen.findByRole('region', { name: '稿件列表' })
  const [current, older] = await within(list).findAllByRole('article')
  expect(current.textContent).toContain('当前稿件'); expect(current.textContent).toContain('Planned article')
  expect(current.textContent).toMatch(/第 2 版 · \S+/)
  expect(older.textContent).toContain('之前的稿件'); expect(older.textContent).toContain('Older article')
  fireEvent.click(within(older).getByRole('button', { name: '打开这份稿件' }))
  expect(select).toHaveBeenLastCalledWith('m0', 1)
  fireEvent.click(within(screen.getByRole('navigation', { name: '稿件任务视图' })).getByRole('button', { name: '版本' }))
  const history = screen.getByRole('region', { name: '稿件版本历史' })
  expect(history.textContent).toMatch(/第 1 版 · /)
  expect(within(history).queryAllByRole('button', { name: /另建|编辑新稿/ })).toHaveLength(0)
  expect(within(history).getAllByRole('button', { name: '查看这一版' }).length).toBeGreaterThan(0)
  expect(screen.queryAllByRole('button', { name: /另建|编辑新稿/ })).toHaveLength(0)
  expect(document.body.textContent).not.toMatch(/事实稿|受控/)
})

it.each([0, 1])('requires review of a draft from revision %i when a tab becomes visible again', async original => {
  const revisions = original ? [version(original)] : []
  const { fetcher, state } = serve({ items: original ? [manuscript('m1', revisions)] : [] })
  render(<Harness />)
  await ready()
  fireEvent.click(screen.getByRole('button', { name: /补充方法/ }))
  fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: 'Edited in the older tab' } })
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  try {
    fireEvent(document, new Event('visibilitychange'))
    const current = original + 1
    state.items = [manuscript('m1', [...revisions, version(current)])]
    visibility.mockReturnValue('visible')
    fireEvent(document, new Event('visibilitychange'))
    await waitFor(() => expect(screen.getByText(/将覆盖：/).textContent).toContain(`第 ${current} 版`))
    const save = screen.getByRole('button', { name: '覆盖之前的写作材料' })
    fireEvent.click(save)
    const notice = original ? '这份稿件已有更新。你输入的内容仍在，请核对后再保存。' : '这个项目已经有稿件。请覆盖之前的写作材料。'
    expect((await screen.findByRole('alert')).textContent).toBe(notice)
    expect(state.items[0].current_revision).toBe(current)
    expect(saves(fetcher)).toHaveLength(0)
    expect(screen.getByLabelText('研究问题')).toHaveProperty('value','Edited in the older tab')
    await waitFor(() => expect(save.closest('fieldset')?.disabled).toBe(false))
    fireEvent.click(save)
    expect(await screen.findByText(`已保存为第 ${current + 1} 版。`)).toBeTruthy()
    expect(JSON.parse(String(saves(fetcher).at(-1)![1]?.body)).expected_revision).toBe(current)
  } finally { visibility.mockRestore() }
})

it('uses customer wording on the materials page', async () => {
  serve({ items: [manuscript('m1', [version(1)])] })
  render(<Harness />)
  await ready()
  expect(screen.getByRole('form', { name: '写作材料' })).toBeTruthy()
  expect(screen.getByText('写作材料由系统整理；生成正文前会请你确认费用。科研内容、来源、数值、引用和待办仍需你核实。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '预览写作材料' }))
  expect(await screen.findByRole('region', { name: '写作材料预览' })).toBeTruthy()
  expect(document.body.textContent).not.toMatch(/事实稿|受控/)
  await act(async () => {})
})

it('recognizes adopted snapshots the same way as the backend', () => {
  const plain = snapshotFixture as unknown as Snapshot
  expect(isAdoptedSnapshot(plain, null)).toBe(false)
  const written = { ...plain, writing_provenance: { schema_version: 2 as const, provider_provenance: 'synthetic_fixture', verification_status: 'x', base_version_id: 'v1' } }
  expect(isAdoptedSnapshot(written, 'v1')).toBe(true)
  expect(isAdoptedSnapshot(written, 'v0')).toBe(false)
  expect(isAdoptedSnapshot(written, null)).toBe(false)
  for (const key of ['review_provenance', 'review_revision_provenance', 'user_return_provenance', 'journal_adaptation_provenance', 'school_change_provenance'])
    expect(isAdoptedSnapshot({ ...plain, [key]: {} } as Snapshot, null)).toBe(true)
})


it('keeps the customer material draft while the current version prepares and opens writing automatically', async () => {
  const { fetcher, state } = serve({ items: [manuscript('m1', [version(1, { status: 'pending' }), version(2, { status: 'pending' })])] })
  vi.useFakeTimers()
  try {
    await act(async () => { render(<Harness revision={2} />) })
    fireEvent.click(screen.getByRole('button', { name: /补充方法/ }))
    fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: 'Keep this unsaved draft' } })
    fireEvent.click(screen.getByRole('button', { name: '写作' }))
    expect(screen.getByText('正在整理第 2 版写作材料。整理完成后，这里会自动显示写作选项。')).toBeTruthy()
    expect(screen.queryByRole('region', { name: '写作工作区' })).toBeNull()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '刷新准备状态' })) })
    state.items[0].versions[1].status = 'published'
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(screen.getByRole('region', { name: '写作工作区' })).toBeTruthy()
    const reads = () => fetcher.mock.calls.filter(([url]) => url === base).length
    const completedReads = reads()
    await act(async () => { await vi.advanceTimersByTimeAsync(6500) })
    expect(reads()).toBe(completedReads)
    expect(posts(fetcher)).toHaveLength(0)
    openMaterials()
    expect(screen.getByLabelText('研究问题')).toHaveProperty('value', 'Keep this unsaved draft')
  } finally { vi.useRealTimers() }
})

it('lets a customer retry the failed writing material version once and shows its preparation status', async () => {
  setLocale('en')
  const { fetcher, state } = serve({ items: [manuscript('m1', [version(1), version(2, { status: 'failed' })])] })
  const ordinaryFetch = fetcher.getMockImplementation()!
  const task = { ...taskFixture, id: 'draft-2', task_type: 'manuscript_draft', phase: 'write', status: 'failed', display_status: 'failed',
    input_version: { kind: 'manuscript', manuscript_version_id: 'v2', output_language: 'en', workflow_version: 'manuscript_fact_draft_v1' } }
  const taskUrl = '/api/v1/tasks/draft-2'
  fetcher.mockImplementation(async (url, init) => {
    if (url === taskUrl + '/workspace') return Response.json({ ...workspaceFixture, task, source: { file_id: null, filename: 'Materials', analysis_run_id: null, is_current: true }, wait: null, allowed_actions: ['retry'] })
    if (url === taskUrl + '/resume') {
      state.items[0].versions[1].status = 'pending'
      return Response.json({ ...task, status: 'queued', display_status: 'queued', revision: task.revision + 1 })
    }
    return ordinaryFetch(url, init)
  })
  render(<Harness initial="writing" revision={2} />)
  await screen.findByText('The writing materials for version 2 could not be prepared.')
  const retry = screen.getByRole('button', { name: 'Prepare this version again' })
  fireEvent.click(retry)
  fireEvent.click(retry)
  await screen.findByText('Preparing the writing materials for version 2. Writing options will appear here when they are ready.')
  expect(posts(fetcher).map(([url]) => url)).toEqual([taskUrl + '/resume'])
  expect(JSON.parse(String(posts(fetcher)[0][1]?.body))).toMatchObject({ operation: 'retry', input_version: task.input_version })
})


it('pauses preparation polling away from writing and leaves a previous version read-only', async () => {
  const { fetcher, state } = serve({ items: [manuscript('m1', [version(1, { status: 'pending' }), version(2, { status: 'pending' })])] })
  const page = (active: boolean, revision: number) => <ProjectManuscripts projectId="p1" researchTopic="Topic" outputLanguage="en"
    active={active} customerSci={{ settings: null, wordOnly: false }} initialManuscript="m1" initialRevision={revision} view="writing" />
  const reads = () => fetcher.mock.calls.filter(([url]) => url === base).length
  vi.useFakeTimers()
  try {
    const rendered = render(page(true, 2))
    await act(async () => {})
    expect(screen.getByRole('button', { name: '刷新准备状态' })).toBeTruthy()
    rendered.rerender(page(false, 2))
    const beforeLeaving = reads()
    await act(async () => { await vi.advanceTimersByTimeAsync(6500) })
    expect(reads()).toBe(beforeLeaving)
    state.items[0].versions[1].status = 'published'
    await act(async () => { rendered.rerender(page(true, 1)) })
    expect(screen.getByText('这是之前的版本，只能查看。')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '刷新准备状态' })).toBeNull()
    expect(screen.queryByRole('button', { name: '重新整理这一版' })).toBeNull()
    const historicalReads = reads()
    await act(async () => { await vi.advanceTimersByTimeAsync(6500) })
    expect(reads()).toBe(historicalReads)
    expect(posts(fetcher)).toHaveLength(0)
  } finally { vi.useRealTimers() }
})


function adoptedWordVersion(status: string) {
  const snapshot = { ...snapshotFixture, sections: rawSnapshot.sections,
    writing_provenance: { ...rawSnapshot.writing_provenance, base_version_id: 'v2', language_review_id: 'language1' } }
  return version(3, { snapshot, status })
}

function wordPage(revision: number, onOpenTask = vi.fn()) {
  return <ProjectManuscripts projectId="p1" researchTopic="Topic" outputLanguage="en" active
    customerSci={{ settings: null, wordOnly: true }} initialManuscript="m1" initialRevision={revision}
    view="exports" adoptedNotice={revision === 3} onOpenTask={onOpenTask} />
}

it('explains manuscript publication on the adopted Word page, then starts one export and stops polling that manuscript', async () => {
  const { fetcher, state } = serve({ items: [manuscript('m1', [version(1, { status: 'pending' }), version(2), adoptedWordVersion('pending')])] })
  const ordinaryFetch = fetcher.getMockImplementation()!
  const url = base + '/m1/versions/3/exports'
  const queued = { ...exportFixture, version_id: 'v3', status: 'queued', filename: null, download_url: null, sha256: null, size_bytes: null }
  let submitted = false
  fetcher.mockImplementation(async (path, init) => {
    if (path !== url) return ordinaryFetch(path, init)
    if (init?.method === 'POST') { submitted = true; return Response.json(queued, { status: 201 }) }
    return Response.json({ items: submitted ? [queued] : [] })
  })
  vi.useFakeTimers()
  try {
    render(wordPage(3))
    await act(async () => {})
    expect(screen.getByText(/已采用这份稿件/)).toBeTruthy()
    const word = within(screen.getByRole('region', { name: 'Word' }))
    expect(word.getByRole('status').textContent).toBe('正在发布第 3 版稿件。发布完成后会自动准备 Word。')
    expect(word.queryByText('当前版本尚未生成 Word。')).toBeNull()
    expect(word.getByRole('button', { name: '生成 Word' })).toHaveProperty('disabled', true)
    expect(posts(fetcher)).toHaveLength(0)
    act(() => setLocale('en'))
    expect(word.getByRole('status').textContent).toBe('Publishing manuscript version 3. Word will be prepared automatically once it is published.')
    state.items[0].versions[2].status = 'published'
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(word.getByText('Preparing Word for this version…')).toBeTruthy()
    expect(word.queryByText('No Word document has been generated for this version yet.')).toBeNull()
    const manuscriptReads = () => fetcher.mock.calls.filter(([path]) => path === base).length
    const readsAtPublication = manuscriptReads()
    await act(async () => { await vi.advanceTimersByTimeAsync(6500) })
    expect(manuscriptReads()).toBe(readsAtPublication)
    expect(posts(fetcher).map(([path]) => path)).toEqual([url])
  } finally { vi.useRealTimers() }
})

it('opens the manuscript task when publication fails on the adopted Word page', async () => {
  const { fetcher } = serve({ items: [manuscript('m1', [version(2), adoptedWordVersion('failed')])] })
  const openTask = vi.fn()
  render(wordPage(3, openTask))
  const word = within(await screen.findByRole('region', { name: 'Word' }))
  expect((await word.findByRole('alert')).textContent).toBe('第 3 版稿件发布失败，无法生成 Word。')
  expect(word.queryByText('当前版本尚未生成 Word。')).toBeNull()
  act(() => setLocale('en'))
  expect(word.getByRole('alert').textContent).toBe('Manuscript version 3 could not be published, so Word could not be generated.')
  fireEvent.click(word.getByRole('button', { name: 'Check the task result' }))
  expect(openTask).toHaveBeenCalledExactlyOnceWith('draft-3')
  expect(posts(fetcher)).toHaveLength(0)
})

it.each(['previous adopted', 'ordinary current'])('keeps the ordinary empty Word state for a %s version', async kind => {
  const previous = { ...adoptedWordVersion('pending'), id: 'previous' }
  const { fetcher } = serve({ items: [manuscript('m1', [previous, version(4, { status: 'pending' })])] })
  render(wordPage(kind === 'previous adopted' ? 3 : 4))
  const word = within(await screen.findByRole('region', { name: 'Word' }))
  expect(await word.findByText('当前版本尚未生成 Word。')).toBeTruthy()
  expect(word.queryByRole('status')).toBeNull()
  expect(posts(fetcher)).toHaveLength(0)
})

it.each([['clean', false], ['edited', true]] as const)('reopens saved supplementary materials with an older %s tab draft', async (_name, edited) => {
  const { fetcher, state } = serve({ items: [manuscript('m1', [version(1)])] })
  const ordinaryFetch = fetcher.getMockImplementation()!
  const sources = [['word', 'Study report.docx'], ['image', 'figure-31-zh.png']].map(([id, label]) =>
    ({ kind: 'original' as const, id, file_id: id, label, version: null, allowed_roles: ['literature', 'methods'], download_url: null }))
  fetcher.mockImplementation((url, init) => url === base + '/candidates'
    ? Promise.resolve(Response.json({ ...candidates, items: sources })) : ordinaryFetch(url, init))
  const first = render(<Harness />)
  await ready()
  if (edited) {
    fireEvent.click(screen.getByRole('button', { name: /补充方法/ }))
    fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: 'Draft from this tab' } })
  }
  first.unmount()
  const saved = version(2)
  state.items[0] = manuscript('m1', [version(1), { ...saved, input: { ...saved.input,
    sources: sources.map(({ kind, id, file_id }) => ({ kind, id, file_id, role: 'methods' })),
  } }])
  render(<Harness />)
  await waitFor(() => expect(screen.getByText(/将覆盖：/).textContent).toContain('第 2 版'))
  fireEvent.click(screen.getByRole('button', { name: /补充来源/ }))
  for (const item of sources) {
    const source = within(screen.getByRole('group', { name: item.label }))
    expect(source.getByRole('checkbox')).toHaveProperty('checked', !edited)
    expect(source.getByRole('combobox')).toHaveProperty('value', edited ? 'literature' : 'methods')
  }
  if (edited) {
    fireEvent.click(screen.getByRole('button', { name: /补充方法/ }))
    expect(screen.getByLabelText('研究问题')).toHaveProperty('value', 'Draft from this tab')
  }
})

it.each([['zh-CN', '文档解析'], ['en', 'Parsed document']] as const)(
  'shows parsed source labels only in the chosen interface language (%s)', async (locale, kindLabel) => {
    const { fetcher } = serve({ items: [manuscript('m1', [version(1)])] })
    const ordinaryFetch = fetcher.getMockImplementation()!
    const filename = '研究-Parsed document v1.docx'
    fetcher.mockImplementation((url, init) => url === base + '/candidates' ? Promise.resolve(Response.json({
      ...candidates, items: [
        { ...candidates.items[1], kind: 'original', id: 'file2', version: null, label: filename },
        { ...candidates.items[1], label: filename + ' — 文档解析 / Parsed document v1' },
        { ...candidates.items[1], kind: 'ocr_review_version', id: 'reviewed', label: filename + ' — 人工核对 / Human reviewed v1' },
      ],
    })) : ordinaryFetch(url, init))
    render(<Harness />)
    await ready()
    fireEvent.click(screen.getByRole('button', { name: /补充来源/ }))
    act(() => setLocale(locale))
    expect(screen.getByRole('checkbox', { name: filename })).toBeTruthy()
    const localized = filename + ' — ' + kindLabel + ' v1'
    const field = within(screen.getByRole('group', { name: localized }))
    expect(field.getByRole('checkbox', { name: localized })).toBeTruthy()
    expect(screen.queryByText(filename + ' — 文档解析 / Parsed document v1')).toBeNull()
    expect(screen.getByRole('checkbox', { name: filename + (locale === 'en' ? ' — Human reviewed v1' : ' — 人工核对 v1') })).toBeTruthy()
  },
)

function delayedList() {
  let resolve!: (value: Response) => void
  const history = new Promise<Response>(done => { resolve = done })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === base) return history
    if (url === base + '/candidates') return Response.json(candidates)
    return Response.json({ items: [] })
  }))
  render(<Harness initial="list" />)
  return resolve
}
const comesBefore = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

it('provides one supplementary material editor that stays usable before the manuscript list arrives', async () => {
  const finish = delayedList()
  expect(screen.queryByRole('button', { name: '写作材料' })).toBeNull()
  const primary = screen.getByRole('button', { name: '整理写作材料' })
  const loading = screen.getByText('正在读取稿件资料……')
  expect(primary.matches(':disabled')).toBe(false)
  expect(comesBefore(primary, loading)).toBe(true)
  fireEvent.click(primary)
  await act(async () => finish(Response.json({ items: [manuscriptFixture] })))
  expect(await screen.findByRole('button', { name: '覆盖之前的写作材料' })).toBeTruthy()
})
it('inserts incoming manuscript cards after the customer prepare button while the pointer is held on it', async () => {
  const finish = delayedList()
  const primary = screen.getByRole('button', { name: '整理写作材料' })
  fireEvent.pointerDown(primary)
  await act(async () => finish(Response.json({ items: [manuscriptFixture] })))
  const card = (await screen.findByRole('button', { name: '打开这份稿件' })).closest('article')!
  expect(comesBefore(primary, card)).toBe(true)
  expect(screen.getByRole('button', { name: '整理写作材料' })).toBe(primary)
  fireEvent.pointerUp(primary)
  fireEvent.click(primary)
  expect(await screen.findByRole('button', { name: '覆盖之前的写作材料' })).toBeTruthy()
})
