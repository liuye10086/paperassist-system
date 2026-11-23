import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setLocale } from '../../shared/i18n'
import type { Reference } from '../literature/literatureApi'
import PaperDraftComposer from './PaperDraftComposer'
import { manuscriptFixture } from './manuscriptFixtures'
import { emptyInput, methodFields, type Candidates, type ManuscriptInput, type SourceCandidate } from './manuscriptTypes'
import { findPaperDraft, submitPaperDraft } from './submitPaperDraft'
import { liveRequest } from './writingLiveFixtures'

vi.mock('./submitPaperDraft', async importOriginal => ({
  ...await importOriginal<typeof import('./submitPaperDraft')>(),
  findPaperDraft: vi.fn(), submitPaperDraft: vi.fn(),
}))
const find = vi.mocked(findPaperDraft), submit = vi.mocked(submitPaperDraft)
const stamp = '2026-11-22T12:00:00Z', quote = 'The saved abstract reports the observed outcome.'
const reference: Reference = {
  id: 'ref1', reference_id: 'book1', project_id: 'p1', pmid: '123',
  record: {pmid: '123', title: 'Synthetic source', authors: ['Author'], year: 2024, journal: 'Example Journal',
    doi: null, abstract: [{label: 'Results', text: quote}], abstract_status: 'available', full_text_status: 'not_acquired',
    verification_status: 'not_verified', doi_resolution_status: 'not_checked', keywords: [], mesh_terms: [], full_text_links: []},
  selection: {status: 'candidate', note: '', revision: 1},
  source: {search_id: 's1', receipt_id: 'receipt', query: 'topic', effective_query: 'topic', retrieved_at: stamp,
    source_kind: 'synthetic_fixture', cached: false, ordinal: 1, source_download_url: '/api/v1/projects/p1/literature/receipts/receipt/source'},
  created_at: stamp, updated_at: stamp,
}
const file: SourceCandidate = {kind: 'document_version', id: 'doc1', file_id: 'file1', version: 1,
  label: 'Measurements.docx', allowed_roles: ['methods', 'user_results'], download_url: null}
