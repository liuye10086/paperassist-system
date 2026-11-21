// B03 task 7: a paragraph that lacks a source sends the customer to add literature or materials and back to it.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { manuscriptFixture, snapshotFixture } from '../manuscripts/manuscriptFixtures'
import CustomerWorkspace from './CustomerWorkspace'

type Need = (kind: 'literature' | 'materials', target: { writingRequest: string; paragraph: string }, location: { section: string; paragraph: number }) => void
vi.mock('../manuscripts/WritingLive', () => ({
  default: ({ onNeedSource, initialWritingRequest, initialParagraph }: { onNeedSource?: Need; initialWritingRequest?: string; initialParagraph?: string }) => <div>
    <p>{`received:${initialWritingRequest ?? ''}|${initialParagraph ?? ''}`}</p>
    <button type="button" onClick={() => onNeedSource?.('literature', { writingRequest: 'w1', paragraph: 'discussion:2' }, { section: '讨论', paragraph: 2 })}>去添加文献（完成后回到本段）</button>
    <button type="button" onClick={() => onNeedSource?.('materials', { writingRequest: 'w1', paragraph: 'discussion:2' }, { section: '讨论', paragraph: 2 })}>去补充材料（完成后回到本段）</button>
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
  id: 'customer-project-1', name: '客户项目样例', research_topic: '比较病例与对照',
  project_type: 'sci', file_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
}
const base = '/api/v1/projects/' + project.id
const settings = {
  article_type: 'narrative_review', proposed_title: 'Planned article', target_journal: { choice: 'science', name: null },
  keywords: ['lineage'], review_sections: [{ id: 'section-1', heading: '文献主题', content: '描述领域现状。' }],
}
const manuscript = { ...manuscriptFixture, project_id: project.id, title: 'Planned article',
  versions: [{ ...manuscriptFixture.versions[0], snapshot: { ...snapshotFixture, project_id: project.id }, exports: [] }] }
const writing = `customer-project=${project.id}&step=manuscripts&manuscript=m1&revision=1&view=writing`

beforeEach(() => {
  setApiSession('csrf', 'customer-test')
  sessionStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === base) return Response.json(project)
    if (url === base + '/sci-settings') return Response.json({ settings, revision: 2 })
    if (url === base + '/manuscripts') return Response.json({ items: [manuscript] })
    return new Response(null, { status: 404 })
  }))
})
afterEach(() => {
  cleanup()
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

function expectedTrip(step: string, view: string) {
  const origin = new URLSearchParams(writing)
  origin.set('writingRequest', 'w1')
  origin.set('paragraph', 'discussion:2')
  return '#' + new URLSearchParams({ 'customer-project': project.id, step, view, return: origin.toString(),
    returnLabel: 'paragraph', returnSection: '讨论', returnParagraph: '2' }).toString()
}

it('goes to the literature list with a return token and keeps it while switching views inside the page', async () => {
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  window.history.replaceState(null, '', '#' + writing)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去添加文献（完成后回到本段）' }))
  await waitFor(() => expect(window.location.hash).toBe(expectedTrip('citations', 'list')))
  expect(confirm).not.toHaveBeenCalled()
  expect(await screen.findByText('正在为“讨论第 2 段”补充依据')).toBeTruthy()
  expect(screen.getByRole('link', { name: '返回 讨论第 2 段' })).toBeTruthy()
  expect(screen.getByText('waiting-for-reference')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '项目文件' }))
  await waitFor(() => expect(window.location.hash).toContain('view=files'))
  expect(window.location.hash).toContain('returnLabel=paragraph')
  expect(screen.getByRole('link', { name: '返回 讨论第 2 段' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '写作资料与引用' }))
  await waitFor(() => expect(window.location.hash).toBe(`#customer-project=${project.id}&step=materials`))
  expect(screen.queryByRole('link', { name: '返回 讨论第 2 段' })).toBeNull()
})

it('returns to the paragraph by itself once the added reference is ready', async () => {
  window.history.replaceState(null, '', '#' + writing)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去添加文献（完成后回到本段）' }))
  fireEvent.click(await screen.findByRole('button', { name: '入选并核对书目' }))
  expect(await screen.findByText('received:w1|discussion:2')).toBeTruthy()
  expect(window.location.hash).toBe('#' + writing + '&writingRequest=w1&paragraph=discussion%3A2')
})

it('returns from the literature page through the return bar', async () => {
  window.history.replaceState(null, '', '#' + writing)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去添加文献（完成后回到本段）' }))
  fireEvent.click(await screen.findByRole('link', { name: '返回 讨论第 2 段' }))
  expect(await screen.findByText('received:w1|discussion:2')).toBeTruthy()
})

it('goes to the project files for a missing material and comes back after an upload', async () => {
  window.history.replaceState(null, '', '#' + writing)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去补充材料（完成后回到本段）' }))
  await waitFor(() => expect(window.location.hash).toBe(expectedTrip('materials', 'files')))
  expect(await screen.findByText('waiting-for-upload')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '上传完成' }))
  expect(await screen.findByText('received:w1|discussion:2')).toBeTruthy()
})

it('ignores a malformed paragraph in the writing address', async () => {
  window.history.replaceState(null, '', '#' + writing + '&writingRequest=w1&paragraph=' + encodeURIComponent('<bad>'))
  render(<CustomerWorkspace />)
  expect(await screen.findByText('received:w1|')).toBeTruthy()
})
