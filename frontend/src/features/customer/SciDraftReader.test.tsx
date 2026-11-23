import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { SciDraftReader } from './SciDraftReader'

const props = { projectId: 'project1', manuscriptId: 'paper1', requestId: 'first', revision: 2, onRevise: vi.fn() }
const url = '/api/v1/projects/project1/manuscripts/paper1/writing-requests/first/draft-reader'
const citation = { number: 2, title: 'Frozen source title', project_reference_id: 'ref2',
  excerpts: [{ id: 'evidence2', quote: 'Exact words of the source.', reading_scope: 'abstract' }] }
const detail = { project_id: props.projectId, manuscript_id: props.manuscriptId, request_id: props.requestId,
  revision: 2, status: 'succeeded', previous_request_id: null, changes: [], error_code: null, can_revise: true,
  draft: { title: 'Draft title', output_language: 'en', sections: [
    { id: 'title', heading: 'Title', level: 1, groups: [], paragraphs: [{ id: 'title-p', parts: [{ text: 'Draft title', citations: [] }] }] },
    { id: 'discussion', heading: 'Discussion', level: 1, groups: [], paragraphs: [{ id: 'p', parts: [{ text: 'Manuscript prose.', citations: [citation] }] }] },
  ], keywords: [], acknowledgements: '', references: [{ number: 2, project_reference_id: 'ref2', text: 'Full bibliographic entry.' }] } }

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks() })

it('renders school headings and bibliography in template order and offers advisor revision', async () => {
  const thesis = {...detail.draft, sections: [
    {id:'cn-ref', purpose:'references', heading:'学校参考书目', level:1, output_language:'zh-CN', paragraphs:[], groups:[]},
    {id:'english-abstract', purpose:'abstract', heading:'Abstract', level:1, output_language:'en', paragraphs:[], groups:[]},
  ]}
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({...detail, draft:thesis})))
  render(<SciDraftReader {...props} thesis/>)
  expect(await screen.findByRole('heading', {name:'Draft title'})).toBeTruthy()
  expect(screen.getAllByRole('heading').map(h => h.textContent)).toEqual(['Draft title','学校参考书目','Abstract'])
  expect(screen.getByText(/Full bibliographic entry/).closest('section')?.getAttribute('lang')).toBe('zh-CN')
  expect(screen.getByRole('link', {name:'按学校模板下载 Word'}).getAttribute('href')).toBe(url + '/word?revision=2')
  fireEvent.click(screen.getByRole('button', {name:'按导师意见修改'}))
  expect(props.onRevise).toHaveBeenCalledOnce()
})

it('opens a numbered frozen excerpt beside the prose and downloads the exact draft', async () => {
  const fetcher = vi.fn(async () => Response.json(detail))
  vi.stubGlobal('fetch', fetcher)
  render(<SciDraftReader {...props}/>)
  expect(await screen.findByRole('heading', { name: 'Draft title' })).toBeTruthy()
  const marker = screen.getByRole('button', { name: '[2]' })
  expect(screen.queryByText(citation.excerpts[0].quote)).toBeNull()
  fireEvent.click(marker)
  expect(screen.getByText(citation.excerpts[0].quote)).toBeTruthy()
  expect(screen.getByText(citation.title)).toBeTruthy()
  fireEvent.click(marker)
  expect(screen.queryByText(citation.excerpts[0].quote)).toBeNull()
  expect(screen.getByRole('link', { name: '下载 Word' }).getAttribute('href')).toBe(url + '/word?revision=2')
  fireEvent.click(screen.getByRole('button', { name: '修改初稿' }))
  expect(props.onRevise).toHaveBeenCalledOnce()
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('reloads read failures and shows before and after even if paragraph ids changed', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(Response.json({}, {status: 503}))
    .mockResolvedValueOnce(Response.json({ ...detail, previous_request_id: 'original', changes: [
      { section_id: 'discussion', heading: 'Discussion', before: ['Original wording.'], after: ['Manuscript prose.[2]'], paragraph_ids: ['p'] },
    ] })))
  render(<SciDraftReader {...props}/>)
  fireEvent.click(within(await screen.findByRole('alert')).getByRole('button', {name:'重试'}))
  const changes = await screen.findByText('查看修改处')
  fireEvent.click(changes)
  expect(screen.getByText('Original wording.')).toBeTruthy()
  expect(screen.getByText('Manuscript prose.[2]')).toBeTruthy()
})

it('polls the pinned queued request and stops after its body arrives', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json({...detail, status:'queued', draft:null}))
    .mockResolvedValueOnce(Response.json(detail))
  vi.stubGlobal('fetch', fetcher)
  render(<SciDraftReader {...props}/>)
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(screen.getByRole('status').textContent).toContain('已排队')
  expect(screen.queryByRole('link', {name:'下载 Word'})).toBeNull()
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(screen.getByRole('heading', {name:'Draft title'})).toBeTruthy()
  await act(() => vi.advanceTimersByTimeAsync(30000))
  expect(fetcher.mock.calls.map(call => call[0])).toEqual([url + '?revision=2', url + '?revision=2'])
})

it('keeps historical drafts readable and confirms the browser download handoff', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(Response.json({...detail, can_revise:false}))
    .mockResolvedValueOnce(new Response('fixed bytes')))
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:fixed-draft')
    static revokeObjectURL = vi.fn()
  })
  const download = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  render(<SciDraftReader {...props}/>)
  fireEvent.click(await screen.findByRole('link', {name:'下载 Word'}))
  expect(await screen.findByText('Word 已交给浏览器下载。')).toBeTruthy()
  expect(download).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', {name:'修改初稿'})).toBeNull()
})
