// B04 task 7: the thesis workbench takes over B03's trip to add a missing source and the step from adopting to Word.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { exportFixture, manuscriptFixture, snapshotFixture } from '../manuscripts/manuscriptFixtures'
import type { Manuscript } from '../manuscripts/manuscriptTypes'
import { rawSnapshot } from '../manuscripts/writingLiveFixtures'
import { taskFixture } from '../tasks/taskFixtures'
import CustomerWorkspace from './CustomerWorkspace'

type Need = (kind: 'literature' | 'materials', target: { writingRequest: string; paragraph: string }, location: { section: string; paragraph: number }) => void
const server = vi.hoisted(() => ({ adopted: false, sealed: true, section: '第三章 实验结果' }))
vi.mock('../manuscripts/WritingLive', () => ({
  default: ({ onNeedSource, onPublished, initialWritingRequest, initialParagraph }: {
    onNeedSource?: Need; onPublished: (value: Manuscript) => void; initialWritingRequest?: string; initialParagraph?: string
  }) => <div>
    <p>{`received:${initialWritingRequest ?? ''}|${initialParagraph ?? ''}`}</p>
    <button type="button" onClick={() => onNeedSource?.('literature', { writingRequest: 'w1', paragraph: 'chapter-result:2' }, { section: server.section, paragraph: 2 })}>去添加文献（完成后回到本段）</button>
    <button type="button" onClick={() => onNeedSource?.('materials', { writingRequest: 'w1', paragraph: 'chapter-result:2' }, { section: server.section, paragraph: 2 })}>去补充材料（完成后回到本段）</button>
    <button type="button" onClick={() => { server.adopted = true; onPublished(adoptedManuscript() as unknown as Manuscript) }}>采用这份稿件</button>
  </div>,
}))
vi.mock('../literature/ProjectLiterature', () => ({
  default: ({ onReferenceReady }: { onReferenceReady?: (id: string) => void }) => <div>
    <p>{onReferenceReady ? 'waiting-for-reference' : 'no-return'}</p>
    <button type="button" onClick={() => onReferenceReady?.('ref1')}>入选并核对书目</button>
  </div>,
}))
vi.mock('./CustomerMaterials', () => ({
  default: ({ onUploaded }: { onUploaded?: () => void }) => <div>
    <p>{onUploaded ? 'waiting-for-upload' : 'no-return'}</p>
    <button type="button" onClick={() => onUploaded?.()}>上传完成</button>
  </div>,
}))

const project = {
  id: 'customer-thesis-1', name: '毕业论文样例', research_topic: '比较病例与对照',
  project_type: 'thesis', file_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
}
const base = '/api/v1/projects/' + project.id
const profile = { revision: 2, school: '测试学校', department: '', major: '', degree_type: '硕士', education_level: '研究生', applicable_version: '2026', bound_confirmation_id: 'confirm1' }
const chapters = [{ id: 'chapter-result', title: '第三章 实验结果', level: 1, purpose: 'results', output_language: 'zh-CN', result_group_ids: [] }]
const thesisContext = { schema_version: 1, profile, template_version_id: 'template1', confirmation_id: 'confirm1', confirmation_sha256: 'a'.repeat(64),
  confirmation: { id: 'confirm1', chapters: chapters.map(({ id, title, level }) => ({ id, title, level })) }, source_files: [], chapters }
const snapshot = { ...snapshotFixture, project_id: project.id, output_language: 'zh-CN', thesis_context: thesisContext,
  sections: chapters.map(c => ({ ...c, paragraphs: [{ id: 'chapter-result:1', text: '学校结果正文', origin: 'user_provided', source_ids: [], citations: [] }] })),
  school_content_report: { rules_version: 'school_v1', issues: [], can_publish: true, scientifically_verified: false } }
const options = { manual_fields: { author: '合成作者', student_id: '', department: '', major: '', class_name: '', supervisor: '', submission_date: '' },
  manual_chapters: [], english_title: 'Reviewed title', keywords: [], include_toc: true, toc_depth: 3 }
