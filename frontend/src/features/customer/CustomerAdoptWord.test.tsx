// B03 task 6: adopting the reviewed manuscript opens the Word page of the new version and generates its Word once.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { exportFixture, manuscriptFixture, snapshotFixture } from '../manuscripts/manuscriptFixtures'
import type { Manuscript } from '../manuscripts/manuscriptTypes'
import CustomerWorkspace from './CustomerWorkspace'

const server = vi.hoisted(() => ({ adopted: false }))
vi.mock('../manuscripts/WritingLive', () => ({
  default: ({ onPublished }: { onPublished: (value: Manuscript) => void }) => <button type="button" onClick={() => {
    server.adopted = true
    onPublished(adoptedManuscript() as unknown as Manuscript)
  }}>采用这份稿件</button>,
}))

const project = {
  id: 'customer-project-1', name: '客户项目样例', research_topic: '比较病例与对照',
  project_type: 'sci', file_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
}
const base = '/api/v1/projects/' + project.id
const settings = {
  article_type: 'narrative_review', proposed_title: 'Planned article', target_journal: { choice: 'science', name: null },
  keywords: ['lineage'], review_sections: [{ id: 'section-1', heading: '文献主题', content: '描述领域现状。' }],
}
const snapshot = { ...snapshotFixture, project_id: project.id }
const first = { ...manuscriptFixture.versions[0], snapshot, exports: [], created_at: '2026-11-19T07:40:00Z' }
const second = { ...first, id: 'v2', revision: 2, parent_version_id: 'v1', task_id: 'draft-2', created_at: '2026-11-19T09:10:00Z',
  snapshot: { ...snapshot, review_provenance: { verification_status: 'not_verified' } } }
function adoptedManuscript() {
  return { ...manuscriptFixture, project_id: project.id, title: 'Planned article', current_revision: 2,
    updated_at: '2026-11-19T09:10:00Z', versions: [second, first] }
}
function currentManuscripts() {
  return server.adopted ? [adoptedManuscript()]
    : [{ ...manuscriptFixture, project_id: project.id, title: 'Planned article', current_revision: 1, updated_at: '2026-11-19T07:40:00Z', versions: [first] }]
}

type Export = typeof exportFixture
function serve(options: { exports?: Export[]; extra?: unknown[] } = {}) {
  const exports: Export[] = [...(options.exports ?? [])]
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === base) return Response.json(project)
    if (url === base + '/sci-settings') return Response.json({ settings, revision: 2 })
    if (url === base + '/manuscripts') return Response.json({ items: [...currentManuscripts(), ...(options.extra ?? [])] })
    if (url === base + '/manuscripts/m1/versions/2/exports') {
      if (init?.method === 'POST') {
        const key = new Headers(init.headers).get('Idempotency-Key')
        const created = { ...exportFixture, id: 'export-' + key, version_id: 'v2', created_at: '2026-11-19T09:11:00Z',
          download_url: `${base}/manuscripts/m1/exports/export-${key}/download` }
        if (!exports.some(item => item.id === created.id)) exports.unshift(created)
        return Response.json(created, { status: 201 })
      }
      return Response.json({ items: exports })
    }
    if (url === base + '/manuscripts/m1/versions/1/exports') return Response.json({ items: [] })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const exportPosts = (fetch: ReturnType<typeof serve>) => fetch.mock.calls.filter(([url, init]) => url.endsWith('/exports') && init?.method === 'POST')

beforeEach(() => { setApiSession('csrf', 'customer-test'); sessionStorage.clear(); server.adopted = false })
afterEach(() => {
  cleanup()
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it('goes from adopting to downloading the new version Word in two clicks without a leave prompt', async () => {
  const fetch = serve()
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  const push = vi.spyOn(window.history, 'pushState')
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=manuscripts&manuscript=m1&revision=1&view=writing`)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '采用这份稿件' }))
  await screen.findByRole('heading', { name: '固定版本与 Word', level: 1 })
  expect(String(push.mock.calls.at(-1)?.[2])).toContain(`#customer-project=${project.id}&step=word&manuscript=m1&revision=2&view=exports&adopted=1`)
  expect(confirm).not.toHaveBeenCalled()
  const notice = await screen.findByText(/^已采用这份稿件（Planned article，/)
  expect(notice.textContent).toMatch(/^已采用这份稿件（Planned article，第 2 版 · .+）。$/)
  const download = await screen.findByRole('link', { name: '下载这份 Word' })
  fireEvent.click(download)
  expect(exportPosts(fetch)).toHaveLength(1)
  const [, init] = exportPosts(fetch)[0]
  expect(new Headers(init?.headers).get('Idempotency-Key')).toBe('auto-word-v2')
  expect(init?.body).toBe('{}')
  await waitFor(() => expect(window.location.hash).not.toContain('adopted'))
  expect(window.location.hash).toContain('manuscript=m1&revision=2&view=exports')
  expect(screen.getByText(/^已采用这份稿件（Planned article，/)).toBeTruthy()
  expect(document.querySelector('.customer-step-content')?.textContent).not.toMatch(/DOCX/)
})

it('generates Word once for an adopted current version reached from the summary without the adopted flag', async () => {
  server.adopted = true
  const fetch = serve()
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=word&manuscript=m1&revision=2&view=exports`)
  render(<CustomerWorkspace />)
  await screen.findByRole('link', { name: '下载这份 Word' })
  expect(exportPosts(fetch)).toHaveLength(1)
  expect(new Headers(exportPosts(fetch)[0][1]?.headers).get('Idempotency-Key')).toBe('auto-word-v2')
  expect(screen.queryByText(/^已采用这份稿件/)).toBeNull()
})

it('carries the current manuscript to the Word page from the manuscript step', async () => {
  serve()
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=manuscripts&manuscript=m1&revision=1&view=body`)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '固定版本与 Word' }))
  await screen.findByRole('heading', { name: '固定版本与 Word', level: 1 })
  expect(window.location.hash).toBe(`#customer-project=${project.id}&step=word&manuscript=m1&revision=1&view=exports`)
})

it('opens the current version of the most recently updated manuscript on a Word page without one', async () => {
  server.adopted = true
  const older = { ...manuscriptFixture, id: 'm0', project_id: project.id, title: 'Older article', updated_at: '2026-11-01T00:00:00Z',
    versions: [{ ...first, id: 'v0' }] }
  const fetch = serve({ exports: [{ ...exportFixture, version_id: 'v2', download_url: `${base}/manuscripts/m1/exports/export1/download` }], extra: [older] })
  const replace = vi.spyOn(window.history, 'replaceState')
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=word`)
  render(<CustomerWorkspace />)
  await screen.findByRole('link', { name: '下载这份 Word' })
  expect(window.location.hash).toBe(`#customer-project=${project.id}&step=word&manuscript=m1&revision=2&view=exports`)
  expect(String(replace.mock.calls.at(-1)?.[2])).toContain('manuscript=m1&revision=2&view=exports')
  expect(exportPosts(fetch)).toHaveLength(0)
})
