import {webcrypto} from 'node:crypto'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import {manuscriptFixture} from './manuscriptFixtures'
import type {FrozenSource, ManuscriptVersion} from './manuscriptTypes'
import {findPaperDraft, isPaperDraftRejected, submitPaperDraft} from './submitPaperDraft'
import {TaskRequestError} from '../tasks/taskApi'
import {authFixture, bundleFixture, liveRequest} from './writingLiveFixtures'
import {validPreviewInput, type Authorization, type Bundle, type ExecutionGroup, type LiveRequest, type PreviewInput} from './writingLiveTypes'

const scope = {projectId: 'p1', manuscriptId: 'm1', attemptKey: 'click-1'}
const plainVersion = manuscriptFixture.versions[0] as unknown as ManuscriptVersion
const source = (id: string, kind: FrozenSource['kind'], role: FrozenSource['role']): FrozenSource => ({
  id, kind, role, file_id: id + '-file', sha256: 'a'.repeat(64), label: id, content: {}, download_url: null,
})
const document = source('methods', 'document_version', 'methods')
const run = source('run', 'analysis_run', 'computed_results')
const figure = source('illustration', 'original', 'image_observation')
const citation = {paragraphs: [{fragments: [{kind: 'claim', bindings: [
  {evidence: [{id: 'e2', quote: 'Selected excerpt'}, {id: 'e1', quote: 'Another excerpt'}]},
  {evidence: [{id: 'e2', quote: 'Selected excerpt'}]},
]}]}]}
const version: ManuscriptVersion = {...plainVersion, snapshot: {...plainVersion.snapshot,
  keywords: ['frozen'], citation_snapshot: citation, sources: [document, run, figure]}}
const options = () => ({...scope, version, signal: new AbortController().signal})

function server(settings: {
  enabled?: boolean
  changeBundle?: (bundle: Bundle) => Bundle
  changeGrant?: (tasks: Authorization['manifest']['tasks']) => Authorization['manifest']['tasks']
  loseReply?: boolean
  afterAuthorization?: () => void
} = {}) {
  const posts: {endpoint: string; key: string; body: Record<string, unknown>}[] = []
  const records: LiveRequest[] = []
  let preview: Bundle
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const endpoint = url.split('/').at(-1)!
    if (init?.method !== 'POST') {
      if (endpoint === 'writing-requests') return Response.json({items: [{schema_version: 1}, ...records]})
      if (endpoint === 'writing-previews') return Response.json({items: [], capabilities: {real_calls_enabled: settings.enabled ?? true}})
    } else {
      const body = JSON.parse(String(init.body))
      posts.push({endpoint, key: new Headers(init.headers).get('Idempotency-Key') ?? '', body})
      if (endpoint === 'writing-previews') {
        preview = {...bundleFixture(), request_json: body as PreviewInput}
        if (body.schema_version === 3) {
          preview.local_manifest = {...preview.local_manifest, protected_identity: {sha256: 'b'.repeat(64)},
            school: {schema_version: 1, chapters: {chapter1: {chapter_id: 'custom-methods', title: '试验方法', level: 1,
              purpose: 'materials_and_methods', output_language: 'en', result_group_ids: []}}, writable_aliases: ['chapter1']}}
        }
        return Response.json(settings.changeBundle?.(preview) ?? preview)
      }
      if (endpoint === 'writing-authorizations') {
        const auth = authFixture([preview])
        settings.afterAuthorization?.()
        return Response.json({...auth, occupied_posts: 0, logical_task_usage: [],
          manifest: {...auth.manifest, tasks: settings.changeGrant?.(body.tasks) ?? body.tasks}})
      }
      if (endpoint === 'writing-requests') {
        const {bundle_id, authorization_id, logical_task_id} = body as ExecutionGroup
        const result = {...liveRequest, candidate: null, input: preview.request_json,
          task: {...liveRequest.task, status: 'queued', display_status: 'queued'} as LiveRequest['task'],
          execution: {bundle_id, authorization_id, logical_task_id}}
        records.push(result)
        if (settings.loseReply) throw new TypeError('connection lost after acceptance')
        return Response.json(result, {status: 202})
      }
    }
    throw new Error('Unexpected request ' + url)
  })
  vi.stubGlobal('fetch', fetcher)
  return {posts, records, fetcher}
}

beforeEach(() => vi.stubGlobal('crypto', webcrypto))
afterEach(() => vi.unstubAllGlobals())