const first = { ...manuscriptFixture.versions[0], snapshot, exports: [], created_at: '2026-11-19T07:40:00Z' }
function adoptedVersion() {
  return { ...first, id: 'v2', revision: 2, parent_version_id: 'v1', task_id: 'draft-2', created_at: '2026-11-19T09:10:00Z',
    snapshot: { ...snapshot, writing_provenance: { ...rawSnapshot.writing_provenance!, base_version_id: 'v1',
      ...(server.sealed ? { language_review_id: 'language-review-1', school_export_options: options } : {}) } } }
}
function adoptedManuscript() {
  return { ...manuscriptFixture, project_id: project.id, title: '毕业论文初稿', current_revision: 2,
    updated_at: '2026-11-19T09:10:00Z', versions: [adoptedVersion(), first] }
}
function currentManuscripts() {
  return server.adopted ? [adoptedManuscript()]
    : [{ ...manuscriptFixture, project_id: project.id, title: '毕业论文初稿', current_revision: 1, updated_at: '2026-11-19T07:40:00Z', versions: [first] }]
}

type Export = typeof exportFixture
const allowedPlan = { schema_version: 1, rules_version: 'school-export-v1', confirmation_id: 'confirm1', confirmation_sha256: 'a'.repeat(64), analysis_sha256: 'b'.repeat(64),
  snapshot_sha256: 'c'.repeat(64), options: {}, styles: {}, sections: [], chapters: [], requirements: [], toc: { enabled: true, depth: 3 }, label_map: { figures: {}, tables: {} },
  report: { rules_version: 'school-export-v1', issues: [], can_export: true, scientifically_verified: false } }
const previewPosts = (fetch: ReturnType<typeof serve>) => fetch.mock.calls.filter(([url]) => url.endsWith('/exports/preview'))
function serve(store: Export[] = []) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === base) return Response.json(project)
    if (url === base + '/manuscripts') return Response.json({ items: currentManuscripts() })
    const failed = store.find(item => item.status === 'failed' && url === `/api/v1/tasks/${item.task_id}/workspace`)
    if (failed) {
      const task = { ...taskFixture, id: failed.task_id, project_id: project.id, task_type: 'manuscript_docx',
        status: 'failed', display_status: 'failed', phase: 'export', reason_code: null, error_code: 'task_failed',
        input_version: { kind: 'manuscript', manuscript_version_id: failed.version_id, output_language: 'zh-CN', workflow_version: 'manuscript_fact_draft_v1' } }
      return Response.json({ task, source: { file_id: null, filename: '毕业论文初稿', analysis_run_id: null, is_current: true },
        wait: null, allowed_actions: ['retry'], artifacts: { figure: null, explanation: null, report: null } })
    }
    // B04 task 11: the automatic thesis Word is preceded by the school layout check.
    if (url === base + '/manuscripts/m1/versions/2/exports/preview') return Response.json({ schema_version: 1, school: allowedPlan })
    if (url === base + '/manuscripts/m1/versions/2/exports') {
      if (init?.method === 'POST') {
        const key = new Headers(init.headers).get('Idempotency-Key')
        const created = { ...exportFixture, id: 'export-' + key, version_id: 'v2', created_at: '2026-11-19T09:11:00Z',
          download_url: `${base}/manuscripts/m1/exports/export-${key}/download` }
        if (!store.some(item => item.id === created.id)) store.unshift(created)
        return Response.json(created, { status: 201 })
      }
      return Response.json({ items: store })
    }
    if (url === base + '/manuscripts/m1/versions/1/exports') return Response.json({ items: [] })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const exportPosts = (fetch: ReturnType<typeof serve>) => fetch.mock.calls.filter(([url, init]) => url.endsWith('/exports') && init?.method === 'POST')
