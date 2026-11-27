import {webcrypto} from 'node:crypto'
import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import {authFixture, bundleFixture, liveRequest} from '../manuscripts/writingLiveFixtures'
import type {SchoolChapter} from '../manuscripts/thesisTypes'
import {jsonDigest, type LiveRequest} from '../manuscripts/writingLiveTypes'
import {SciDraftRevision} from './SciDraftRevision'
import {resolveDraftChat} from './sciDraftChatIntent'
import {getApiUserId} from '../../shared/api/client'

const props = {projectId: 'p1', manuscriptId: 'm1', revision: 1, requestId: 'w1'}
const parent = {...liveRequest, input: {...liveRequest.input, selected_source_ids: ['sourceA'], selected_evidence_ids: ['evidenceA']}}
const chapterDefaults = {level:1, output_language:'en' as const, result_group_ids:[]}
const methods: SchoolChapter = {...chapterDefaults, id:'thesis:school:methods', title:'Study design', purpose:'materials_and_methods'}
const conclusion: SchoolChapter = {...chapterDefaults, id:'thesis:school:conclusion', title:'Study conclusions', purpose:'conclusion'}
const chapters: SchoolChapter[] = [methods, conclusion,
  {...chapterDefaults, id:'thesis:school:references', title:'Reference list', purpose:'references'}]
const school: LiveRequest = {...parent, input:{...parent.input, schema_version:3}, candidate:{...parent.candidate!,
  thesis_context:{schema_version:1, template_version_id:'school-v1', confirmation_id:'checked',
    confirmation_sha256:'a'.repeat(64), confirmation:{}, source_files:[], chapters,
    profile:{school:'Test school', revision:1, bound_confirmation_id:'checked', department:'', major:'', degree_type:'',
      education_level:'', applicable_version:''}},
  sections:chapters.map(chapter => ({...chapter, paragraphs:parent.candidate!.sections![0].paragraphs})),
  school_content_report:{rules_version:'school-v1', issues:[], can_publish:true, scientifically_verified:false}}}
const sessionKey = () => `paperassist.research-draft.v1:${getApiUserId() ?? 'anonymous'}:p1:sci-revision:m1:w1`
beforeEach(() => {sessionStorage.clear(); vi.stubGlobal('crypto', webcrypto)})
afterEach(() => {cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks()})

function draftDetail(id: string, previous: string | null, status: 'queued' | 'running' | 'succeeded' = 'succeeded') {
  const title = id === 'w1' ? 'Original draft' : `Revised draft ${id}`
  return {project_id:'p1', manuscript_id:'m1', revision:1, request_id:id, status,
    previous_request_id:previous, can_revise:status === 'succeeded', error_code:null,
    editable_section_ids:['title', 'discussion', 'conclusion'],
    changes:previous && status === 'succeeded' ? [{section_id:'discussion', heading:'Discussion',
      before:[`Before ${id}`], after:[`After ${id}`], paragraph_ids:[]}] : [],
    draft:status === 'succeeded' ? {title, output_language:'en', sections:[{id:'title', heading:'Title', level:0, groups:[],
      paragraphs:[{id:'title-p', parts:[{text:title, citations:[]}]}]},
      {id:'discussion', heading:'Discussion', level:1, groups:[],
        paragraphs:[{id:'discussion-p', parts:[{text:'Discussion text', citations:[]}]}]},
      {id:'conclusion', heading:'Conclusion', level:1, groups:[],
        paragraphs:[{id:'conclusion-p', parts:[{text:'Conclusion text', citations:[]}]}]}],
      keywords:[], acknowledgements:'', references:[]} : null}
}