it('submits the full frozen research draft with the selected files and distinct citation evidence', async () => {
  const {posts, records} = server()
  const result = await submitPaperDraft(options())
  expect(result).toEqual(records[0])
  expect(posts.map(p => p.endpoint)).toEqual(['writing-previews', 'writing-authorizations', 'writing-requests'])
  expect(posts[0].body).toMatchObject({schema_version: 4, document_kind: 'sci', article_type: 'research', mode: 'full_draft',
    target_section: null, target_sections: [], keywords: ['frozen'], output_language: 'en', document_context_version: 'selected-text-v1',
    selected_source_ids: ['methods', 'run', 'illustration'], selected_evidence_ids: ['e2', 'e1']})
  const grant = {bundle_id: 'b1', bundle_sha256: bundleFixture().bundle_sha256}
  expect(posts[1].body).toEqual({schema_version: 2, confirmed: true, tasks: [{logical_task_id: result.execution!.logical_task_id, bundles: [grant]}]})
  expect(posts[2].body).toEqual({schema_version: 2, authorization_id: 'auth1', logical_task_id: result.execution!.logical_task_id, ...grant})
  expect(posts.every(p => p.key.length > 0)).toBe(true)
  expect(new Set(posts.map(p => p.key)).size).toBe(3)
})

it('includes review literature and its planned illustrations while excluding original study results', async () => {
  const {posts} = server()
  await submitPaperDraft({...options(), version: {...version, snapshot: {...version.snapshot,
    paper_plan: {kind: 'narrative_review', title: 'Review', keywords: [], sections: [{id: 'theme', label: 'Theme', text: 'Theme'}],
      materials: [{section_id: 'theme', kind: 'figure', filename: 'map.png', result: 'Summary', selection: figure}]},
    sources: [document, run, figure, source('other', 'original', 'user_results')]}}})
  expect(posts[0].body).toMatchObject({schema_version: 4, article_type: 'narrative_review',
    selected_source_ids: ['methods', 'illustration'], selected_evidence_ids: ['e2', 'e1']})
})

it('uses project article settings for historical SCI snapshots without paper plan or keywords', async () => {
  const {posts} = server()
  await submitPaperDraft({...options(), version: {...version, snapshot: {...version.snapshot, keywords: undefined}},
    sciSettings: {article_type: 'narrative_review', keywords: ['legacy topic']}})
  expect(posts[0].body).toMatchObject({article_type: 'narrative_review', keywords: ['legacy topic'], selected_source_ids: ['methods']})
})

it('selects planned original figures in native review sections and excludes unplanned or unsupported placements', async () => {
  const {posts} = server()
  const images = ['introduction', 'discussion', 'conclusion', 'abstract'].map(id => source(id, 'original', 'image_observation'))
  const table = source('table', 'original', 'user_results')
  await submitPaperDraft({...options(), version: {...version, snapshot: {...version.snapshot,
    paper_plan: {kind: 'narrative_review', title: 'Review', keywords: [], sections: [],
      materials: [...images.map(image => ({section_id: image.id, kind: 'figure' as const, filename: image.id + '.png', result: '', selection: image})),
        {section_id: 'discussion', kind: 'table', filename: 'results.xlsx', result: 'Results', selection: table}]},
    sources: [document, run, ...images, table, figure]}}})
  expect(posts[0].body.selected_source_ids).toEqual(['methods', 'introduction', 'discussion', 'conclusion'])
})

it('uses the full school chapter contract and includes sources and excerpts in thesis writing', async () => {
  const {posts} = server()
  const school = {confirmation_id: 'confirmed', chapters: [{id: 'custom-methods', purpose: 'materials_and_methods'}]} as NonNullable<ManuscriptVersion['snapshot']['thesis_context']>
  await submitPaperDraft({...options(), version: {...version, snapshot: {...version.snapshot, thesis_context: school}}})
  expect(posts[0].body).toEqual({schema_version: 3, base_revision: 1, mode: 'full_draft', target_section: null, output_language: 'en',
    instructions: '', keywords: [], acknowledgements: '', document_context_version: 'selected-text-v1',
    selected_source_ids: ['methods', 'run', 'illustration'], selected_evidence_ids: ['e2', 'e1']})
})

it('rejects a thesis preparation without a frozen school context before writing', async () => {
  const {posts} = server()
  await expect(submitPaperDraft({...options(),documentKind:'thesis'})).rejects.toThrow()
  expect(posts).toEqual([])
})