const writing = `customer-project=${project.id}&step=manuscripts&manuscript=m1&revision=1&view=writing`
function expectedTrip(step: string, view: string, section = '第三章 实验结果') {
  const origin = new URLSearchParams(writing)
  origin.set('writingRequest', 'w1')
  origin.set('paragraph', 'chapter-result:2')
  return '#' + new URLSearchParams({ 'customer-project': project.id, step, view, return: origin.toString(),
    returnLabel: 'paragraph', returnSection: section, returnParagraph: '2' }).toString()
}

beforeEach(() => {
  setApiSession('csrf', 'customer-test')
  sessionStorage.clear()
  Object.assign(server, { adopted: false, sealed: true, section: '第三章 实验结果' })
})
afterEach(() => {
  cleanup()
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it('goes to the thesis literature list with a return token, returns once the reference is ready and drops it on a step click', async () => {
  serve()
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  window.history.replaceState(null, '', '#' + writing)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去添加文献（完成后回到本段）' }))
  await waitFor(() => expect(window.location.hash).toBe(expectedTrip('citations', 'list')))
  expect(confirm).not.toHaveBeenCalled()
  expect(await screen.findByText('正在为“第三章 实验结果第 2 段”补充依据')).toBeTruthy()
  expect(screen.getByRole('link', { name: '返回 第三章 实验结果第 2 段' })).toBeTruthy()
  expect(screen.getByText('waiting-for-reference')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '入选并核对书目' }))
  expect(await screen.findByText('received:w1|chapter-result:2')).toBeTruthy()
  expect(window.location.hash).toBe('#' + writing + '&writingRequest=w1&paragraph=chapter-result%3A2')

  fireEvent.click(screen.getByRole('button', { name: '去添加文献（完成后回到本段）' }))
  await screen.findByRole('link', { name: '返回 第三章 实验结果第 2 段' })
  fireEvent.click(screen.getByRole('button', { name: '写作资料与引用' }))
  await waitFor(() => expect(window.location.hash).toBe(`#customer-project=${project.id}&step=materials`))
  expect(screen.queryByRole('link', { name: '返回 第三章 实验结果第 2 段' })).toBeNull()
  expect(screen.getByText('no-return')).toBeTruthy()
})

it('goes to the thesis project files for a missing material and comes back after an upload', async () => {
  serve()
  window.history.replaceState(null, '', '#' + writing)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去补充材料（完成后回到本段）' }))
  await waitFor(() => expect(window.location.hash).toBe(expectedTrip('materials', 'files')))
  fireEvent.click(await screen.findByRole('button', { name: '上传完成' }))
  expect(await screen.findByText('received:w1|chapter-result:2')).toBeTruthy()
})

it('names the place “正文” when the chapter title is missing', async () => {
  serve()
  server.section = '正文'
  window.history.replaceState(null, '', '#' + writing)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去添加文献（完成后回到本段）' }))
  await waitFor(() => expect(window.location.hash).toBe(expectedTrip('citations', 'list', '正文')))
  expect(await screen.findByText('正在为“正文第 2 段”补充依据')).toBeTruthy()
})