function server(lost = false, original: LiveRequest = parent) {
  const posts: string[] = [], reads: string[] = [], records = [original]
  let bundle = bundleFixture()
  const chapters = original.candidate?.thesis_context?.chapters
  if (chapters) bundle.local_manifest = {...bundle.local_manifest, protected_identity:{sha256:'a'.repeat(64)},
    school:{schema_version:1, chapters:Object.fromEntries(chapters.map((ch, i) => ['chapter' + (i + 1), {...ch, chapter_id:ch.id}])),
      writable_aliases:['chapter1', 'chapter2']}}
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const endpoint = url.split('/').at(-1)!
    if (init?.method !== 'POST') {
      reads.push(endpoint)
      if (endpoint === 'writing-requests') return Response.json({items: records})
      if (endpoint === 'writing-previews') return Response.json({items: [], capabilities: {real_calls_enabled: true}})
      if (endpoint === 'writing-previews?capabilities_only=true') return Response.json({capabilities: {real_calls_enabled: true}})
      const request = records.find(item => item.id === (endpoint.startsWith('draft-reader?') ? url.split('/').at(-2) : endpoint))
      if (request && endpoint.startsWith('draft-reader?')) {
        const detail = draftDetail(request.id, request.input.revision_of_request_id ?? null)
        const scoped = {...detail, target_sections:request.input.target_sections}
        if ('draft_advice' in request.input && request.input.draft_advice === true) {
          return Response.json({...scoped, draft:null, changes:[], can_revise:false, draft_advice:true,
            advice:'先概括主要结论，再保留一句局限说明。'})
        }
        if (!chapters) return Response.json(scoped)
        return Response.json({...scoped, can_revise:request.published_revision === null, editable_section_ids:[methods.id, conclusion.id],
          draft:{...detail.draft, sections:chapters.map(chapter => ({...chapter, heading:chapter.title, groups:[],
            paragraphs:chapter.purpose === 'references' ? [] : [{id:chapter.id + ':1', parts:[{text:chapter.title + ' prose', citations:[]}]}]}))}})
      }
      if (request) return Response.json({...request, task:{...request.task, status:'succeeded'}, candidate:original.candidate})
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
      const id = `w${records.length + 1}`
      const item = {...liveRequest, id, task: {...liveRequest.task, id, status: 'queued' as const},
        input: bundle.request_json, execution: body, candidate: null}
      records.push(item)
      if (lost) throw new Error('lost receipt')
      return Response.json(item)
    }
    throw new Error(url)
  }))
  return {posts, reads, records, input: () => bundle.request_json}
}