function candidates(kind: 'research' | 'narrative_review' | 'thesis'): Candidates {
  return {
    project_type: kind === 'thesis' ? 'thesis' : 'sci', methods_fields: [...methodFields], citation_drafts: [], items: [file],
    paper_plan: {kind, title: 'Project title', keywords: ['analysis'], sections: [], materials: [],
      token: 'a'.repeat(64), omitted_count: 0},
    thesis: kind === 'thesis' ? {
      ready: true, confirmation_id: 'confirm1', blocking_reasons: [], purposes: ['introduction', 'manual'],
      profile: {revision: 3, school: 'School', department: '', major: '', degree_type: '', education_level: '',
        applicable_version: '', bound_confirmation_id: 'confirm1'},
      chapters: [{id: 'front', title: 'Cover', level: 1}, {id: 'custom', title: 'Research framework', level: 1}],
      template_source_file_ids: [], protected_chapter_purposes: {front: 'manual'},
    } : null,
  }
}
const collection = '/api/v1/projects/p1/manuscripts'
function serve() {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/v1/projects/p1/literature/references?page=1' && !init?.method) {
      return Response.json({project_id: 'p1', items: [reference], total: 1, page: 1, page_size: 10})
    }
    if (url === collection + '/selected-references' && init?.method === 'POST') return Response.json({id: 'citation1', revision: 1})
    if (url === collection && init?.method === 'POST') {
      const input: ManuscriptInput = JSON.parse(String(init.body))
      return Response.json({...manuscriptFixture, title: input.title, versions: [{...manuscriptFixture.versions[0], input}]})
    }
    throw new Error(`Unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}
function props(kind: 'research' | 'narrative_review' | 'thesis') {
  return {projectId: 'p1', active: true, school: kind === 'thesis', candidates: candidates(kind),
    baseInput: emptyInput('Base title', 'en'), planUnavailable: false, onPrepared: vi.fn(),
    onOpenGenerated: vi.fn(), onRefresh: vi.fn(), onOpenSchoolTemplate: vi.fn()}
}
const action = (name: string) => screen.getByRole('button', {name})
const consent = () => screen.getByRole('checkbox', {name: /接受本次写作费用/})
async function selectReference() {
  fireEvent.click(await screen.findByRole('checkbox', {name: new RegExp(quote)}))
}
function generate() {
  fireEvent.click(consent())
  fireEvent.click(action('生成正文初稿'))
}
beforeEach(() => {
  find.mockReset().mockResolvedValue(null)
  submit.mockReset().mockResolvedValue(liveRequest)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); setLocale('zh-CN') })

it('generates an SCI review from the checked abstract and saved project plan after one final consent', async () => {
  const api = serve(), page = props('narrative_review')
  render(<PaperDraftComposer {...page} />)
  fireEvent.click(consent())
  expect(action('生成正文初稿').matches(':disabled')).toBe(true)
  expect(screen.queryByRole('textbox', {name: '主要结果'})).toBeNull()
  await selectReference()
  expect(consent()).toHaveProperty('checked', false)
  expect(submit).not.toHaveBeenCalled()
  generate()
  await waitFor(() => expect(page.onOpenGenerated).toHaveBeenCalledWith('m1', 1, liveRequest.id))
  expect(submit).toHaveBeenCalledTimes(1)
  const writes = api.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(writes.map(([url]) => url)).toEqual([collection + '/selected-references', collection])
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({output_language: 'en',
    references: [{project_reference_id: 'ref1', search_id: 's1', quote}]})
  expect(JSON.parse(String(writes[1][1]?.body))).toMatchObject({title: 'Project title', paper_plan_token: 'a'.repeat(64),
    citation_draft: {id: 'citation1', revision: 1}, sources: [{id: 'doc1', role: 'methods'}]})
})

it('enables an SCI research draft once its reported result is connected to the selected upload', async () => {
  const api = serve(), page = props('research')
  render(<PaperDraftComposer {...page} />)
  fireEvent.change(screen.getByRole('textbox', {name: '主要结果'}), {target: {value: 'Seven samples passed.'}})
  fireEvent.click(consent())
  expect(action('生成正文初稿').matches(':disabled')).toBe(true)
  fireEvent.change(screen.getByRole('combobox', {name: '这项结果来自哪个文件？'}), {target: {value: 'doc1'}})
  generate()
  await waitFor(() => expect(page.onOpenGenerated).toHaveBeenCalledWith('m1', 1, liveRequest.id))
  const writes = api.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(writes.map(([url]) => url)).toEqual([collection])
  expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({
    reported_result: {text: 'Seven samples passed.', source_ids: ['doc1']}, sources: [{id: 'doc1', role: 'user_results'}],
  })
})

it('requires a confirmed school template and a writable chapter, then carries its mappings into the thesis draft', async () => {
  serve()
  const page = props('thesis'), ready = page.candidates.thesis!
  const view = render(<PaperDraftComposer {...page} candidates={{...page.candidates, thesis: {...ready, ready: false}}} />)
  fireEvent.click(action('确认学校模板'))
  expect(page.onOpenSchoolTemplate).toHaveBeenCalledOnce()
  fireEvent.click(consent())
  expect(action('生成正文初稿').matches(':disabled')).toBe(true)
  view.rerender(<PaperDraftComposer {...page} />)
  expect(action('生成正文初稿').matches(':disabled')).toBe(true)
  fireEvent.change(screen.getByRole('combobox', {name: 'Research framework'}), {target: {value: 'introduction'}})
  await selectReference()
  generate()
  await waitFor(() => expect(page.onOpenGenerated).toHaveBeenCalledWith('m1', 1, liveRequest.id))
  expect(submit.mock.calls[0][0].version.input).toMatchObject({
    citation_draft: {id: 'citation1', revision: 1},
    thesis: {confirmation_id: 'confirm1', profile_revision: 3, chapter_mappings: [
      {chapter_id: 'front', purpose: 'manual'}, {chapter_id: 'custom', purpose: 'introduction'},
    ]},
  })
})

it.each([false, true])('restores an uncertain submission without a model call and recovers with its original key (receipt found: %s)', async receiptFound => {
  const api = serve(), page = props('narrative_review')
  submit.mockRejectedValueOnce(new TypeError('Lost write response'))
  const first = render(<PaperDraftComposer {...page} />)
  await selectReference()
  generate()
  expect(await screen.findByRole('alert')).toBeTruthy()
  const attempt = submit.mock.calls[0][0].attemptKey
  const writes = () => api.mock.calls.filter(([, init]) => init?.method === 'POST')
  const firstKeys = writes().map(([, init]) => new Headers(init?.headers).get('Idempotency-Key'))
  first.unmount()
  render(<PaperDraftComposer {...page} />)
  await screen.findByRole('checkbox', {name: new RegExp(quote)})
  expect(consent()).toHaveProperty('checked', false)
  expect(action('用原请求继续').matches(':disabled')).toBe(true)
  expect(submit).toHaveBeenCalledTimes(1)
  expect(writes()).toHaveLength(2)
  find.mockResolvedValueOnce(receiptFound ? liveRequest : null)
  fireEvent.click(action('查看提交结果'))
  await waitFor(() => expect(find).toHaveBeenCalledWith(expect.objectContaining({attemptKey: attempt, manuscriptId: 'm1'})))
  if (receiptFound) {
    await waitFor(() => expect(page.onOpenGenerated).toHaveBeenCalledWith('m1', 1, liveRequest.id))
    expect(submit).toHaveBeenCalledTimes(1)
    expect(writes()).toHaveLength(2)
  } else {
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(writes()).toHaveLength(2)
    fireEvent.click(consent())
    fireEvent.click(action('用原请求继续'))
    await waitFor(() => expect(page.onOpenGenerated).toHaveBeenCalledWith('m1', 1, liveRequest.id))
    expect(submit.mock.calls.map(([input]) => input.attemptKey)).toEqual([attempt, attempt])
    expect(writes().slice(2).map(([, init]) => new Headers(init?.headers).get('Idempotency-Key'))).toEqual(firstKeys)
  }
})

it('unlocks the form after the server rejects the selected excerpt before writing', async () => {
  const api = serve(), page = props('narrative_review')
  const view = render(<PaperDraftComposer {...page} />)
  await selectReference()
  api.mockResolvedValueOnce(Response.json({detail: {code: 'selected_reference_quote_invalid', params: {position: 1}}}, {status: 422}))
  generate()
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(page.onRefresh).toHaveBeenCalledOnce()
  expect(submit).not.toHaveBeenCalled()
  expect(screen.getByRole('checkbox', {name: new RegExp(quote)}).matches(':disabled')).toBe(false)
  view.unmount()
  render(<PaperDraftComposer {...page} />)
  await screen.findByRole('checkbox', {name: new RegExp(quote)})
  expect(action('生成正文初稿').matches(':disabled')).toBe(true)
  generate()
  await waitFor(() => expect(submit).toHaveBeenCalledOnce())
})

it('allows recovery after the active view temporarily closes during submission', async () => {
  serve()
  const page = props('narrative_review')
  submit.mockImplementationOnce(({signal}) => new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), {once: true})
  }))
  const view = render(<PaperDraftComposer {...page} />)
  await selectReference()
  generate()
  await waitFor(() => expect(submit).toHaveBeenCalledOnce())
  view.rerender(<PaperDraftComposer {...page} active={false} />)
  await act(async () => {})
  view.rerender(<PaperDraftComposer {...page} />)
  expect(submit).toHaveBeenCalledOnce()
  expect(consent().matches(':disabled')).toBe(false)
  expect(action('查看提交结果').matches(':disabled')).toBe(false)
})
