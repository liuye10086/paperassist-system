import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import CustomerWorkspace from './CustomerWorkspace'

vi.mock('./SciDraftReader', () => ({ SciDraftReader: (p: { requestId: string; onRevise: () => void }) =>
  <button onClick={p.onRevise}>Read {p.requestId}</button> }))
vi.mock('./SciDraftRevision', () => ({ SciDraftRevision: (p: { onCreated: (m: string, v: number, r: string) => void }) =>
  <button onClick={() => p.onCreated('paper', 4, 'revised')}>Revise</button> }))
vi.mock('./SciDraftGenerator', () => ({
  ThesisDraftGenerator: (p: {initialSearchId?: string; onSubmitted: (m: string, v: number, r: string) => void}) =>
    <button onClick={() => p.onSubmitted('paper2', 4, 'writing2')}>生成毕业论文初稿 {p.initialSearchId}</button>,
  SciDraftGenerator: () => null,
}))
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
  window.history.replaceState(null, '', window.location.pathname)
})
function open(projectType: 'sci' | 'thesis', params: Record<string, string>) {
  const project = { id: 'p1', name: 'Test', project_type: projectType, research_topic: 'Topic', file_count: 0,
    created_at: '2026-11-22T10:00:00Z', updated_at: '2026-11-22T10:00:00Z' }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/v1/projects/p1') return Response.json(project)
    if (url.includes('/sci-current-draft')) return Response.json({ draft: { manuscript_id: 'paper', revision: 4, request_id: 'original' } })
    if (url.endsWith('/sci-settings')) return Response.json({ settings: null })
    if (url.endsWith('/thesis-requirements')) return Response.json({title:'Thesis', keywords:['keyword'], sections:[], template:null})
    return Response.json({})
  }))
  const hash = new URLSearchParams({ 'customer-project': project.id, ...params })
  window.history.replaceState(null, '', '#' + hash.toString())
  render(<CustomerWorkspace />)
}

it('keeps a saved thesis search in the fourth step and opens its exact generated request', async () => {
  open('thesis', { step:'materials', view:'list', search:'search1', paragraph:'old:3' })
  const nav = await screen.findByRole('navigation', {name:'毕业论文项目步骤'})
  expect([...nav.querySelectorAll('button')].map(b => b.textContent)).toEqual(['项目资料','上传资料','模板与资料整理','文献与初稿'])
  fireEvent.click(await screen.findByRole('button', {name:'生成毕业论文初稿 search1'}))
  expect(await screen.findByRole('button', {name:'Read writing2'})).toBeTruthy()
  const params = new URLSearchParams(location.hash.slice(1))
  expect(params.get('step')).toBe('manuscripts')
  expect(params.has('paragraph')).toBe(false)
  expect(params.has('search')).toBe(false)
})

it('opens a bookmarked thesis Word request and revises it inside the manuscript step', async () => {
  open('thesis', {step:'word', manuscript:'paper', revision:'2', writingRequest:'previous'})
  fireEvent.click(await screen.findByRole('button', {name:'Read previous'}))
  fireEvent.click(await screen.findByRole('button', {name:'Revise'}))
  expect(await screen.findByRole('button', {name:'Read revised'})).toBeTruthy()
  expect(location.hash).toContain('step=manuscripts')
})

it.each(['journals', 'word', 'reviews', 'manuscripts'])('opens the current SCI draft from %s with only three steps', async step => {
  open('sci', { step })
  fireEvent.click(await screen.findByRole('button', { name: 'Read original' }))
  const nav = screen.getByRole('navigation', { name: 'SCI 项目步骤' })
  expect([...nav.querySelectorAll('button')].map(b => b.textContent)).toEqual(['项目资料', '上传资料', '文献与初稿'])
  fireEvent.click(await screen.findByRole('button', { name: 'Revise' }))
  expect(await screen.findByRole('button', { name: 'Read revised' })).toBeTruthy()
  expect(location.hash).toContain('writingRequest=revised')
})

it('reads a bookmarked SCI request without replacing it with the newest draft', async () => {
  open('sci', { step: 'manuscripts', manuscript: 'paper', revision: '2', writingRequest: 'previous', view: 'writing' })
  expect(await screen.findByRole('button', { name: 'Read previous' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Read original' })).toBeNull()
})