it('shows author fields and manuscript sections without the template banner', async () => {
  const api = server()
  const fallback = globalThis.fetch
  const detail = draftDetail('w1', null)
  const draft = detail.draft!
  const titleFields = ['Author list', 'Author affiliations and footnotes', 'Contact information']
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/w1/draft-reader?revision=1')) {
      return Response.json({...detail, draft: {...draft, sci_template_name:'Cell Press 风格研究论文',
        title_fields:titleFields, keywords:['observations'], sections:[draft.sections[0],
          {id:'abstract', heading:'Summary', level:1, groups:[],
            paragraphs:[{id:'summary-p', parts:[{text:'Existing abstract.', citations:[]}]}]}, ...draft.sections.slice(1)]}})
    }
    return fallback(url, init)
  }))
  render(<SciDraftRevision {...props}/>)
  const preview = within(screen.getByRole('region', {name:'稿件预览'}))
  const title = await preview.findByRole('heading', {name:'Original draft'})
  expect(preview.queryByText('Cell Press 风格研究论文')).toBeNull()
  const entries = [title, ...titleFields.map(label => preview.getByText(label)),
    preview.getByRole('heading', {name:'Summary'}), preview.getByText(/observations/),
    preview.getByRole('heading', {name:'Discussion'})]
  entries.slice(1).forEach((entry, index) => {
    expect(entries[index].compareDocumentPosition(entry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
  fireEvent.click(screen.getByRole('button', {name:'多选章节'}))
  expect(preview.queryByRole('checkbox', {name:'选择 Author list'})).toBeNull()
  expect(preview.getByRole('checkbox', {name:'选择 Discussion'})).toBeTruthy()
  expect(api.posts).toEqual([])
})

it('uses the shared thesis chat to upload, revise chapters, ask advice and follow up while retaining the school protocol', async () => {
  const api = server(false, school)
  const adjust = vi.fn()
  render(<SciDraftRevision {...props} thesis onAdjustSources={adjust}/>)
  await screen.findByRole('heading', {name:'Original draft'})
  expect(screen.getByRole('region', {name:'修改对话'})).toBeTruthy()
  expect(screen.queryByRole('checkbox')).toBeNull()
  const upload = screen.getByLabelText('上传意见文件')
  fireEvent.change(upload, {target:{files:[new File(['image'], 'requirements.png')]}})
  expect(screen.getByRole('alert').textContent).toContain('意见文件')
  fireEvent.change(upload, {target:{files:[new File(['word'], 'requirements.docx')]}})
  await screen.findByDisplayValue('Review the uploaded comparison.')
  expect(screen.getByText('全文（按意见文件）')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', {name:'多选章节'}))
  expect(screen.queryByRole('checkbox', {name:'选择 Reference list'})).toBeNull()
  fireEvent.click(screen.getByRole('checkbox', {name:'选择 Study conclusions'}))
  function send(message: string) {
    fireEvent.change(screen.getByRole('textbox', {name:'修改意见'}), {target:{value:message}})
    fireEvent.click(screen.getByRole('button', {name:'发送修改意见'}))
  }
  send('Explain the selected school chapters.')
  await screen.findByRole('heading', {name:'Revised draft w2'})
  expect(api.input()).toEqual({...school.input, revision_of_request_id:'w1', instructions:'Explain the selected school chapters.',
    target_sections:[methods.id, conclusion.id]})

  fireEvent.click(screen.getByRole('button', {name:'取消多选'}))
  send('研究方法怎么写？')
  await screen.findByText('先概括主要结论，再保留一句局限说明。')
  expect(api.input()).toMatchObject({revision_of_request_id:'w2', schema_version:3, draft_advice:true, target_sections:[methods.id]})
  expect(screen.getByRole('heading', {name:'Revised draft w2'})).toBeTruthy()
  send('按这个改')
  await screen.findByRole('heading', {name:'Revised draft w4'})
  expect(api.input()).toMatchObject({revision_of_request_id:'w2', schema_version:3, target_sections:[methods.id]})
  expect(api.input()).not.toHaveProperty('draft_advice')
  expect(api.input().instructions).toContain('先概括主要结论，再保留一句局限说明。')
  expect(screen.queryByRole('link', {name:'阅读修改前的全文'})).toBeNull()
  expect(screen.getByRole('link', {name:'按学校模板下载 Word'}).getAttribute('href')).toContain('/w4/draft-reader/word?revision=1')
  fireEvent.click(screen.getByRole('button', {name:'调整所选文献'}))
  expect(adjust).toHaveBeenCalledOnce()
})

it('recovers an unscoped thesis receipt created by the previous revision form', async () => {
  const attemptKey = 'legacy-thesis-attempt'
  const feedback = 'Keep the comparison concise.'
  sessionStorage.setItem(sessionKey(), JSON.stringify({feedback, attemptKey}))
  const api = server(false, school)
  api.records.push({...school, id:'w2', task:{...school.task, id:'w2'},
    input:{...school.input, revision_of_request_id:'w1', instructions:feedback},
    execution:{authorization_id:'auth1', bundle_id:'b1', logical_task_id:await jsonDigest(['paper-draft', 'p1', 'm1', attemptKey])}})
  render(<SciDraftRevision {...props} thesis/>)
  await screen.findByRole('heading', {name:'Original draft'})
  fireEvent.click(screen.getByRole('button', {name:'查看提交结果'}))
  await screen.findByRole('heading', {name:'Revised draft w2'})
  expect(api.posts).toEqual([])
  expect(screen.getByRole('link', {name:'按学校模板下载 Word'}).getAttribute('href')).toContain('/w2/draft-reader/word?revision=1')
})

it('keeps thesis editing disabled while generating and for a read-only completed draft', async () => {
  server(false, {...school, published_revision:2})
  const fetcher = vi.mocked(fetch)
  let generating = true
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => generating && url.includes('/w1/draft-reader')
    ? Response.json(draftDetail('w1', null, 'running')) : fetcher(url, init)))
  render(<SciDraftRevision {...props} thesis/>)
  await screen.findByText('正在生成正文，完成后将自动显示。')
  expect(screen.getByRole('textbox', {name:'修改意见'})).toHaveProperty('disabled', true)
  expect(screen.queryByText('你希望怎么修改这部分？')).toBeNull()
  generating = false
  fireEvent.click(screen.getByRole('button', {name:'重新读取'}))
  await screen.findByRole('heading', {name:'Original draft'})
  expect(screen.getByRole('button', {name:'发送修改意见'})).toHaveProperty('disabled', true)
  expect(screen.getByRole('link', {name:'按学校模板下载 Word'})).toBeTruthy()
})

it('uses the active thesis abstract for a generic request and both for an explicitly bilingual request', () => {
  const abstracts = [
    {id:'chapter-zh', heading:'摘要', purpose:'abstract', output_language:'zh-CN' as const},
    {id:'chapter-en', heading:'Abstract', purpose:'abstract', output_language:'en' as const},
  ]
  const scope = {thesis:true, active:'chapter-en'}
  expect(resolveDraftChat('修改摘要', abstracts, scope).sectionIds).toEqual(['chapter-en'])
  expect(resolveDraftChat('修改中文摘要和英文摘要', abstracts, scope).sectionIds).toEqual(['chapter-zh', 'chapter-en'])
})

it('sends SCI feedback directly and bases the next message on the completed revision', async () => {
  const api = server()
  render(<SciDraftRevision {...props} onAdjustSources={vi.fn()}/>)
  await screen.findByRole('heading', {name:'Original draft'})
  fireEvent.change(screen.getByLabelText('上传意见文件'), {target: {files: [new File(['word'], 'opinion.docx')]}})
  const box = await screen.findByDisplayValue('Review the uploaded comparison.')
  expect(screen.getByText('全文（按意见文件）')).toBeTruthy()
  fireEvent.change(box, {target: {value: 'Clarify the control group.'}})
  expect(api.posts).toEqual(['draft-feedback'])
  expect(screen.queryByRole('checkbox')).toBeNull()
  const send = screen.getByRole('button', {name:'发送修改意见'})
  expect(send).toHaveProperty('disabled', false)
  fireEvent.click(send)
  fireEvent.click(send)
  await screen.findByRole('heading', {name:'Revised draft w2'})
  const chat = within(screen.getByRole('log', {name:'修改记录'}))
  expect(chat.getByText('Clarify the control group.')).toBeTruthy()
  expect(chat.getByText('Before w2')).toBeTruthy()
  expect(chat.getByText('After w2')).toBeTruthy()
  expect(chat.queryByRole('link', {name:'阅读修改前的全文'})).toBeNull()
  expect(screen.queryByText('查看修改处')).toBeNull()
  const word = screen.getByRole('link', {name:'下载 Word'})
  expect(word.getAttribute('href')).toContain('/writing-requests/w2/draft-reader/word?revision=1')
  expect(word.closest('header')?.textContent).toContain('调整所选文献下载 Word')
  expect(api.input()).toMatchObject({revision_of_request_id: 'w1', instructions: 'Clarify the control group.',
    selected_source_ids: ['sourceA'], selected_evidence_ids: ['evidenceA'], target_sections:['title', 'discussion', 'conclusion']})
  expect(api.posts).toEqual(['draft-feedback', 'writing-previews', 'writing-authorizations', 'writing-requests'])
  fireEvent.change(screen.getByRole('textbox', {name:'修改意见'}), {target:{value:'Shorten the discussion.'}})
  fireEvent.click(screen.getByRole('button', {name:'发送修改意见'}))
  await screen.findByRole('heading', {name:'Revised draft w3'})
  expect(api.input()).toMatchObject({revision_of_request_id:'w2', instructions:'Shorten the discussion.'})
  expect(chat.getByText('Before w2')).toBeTruthy()
  expect(chat.getByText('After w3')).toBeTruthy()
  expect(screen.queryByRole('button', {name:'返回正文'})).toBeNull()
})

it('follows the preview midpoint and lets one button start and cancel multi-selection', async () => {
  const api = server()
  render(<SciDraftRevision {...props}/>)
  const title = (await screen.findByRole('heading', {name:'Original draft'})).closest('section')!
  const discussion = screen.getByRole('heading', {name:'Discussion'}).closest('section')!
  const conclusion = screen.getByRole('heading', {name:'Conclusion'}).closest('section')!
  const preview = title.closest<HTMLElement>('.sci-revision-scroll')!
  Object.defineProperty(preview, 'clientHeight', {value:400})
  Object.defineProperty(preview, 'scrollHeight', {value:1200})
  expect(title.hasAttribute('data-sci-revision-selected')).toBe(true)
  preview.scrollTop = 200
  vi.spyOn(title, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, -50, 500, 180))
  vi.spyOn(discussion, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 130, 500, 260))
  vi.spyOn(conclusion, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 390, 500, 420))
  fireEvent.scroll(preview)
  expect(discussion.hasAttribute('data-sci-revision-selected')).toBe(true)
  expect(screen.getByText('目前修改范围：').parentElement?.textContent).toContain('Discussion')
  fireEvent.click(screen.getByRole('button', {name:'多选章节'}))
  fireEvent.click(screen.getByRole('checkbox', {name:'选择 Conclusion'}))
  const cancel = screen.getByRole('button', {name:'取消多选'})
  expect(screen.queryByRole('button', {name:'完成选择'})).toBeNull()
  expect(screen.queryByRole('button', {name:'跟随正文'})).toBeNull()
  const feedback = screen.getByRole('textbox', {name:'修改意见'})
  fireEvent.change(feedback, {target:{value:'Clarify these sections.'}})
  preview.scrollTop = 800
  fireEvent.scroll(preview)
  expect(discussion.hasAttribute('data-sci-revision-selected')).toBe(true)
  expect(conclusion.hasAttribute('data-sci-revision-selected')).toBe(true)
  fireEvent.click(cancel)
  expect(discussion.hasAttribute('data-sci-revision-selected')).toBe(false)
  expect(conclusion.hasAttribute('data-sci-revision-selected')).toBe(true)
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect(feedback).toHaveProperty('value', 'Clarify these sections.')
  fireEvent.click(screen.getByRole('button', {name:'多选章节'}))
  fireEvent.click(screen.getByRole('checkbox', {name:'选择 Discussion'}))
  fireEvent.click(screen.getByRole('button', {name:'发送修改意见'}))
  await screen.findByRole('heading', {name:'Revised draft w2'})
  expect(api.input()).toMatchObject({target_sections:['discussion', 'conclusion'], instructions:'Clarify these sections.'})
})

