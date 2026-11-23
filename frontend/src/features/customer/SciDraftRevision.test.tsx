import {webcrypto} from 'node:crypto'
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import {authFixture, bundleFixture, liveRequest} from '../manuscripts/writingLiveFixtures'
import type {LiveRequest} from '../manuscripts/writingLiveTypes'
import {SciDraftRevision} from './SciDraftRevision'

const props = {projectId: 'p1', manuscriptId: 'm1', revision: 1, requestId: 'w1', onClose: vi.fn(), onCreated: vi.fn()}
const parent = {...liveRequest, input: {...liveRequest.input, selected_source_ids: ['sourceA'], selected_evidence_ids: ['evidenceA']}}
beforeEach(() => {sessionStorage.clear(); vi.stubGlobal('crypto', webcrypto)})
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks()})

function server(lost = false, original: LiveRequest = parent) {
  const posts: string[] = [], records = [original]
  let bundle = bundleFixture()
  const chapter = original.candidate?.thesis_context?.chapters[0]
  if (chapter) bundle.local_manifest = {...bundle.local_manifest, protected_identity:{sha256:'a'.repeat(64)},
    school:{schema_version:1, chapters:{chapter1:{...chapter, chapter_id:chapter.id}}, writable_aliases:['chapter1']}}
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const endpoint = url.split('/').at(-1)!
    if (init?.method !== 'POST') {
      if (endpoint === 'writing-requests') return Response.json({items: records})
      if (endpoint === 'w1') return Response.json(original)
      if (endpoint === 'writing-previews') return Response.json({items: [], capabilities: {real_calls_enabled: true}})
    }
    posts.push(endpoint)
    if (endpoint === 'draft-feedback') return Response.json({text: 'Review the uploaded comparison.'})
    const body = JSON.parse(String(init?.body))
    if (endpoint === 'writing-previews') {bundle = {...bundle, request_json: body}; return Response.json(bundle)}
    if (endpoint === 'writing-authorizations') {
      const auth = authFixture([bundle])
      return Response.json({...auth, occupied_posts: 0, manifest: {...auth.manifest, tasks: body.tasks}})
    }
    if (endpoint === 'writing-requests') {
      const item = {...liveRequest, id: 'w2', task: {...liveRequest.task, id: 'w2', status: 'queued' as const},
        input: bundle.request_json, execution: body, candidate: null}
      records.push(item)
      if (lost) throw new Error('lost receipt')
      return Response.json(item)
    }
    throw new Error(url)
  }))
  return {posts, input: () => bundle.request_json}
}

it('submits advisor feedback and retains the original school protocol and evidence', async () => {
  const chapter = {id:'original-chapter', title:'Study methods', purpose:'materials_and_methods' as const,
    level:1, output_language:'en' as const, result_group_ids:[]}
  const school: LiveRequest = {...parent, input:{...parent.input, schema_version:3}, candidate:{...parent.candidate!,
    thesis_context:{schema_version:1, template_version_id:'school-v1', confirmation_id:'checked',
      confirmation_sha256:'a'.repeat(64), confirmation:{}, source_files:[], chapters:[chapter],
      profile:{school:'Test school', revision:1, bound_confirmation_id:'checked', department:'', major:'', degree_type:'',
        education_level:'', applicable_version:''}},
    sections:[{...chapter, paragraphs:parent.candidate!.sections![0].paragraphs}],
    school_content_report:{rules_version:'school-v1', issues:[], can_publish:true, scientifically_verified:false}}}
  const api = server(false, school)
  render(<SciDraftRevision {...props} thesis/>)
  expect(screen.getByRole('heading', {name:'按导师意见修改'})).toBeTruthy()
  fireEvent.change(screen.getByLabelText('导师意见'), {target:{value:'Explain the school chapter.'}})
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', {name:'生成修改稿'}))
  await waitFor(() => expect(props.onCreated).toHaveBeenCalledWith('m1',1,'w2'))
  expect(api.input()).toEqual({...school.input, revision_of_request_id:'w1', instructions:'Explain the school chapter.'})
})

it('loads a feedback file for editing and writes against the pinned original only after confirmation', async () => {
  const api = server()
  render(<SciDraftRevision {...props}/>)
  fireEvent.change(screen.getByLabelText('上传意见文件'), {target: {files: [new File(['word'], 'opinion.docx')]}})
  const box = await screen.findByDisplayValue('Review the uploaded comparison.')
  fireEvent.change(box, {target: {value: 'Clarify the control group.'}})
  expect(api.posts).toEqual(['draft-feedback'])
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', {name: '生成修改稿'}))
  await waitFor(() => expect(props.onCreated).toHaveBeenCalledWith('m1', 1, 'w2'))
  expect(api.input()).toMatchObject({revision_of_request_id: 'w1', instructions: 'Clarify the control group.',
    selected_source_ids: ['sourceA'], selected_evidence_ids: ['evidenceA']})
  expect(api.posts).toEqual(['draft-feedback', 'writing-previews', 'writing-authorizations', 'writing-requests'])
})

it('restores an uncertain revision after reload using its receipt and no further model submission', async () => {
  const api = server(true)
  const first = render(<SciDraftRevision {...props}/>)
  fireEvent.change(screen.getByLabelText('审稿意见'), {target: {value: 'Explain the controls.'}})
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', {name: '生成修改稿'}))
  await screen.findByRole('alert')
  first.unmount()
  render(<SciDraftRevision {...props}/>)
  fireEvent.click(screen.getByRole('button', {name: '查看提交结果'}))
  await waitFor(() => expect(props.onCreated).toHaveBeenCalledWith('m1', 1, 'w2'))
  expect(api.posts).toEqual(['writing-previews', 'writing-authorizations', 'writing-requests'])
})