it.each([
  ['disabled live capability', {enabled: false}, 0],
  ['changed outgoing bytes', {changeBundle: (b: Bundle) => ({...b, wire_json: b.wire_json + ' '})}, 1],
  ['wrong base version', {changeBundle: (b: Bundle) => ({...b, base_version_id: 'older'})}, 1],
  ['wrong preview scope', {changeBundle: (b: Bundle) => ({...b, request_json: {...b.request_json, selected_source_ids: []}})}, 1],
  ['returned authorization has extra grants', {changeGrant: (tasks: Authorization['manifest']['tasks']) =>
    [...tasks, {...tasks[0], logical_task_id: 'other-task'}]}, 2],
] as const)('rejects %s before submitting a writing request', async (_name, settings, count) => {
  const {posts} = server(settings)
  await expect(submitPaperDraft(options())).rejects.toThrow()
  expect(posts).toHaveLength(count)
})

it('recovers a lost receipt using reads, even after live writing has been disabled', async () => {
  const settings = {loseReply: true, enabled: true}
  const {posts, records} = server(settings)
  await expect(submitPaperDraft(options())).rejects.toThrow()
  expect(posts.filter(p => p.endpoint === 'writing-requests')).toHaveLength(1)
  settings.enabled = false
  expect(await findPaperDraft(options())).toEqual(records[0])
  expect(await findPaperDraft({...options(), attemptKey: 'different-click'})).toBeNull()
  expect(await submitPaperDraft(options())).toEqual(records[0])
  expect(posts).toHaveLength(3)
})

it('uses the original stage keys on an explicit retry, and different keys for a new confirmation', async () => {
  const {posts, records} = server()
  await submitPaperDraft(options())
  records.length = 0
  await submitPaperDraft(options())
  expect(posts.slice(3)).toEqual(posts.slice(0, 3))
  await submitPaperDraft({...options(), attemptKey: 'different-click'})
  expect(new Set(posts.map(p => p.key)).size).toBe(6)
  expect(posts[8].body.logical_task_id).not.toBe(posts[2].body.logical_task_id)
})

it('does not launch writing after a workspace is closed during authorization', async () => {
  const controller = new AbortController()
  const {posts} = server({afterAuthorization: () => controller.abort()})
  await expect(submitPaperDraft({...options(), signal: controller.signal})).rejects.toThrow()
  expect(posts.map(p => p.endpoint)).toEqual(['writing-previews', 'writing-authorizations'])
})

it('distinguishes actionable rejections from a lost receipt for preserving the original submission', async () => {
  server({enabled: false})
  expect(isPaperDraftRejected(await submitPaperDraft(options()).catch(e => e))).toBe(true)
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return Response.json({detail: {code: 'manuscript_writing_evidence_required'}}, {status: 422})
    return Response.json(url.endsWith('writing-previews') ? {items: [], capabilities: {real_calls_enabled: true}} : {items: []})
  }))
  const rejected = await submitPaperDraft(options()).catch(e => e)
  expect(rejected).toBeInstanceOf(TaskRequestError)
  expect(rejected.code).toBe('manuscript_writing_evidence_required')
  expect(isPaperDraftRejected(rejected)).toBe(true)
  server({loseReply: true})
  expect(isPaperDraftRejected(await submitPaperDraft(options()).catch(e => e))).toBe(false)
})

it('reads versioned upload excerpts only on supported school and article preview contracts', async () => {
  const {posts} = server()
  await submitPaperDraft(options())
  expect(validPreviewInput(posts[0].body)).toBe(true)
  expect(validPreviewInput({...posts[0].body, document_context_version: 'unrecognized'})).toBe(false)
  expect(validPreviewInput({...bundleFixture().request_json, document_context_version: 'selected-text-v1'})).toBe(false)
})

it('lets the writing API evaluate an explicitly selected historical analysis version', async () => {
  const {records} = server()
  const current_changes = [{kind: 'analysis_run', id: 'run', reasons: ['analysis_configuration_changed']}]
  const result = await submitPaperDraft({...options(), version: {...version, current_changes}})
  expect(result).toEqual(records[0])
})

it('keeps the attempt after a request lookup fails or the final receipt cannot be read', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({detail: {code: 'project_assignment_stale'}}, {status: 409})))
  const lookupError = await submitPaperDraft(options()).catch(e => e)
  expect(lookupError).toBeInstanceOf(TaskRequestError)
  expect(isPaperDraftRejected(lookupError)).toBe(false)
  const {fetcher} = server()
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) =>
    url.endsWith('writing-requests') && init?.method === 'POST'
      ? Response.json({detail: {code: 'project_assignment_stale'}}, {status: 409}) : fetcher(url, init)))
  const receiptError = await submitPaperDraft(options()).catch(e => e)
  expect(receiptError).toBeInstanceOf(TaskRequestError)
  expect(isPaperDraftRejected(receiptError)).toBe(false)
})