it('routes named chapters, follow-ups and advice through the correct draft and scope', async () => {
  const api = server()
  render(<SciDraftRevision {...props}/>)
  await screen.findByRole('heading', {name:'Original draft'})
  const preview = within(screen.getByRole('region', {name:'稿件预览'}))
  function send(message: string) {
    fireEvent.change(screen.getByRole('textbox', {name:'修改意见'}), {target:{value:message}})
    fireEvent.click(screen.getByRole('button', {name:'发送修改意见'}))
  }
  send('重写结论')
  await screen.findByRole('heading', {name:'Revised draft w2'})
  expect(api.input()).toMatchObject({revision_of_request_id:'w1', target_sections:['conclusion']})
  expect(screen.getByText('我会修改 Conclusion。')).toBeTruthy()
  fireEvent.click(preview.getByRole('heading', {name:'Discussion'}))
  send('再短一点')
  await screen.findByRole('heading', {name:'Revised draft w3'})
  expect(api.input()).toMatchObject({revision_of_request_id:'w2', target_sections:['conclusion']})
  fireEvent.click(preview.getByRole('heading', {name:'Discussion'}))
  send('这段有什么问题？')
  await screen.findByText('先概括主要结论，再保留一句局限说明。')
  expect(api.input()).toMatchObject({revision_of_request_id:'w3', draft_advice:true, target_sections:['discussion']})
  expect(screen.getByRole('heading', {name:'Revised draft w3'})).toBeTruthy()
  send('按这个改')
  await screen.findByRole('heading', {name:'Revised draft w5'})
  expect(api.input()).toMatchObject({revision_of_request_id:'w3', target_sections:['discussion']})
  expect(api.input()).not.toHaveProperty('draft_advice')
  expect(api.input().instructions).toContain('先概括主要结论，再保留一句局限说明。')
})