it('goes from adopting to downloading the thesis Word in two clicks and generates it once without a body', async () => {
  const store: Export[] = []
  let fetch = serve(store)
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  const push = vi.spyOn(window.history, 'pushState')
  window.history.replaceState(null, '', '#' + writing)
  const view = render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '采用这份稿件' }))
  await screen.findByRole('heading', { name: '固定版本与 Word', level: 1 })
  expect(String(push.mock.calls.at(-1)?.[2])).toContain(`#customer-project=${project.id}&step=word&manuscript=m1&revision=2&view=exports&adopted=1`)
  expect(confirm).not.toHaveBeenCalled()
  expect((await screen.findByText(/^已采用这份稿件（毕业论文初稿，/)).textContent).toMatch(/第 2 版/)
  const download = await screen.findByRole('link', { name: '下载这份 Word' })
  fireEvent.click(download)
  expect(exportPosts(fetch)).toHaveLength(1)
  const [, init] = exportPosts(fetch)[0]
  expect(new Headers(init?.headers).get('Idempotency-Key')).toBe('auto-word-v2')
  expect(init?.body).toBe('{}')
  expect(previewPosts(fetch)).toHaveLength(1)
  expect(fetch.mock.calls.indexOf(previewPosts(fetch)[0])).toBeLessThan(fetch.mock.calls.indexOf(exportPosts(fetch)[0]))
  await waitFor(() => expect(window.location.hash).not.toContain('adopted'))

  view.unmount()
  fetch = serve(store)
  render(<CustomerWorkspace />)
  await screen.findByRole('link', { name: '下载这份 Word' })
  expect(exportPosts(fetch)).toHaveLength(0)
})

it('does not generate Word by itself for an adopted version without sealed school options', async () => {
  server.adopted = true
  server.sealed = false
  const fetch = serve()
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=word&manuscript=m1&revision=2&view=exports&adopted=1`)
  render(<CustomerWorkspace />)
  expect(await screen.findByText('当前版本尚未生成 Word。')).toBeTruthy()
  expect(screen.getByRole('button', { name: '生成 Word' })).toBeTruthy()
  expect(exportPosts(fetch)).toHaveLength(0)
})

it('opens the failed Word task and returns to the same manuscript version without resubmitting', async () => {
  server.adopted = true
  const failed = {...exportFixture,version_id:'v2',status:'failed',download_url:null,filename:null,size_bytes:null,sha256:null,error_code:'task_failed'}
  const fetch=serve([failed as unknown as Export])
  const wordPath=`#customer-project=${project.id}&step=word&manuscript=m1&revision=2&view=exports`
  window.history.replaceState(null,'',wordPath)
  render(<CustomerWorkspace/>)
  await screen.findByText('这一版 Word 没有生成成功。请先查看任务结果。')
  fireEvent.click(screen.getByRole('button',{name:'查看任务结果'}))
  expect(await screen.findByRole('heading',{name:'任务详情'})).toBeTruthy()
  expect(new URLSearchParams(window.location.hash.slice(1)).get('task')).toBe(failed.task_id)
  fireEvent.click(await screen.findByRole('button',{name:'待处理'}))
  expect(await screen.findByRole('button',{name:'重试原任务'})).toBeTruthy()
  fireEvent.click(screen.getByRole('link',{name:'返回 稿件 Word'}))
  await waitFor(()=>expect(window.location.hash).toBe(wordPath))
  expect(exportPosts(fetch)).toHaveLength(0)
})

it('does not generate Word by itself for an earlier version', async () => {
  server.adopted = true
  const fetch = serve()
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=word&manuscript=m1&revision=1&view=exports`)
  render(<CustomerWorkspace />)
  expect(await screen.findByText('当前版本尚未生成 Word。')).toBeTruthy()
  expect(exportPosts(fetch)).toHaveLength(0)
})

it('carries the current thesis manuscript to its Word page from the chapter step', async () => {
  serve()
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=manuscripts&manuscript=m1&revision=1&view=body`)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '查看固定版本 Word' }))
  await screen.findByRole('heading', { name: '固定版本与 Word', level: 1 })
  expect(window.location.hash).toBe(`#customer-project=${project.id}&step=word&manuscript=m1&revision=1&view=exports`)
})

it('opens the current version of the latest thesis manuscript on a Word page without one', async () => {
  server.adopted = true
  serve([{ ...exportFixture, version_id: 'v2', download_url: `${base}/manuscripts/m1/exports/export1/download` }])
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=word`)
  render(<CustomerWorkspace />)
  await screen.findByRole('link', { name: '下载这份 Word' })
  expect(window.location.hash).toBe(`#customer-project=${project.id}&step=word&manuscript=m1&revision=2&view=exports`)
})