it('reveals received text in small steps and replaces it with the verified revision', async () => {
  vi.useFakeTimers()
  sessionStorage.setItem(sessionKey(),
    JSON.stringify({feedback:'Clarify the results.', attemptKey:'known-attempt', createdId:'w2', submittedSections:['discussion']}))
  let reads = 0
  const first = 'First streamed paragraph fragment'
  const extended = first + ' with more text from the model.'
  const fetcher = vi.fn(async (url: string) => {
    if (url.includes('/w1/draft-reader')) return Response.json(draftDetail('w1', null))
    if (!url.includes('/w2/draft-reader')) throw new Error(url)
    reads += 1
    if (reads === 1) return Response.json(draftDetail('w2', 'w1', 'queued'))
    if (reads === 2) return Response.json({}, {status:503})
    if (reads === 3) return Response.json({...draftDetail('w2', 'w1', 'running'),
      target_sections:['discussion'], partial_reply:[]})
    if (reads === 4 || reads === 5) return Response.json({...draftDetail('w2', 'w1', 'running'),
      target_sections:['discussion'], partial_reply:[{section_id:'discussion', text:reads === 4 ? first : extended}]})
    return Response.json(draftDetail('w2', 'w1'))
  })
  vi.stubGlobal('fetch', fetcher)
  render(<SciDraftRevision {...props}/>)
  await act(() => vi.advanceTimersByTimeAsync(0))
  const log = screen.getByRole('log', {name:'修改记录'})
  const chat = within(log)
  const previewText = () => log.querySelector('.sci-revision-preview-reply p')?.textContent ?? ''
  expect(chat.getByText('修改稿已排队。')).toBeTruthy()
  await act(() => vi.advanceTimersByTimeAsync(999))
  expect(reads).toBe(1)
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(reads).toBe(2)
  await act(() => vi.advanceTimersByTimeAsync(1))
  expect(chat.getByText('正在按意见修改初稿……').closest('.sci-revision-reply')).toBeTruthy()
  await act(() => vi.advanceTimersByTimeAsync(399))
  expect(reads).toBe(3)
  await act(() => vi.advanceTimersByTimeAsync(1))
  expect(reads).toBe(4)
  await act(() => vi.advanceTimersByTimeAsync(128))
  expect(previewText()).toMatch(/^F/)
  expect(first.startsWith(previewText())).toBe(true)
  expect(previewText().length).toBeLessThan(first.length)
  expect(chat.queryByRole('button', {name:'重新读取'})).toBeNull()
  expect(screen.getByRole('heading', {name:'Original draft'})).toBeTruthy()
  await act(() => vi.advanceTimersByTimeAsync(804))
  expect(previewText()).toBe(first)
  expect(reads).toBe(4)
  Object.defineProperties(log, {scrollHeight:{value:900}, clientHeight:{value:300}})
  log.scrollTop = 100
  fireEvent.scroll(log)
  await act(() => vi.advanceTimersByTimeAsync(68))
  await act(() => vi.advanceTimersByTimeAsync(128))
  expect(previewText()).toContain(first)
  expect(previewText().length).toBeGreaterThan(first.length)
  expect(previewText().length).toBeLessThan(extended.length)
  expect(log.scrollTop).toBe(100)
  await act(() => vi.advanceTimersByTimeAsync(872))
  expect(screen.getByRole('heading', {name:'Revised draft w2'})).toBeTruthy()
  expect(chat.getByText('After w2')).toBeTruthy()
  expect(previewText()).toBe('')
  await act(() => vi.advanceTimersByTimeAsync(30000))
  expect(reads).toBe(6)
  expect(fetcher).toHaveBeenCalledTimes(7)
})

it('loads scoped submission data in parallel and restores a lost receipt after reload', async () => {
  const api = server(true)
  const fetcher = vi.mocked(fetch)
  let releaseParent = () => {}
  const waitingForParent = new Promise<void>(resolve => {releaseParent = resolve})
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/writing-requests/w1')) await waitingForParent
    return fetcher(url, init)
  }))
  const first = render(<SciDraftRevision {...props}/>)
  await screen.findByRole('heading', {name:'Original draft'})
  fireEvent.change(screen.getByRole('textbox', {name:'修改意见'}), {target: {value: 'Explain the controls.'}})
  fireEvent.click(screen.getByRole('button', {name:'发送修改意见'}))
  try {
    await waitFor(() => expect(api.reads).toContain('writing-previews?capabilities_only=true'))
    expect(api.reads).not.toContain('writing-requests')
    expect(api.reads).not.toContain('writing-previews')
    expect(api.posts).toEqual([])
  } finally {releaseParent()}
  await screen.findByRole('alert')
  first.unmount()
  render(<SciDraftRevision {...props}/>)
  const log = within(screen.getByRole('log', {name:'修改记录'}))
  fireEvent.click(log.getByRole('button', {name:'查看提交结果'}))
  await screen.findByRole('heading', {name:'Revised draft w2'})
  expect(api.reads.filter(endpoint => endpoint === 'writing-requests')).toHaveLength(1)
  expect(api.posts).toEqual(['writing-previews', 'writing-authorizations', 'writing-requests'])
})
