import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import CustomerWorkspace from './CustomerWorkspace'
import { exportFixture, manuscriptFixture } from '../manuscripts/manuscriptFixtures'
import type { ThesisSection } from './thesisProjectRequirements'

vi.mock('./SciDraftReader', () => ({ SciDraftReader: (p: { requestId: string }) => <p>Read {p.requestId}</p> }))
vi.mock('./SciDraftRevision', () => ({ SciDraftRevision: (p: { requestId: string }) =>
  <section aria-label="修改对话">{p.requestId}</section> }))
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
const thesisChapter = {id:'thesis:results:school-confirmed:results', label:'观察结果'}
const thesisFigure = {id:'saved-figure', title:'登记流程正图', revision:1,
  preview_url:'/api/v1/projects/p1/thesis-figures/saved-figure/members/png/download'}

function open(projectType: 'sci' | 'thesis', params: Record<string, string>, review = false, thesisFigures?: boolean) {
  const project = { id: 'p1', name: 'Test', project_type: projectType, research_topic: 'Topic', file_count: 0,
    created_at: '2026-11-22T10:00:00Z', updated_at: '2026-11-22T10:00:00Z' }
  const template = {id:'frontiers-genetics-research-v1', name:'Frontiers in Genetics · Original Research', article_type:review?'narrative_review':'research',
    source_url:'https://www.frontiersin.org/journals/genetics/for-authors/article-types', sections:[
      {id:'title',en:'Title',zh:'标题'},{id:'abstract',en:'Abstract',zh:'摘要'},{id:'introduction',en:'Introduction',zh:'引言'},
      {id:'materials_and_methods',en:'Materials and Methods',zh:'材料与方法'},{id:'results',en:'Results',zh:'结果'},
      {id:'discussion',en:'Discussion',zh:'讨论'},{id:'references',en:'References',zh:'参考文献'},
    ]}
  if (review) template.sections.splice(3, 3,
    {id:'literature_scope', en:'Literature scope', zh:'文献范围'},
    {id:'themes', en:'Thematic synthesis', zh:'主题综合'},
    {id:'discussion', en:'Discussion', zh:'讨论'},
    {id:'conclusion', en:'Conclusion', zh:'结论'})
  const [title, abstract, introduction, methods, results, discussion, references] = template.sections
  const templates = review ? [template] : [template, {
    ...template, id:'cell-press-research-v1', name:'Cell Press 风格研究论文',
    source_url:'https://www.cell.com/information-for-authors/article-templates',
    format_guide:{
      notes:{abstract:'英文摘要写成单段，最多 150 词。', results:'结果用简短小标题写出具体发现。'},
      title_fields:[
        {en:'Author list', zh:'作者名单', note:'按实际署名顺序列出全名。'},
        {en:'Author affiliations and footnotes', zh:'作者单位与脚注', note:'用编号脚注标明单位。'},
        {en:'Contact information', zh:'联系信息', note:'注明通讯作者邮箱。'},
      ],
      keywords:{en:'Keywords', zh:'关键词', note:'沿用建项资料，置于摘要之后。'},
      optional_sections:[
        {after:'introduction', section:{id:'sci-section-7c23e73a64d84b71a88c8444e7f5bbba', en:'Design', zh:'设计'},
          note:'仅 Technology 稿件使用。'},
        {after:'materials_and_methods', section:{id:'sci-section-c41b92f76ae04de5b336ed8f2988b42a',
          en:'Supplemental information', zh:'补充材料'}, note:'有补充文件时添加。'},
      ],
    },
    sections:[title, {...abstract, en:'Summary'}, introduction, results, discussion, methods, references],
  }]
  let selected: string | null = null
  let selectedSections: typeof template.sections | null = null
  let combinesReviewTopics = false
  let figureWorkflow = false
  let thesisRevision = 1
  let thesisSections: ThesisSection[] = []
  let thesisPlacements: {figure_id:string; chapter_id:string; caption:string}[] = []
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/v1/projects/p1') return Response.json(project)
    if (url.includes('/files?')) return Response.json({items:[], total:0, page:1, page_size:5})
    if (url.includes('/paper-materials')) return Response.json({items:[],targets:[]})
    if (url.includes('-figures/assembly?')) {
      const empty = {items:[], total:0, page:1, page_size:20}
      return Response.json({available:empty, groups:empty, has_pending:false})
    }
    if (url.includes('/sci-figures?')) return Response.json({items:[], total:0, page:1, page_size:20})
    if (url.includes('/thesis-figures?')) return Response.json({total:thesisFigures ? 1 : 0, page:1, page_size:20,
      items:thesisFigures ? [{...thesisFigure, root_id:thesisFigure.id, latest_revision:thesisFigure.revision,
        config:{title:thesisFigure.title}, task:{status:'succeeded'}}] : []})
    if (url.endsWith('/sci-resources')) return Response.json({revision:0, template_id:selected, chapters:[], figures:[], placements:[]})
    if (url.endsWith('/thesis-figure-resources')) {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        if (body.expected_revision !== thesisRevision) return Response.json({detail:{code:'thesis_requirements_changed'}}, {status:409})
        thesisPlacements = body.placements
        thesisRevision += 1
      }
      return Response.json({revision:thesisRevision, template_id:'school-confirmed',
        chapters:[thesisChapter], figures:thesisFigures ? [thesisFigure] : [], placements:thesisPlacements})
    }
    if (url.endsWith('/sci-template')) {
      if (init?.method === 'PUT') {
        const input = JSON.parse(String(init.body))
        selected = input.template_id
        selectedSections = input.sections
        combinesReviewTopics = input.combine_review_topics === true
        figureWorkflow = input.figure_workflow === true
      }
      return Response.json({revision:selected ? 2 : 1, article_type:template.article_type, selected_template_id:selected,
        selected_sections:selectedSections, templates, combine_review_topics:combinesReviewTopics, figure_workflow:figureWorkflow,
        review_headings:review?[{id:'topic', heading:'单细胞'}]:[]})
    }
    if (url.includes('/sci-current-draft')) return Response.json({ draft: { manuscript_id: 'paper', revision: 4, request_id: 'original' } })
    if (url.endsWith('/draft-history')) return Response.json({items:[{manuscript_id:'paper', revision:2,
      request_id:'previous', title:'Previous thesis', created_at:'2026-11-22T10:00:00Z', previous_request_id:null}]})
    if (url.endsWith('/manuscripts')) return Response.json({items:[]})
    if (url.endsWith('/manuscripts/m1/versions/1')) return Response.json(manuscriptFixture.versions[0])
    if (url.endsWith('/sci-settings')) return Response.json({ settings: null })
    if (url.endsWith('/thesis-requirements')) {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        if (body.expected_revision !== thesisRevision) return Response.json({detail:{code:'thesis_requirements_changed'}}, {status:409})
        thesisSections = body.chapter_plan.sections
        thesisRevision += 1
      }
      return Response.json({title:'Thesis', language:'zh-CN', revision:thesisRevision, keywords:['cohort','survey','register','results'], sections:thesisSections,
        education_level:'本科', school:'示例大学', template:thesisFigures !== undefined ?
          {name:'学校目录', confirmation_id:'school-confirmed', chapters:[{id:'results', title:thesisChapter.label, level:1}]} : null})
    }
    return Response.json({})
  })
  vi.stubGlobal('fetch', fetch)
  const hash = new URLSearchParams({ 'customer-project': project.id, ...params })
  window.history.replaceState(null, '', '#' + hash.toString())
  render(<CustomerWorkspace />)
  return fetch
}

function pointer(element: HTMLElement, type: string, clientY: number) {
  const event = new MouseEvent(type, {bubbles:true, cancelable:true, button:0, clientY})
  Object.defineProperty(event, 'pointerId', {value:1})
  fireEvent(element, event)
}

it('keeps a saved thesis search in the fifth step and opens its exact generated request', async () => {
  open('thesis', { step:'materials', view:'list', search:'search1', paragraph:'old:3' })
  const nav = await screen.findByRole('navigation', {name:'项目操作步骤'})
  expect([...nav.querySelectorAll('button')].map(b => b.textContent)).toEqual(['1项目资料','2上传资料','3图件拼版','4模板与资料整理','5文献与初稿'])
  fireEvent.click(await screen.findByRole('button', {name:'生成毕业论文初稿 search1'}))
  expect((await screen.findByRole('region', {name:'修改对话'})).textContent).toBe('writing2')
  const params = new URLSearchParams(location.hash.slice(1))
  expect(params.get('step')).toBe('manuscripts')
  expect(params.has('paragraph')).toBe(false)
  expect(params.has('search')).toBe(false)
})

it('opens thesis figure assembly and saves a formal figure in the school organizer', async () => {
  const fetch = open('thesis', {step:'materials'}, false, true)
  fireEvent.click(await screen.findByRole('button', {name:'下一步 图件拼版'}))
  await screen.findByRole('button', {name:'第 3 步：图件拼版', current:'step'})
  expect(new URLSearchParams(location.hash.slice(1)).get('step')).toBe('thesis-figures')
  fireEvent.click(screen.getByRole('button', {name:'已保存正图'}))
  await screen.findByRole('button', {name:/登记流程正图.*已完成/})
  expect(fetch.mock.calls.some(([url]) => url.includes('/thesis-figures?'))).toBe(true)

  fireEvent.click(screen.getByRole('button', {name:'下一步 模板与资料整理'}))
  await screen.findByRole('button', {name:'第 4 步：模板与资料整理', current:'step'})
  await screen.findByRole('heading', {name:'已采用学校模板 · 学校目录'})
  expect(screen.queryByRole('combobox', {name:'入稿章节 登记流程正图'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'图件配置'}))
  const chapter = await screen.findByRole('combobox', {name:'入稿章节 登记流程正图'})
  fireEvent.change(chapter, {target:{value:thesisChapter.id}})
  fireEvent.change(screen.getByRole('textbox', {name:'图注 登记流程正图'}), {target:{value:'登记与核对流程。'}})
  fireEvent.click(screen.getByRole('button', {name:'保存资源配置'}))
  await waitFor(() => expect(chapter).toHaveProperty('disabled', false))
  expect(screen.getByRole('button', {name:'保存资源配置'})).toHaveProperty('disabled', true)
  const writes = fetch.mock.calls.filter(([, init]) => init?.method === 'PUT')
  expect(writes).toHaveLength(1)
  expect(writes[0][0]).toBe('/api/v1/projects/p1/thesis-figure-resources')
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({expected_revision:1,
    placements:[{figure_id:thesisFigure.id, chapter_id:thesisChapter.id, caption:'登记与核对流程。'}]})
  expect(fetch.mock.calls.some(([url]) => url.includes('/sci-figures') || url.endsWith('/sci-resources'))).toBe(false)

  fireEvent.click(screen.getByRole('button', {name:'下一步 文献与初稿'}))
  await screen.findByRole('button', {name:'第 5 步：文献与初稿', current:'step'})
  expect(fetch.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)
})

it('keeps thesis figure configuration optional when there are no formal figures', async () => {
  const fetch = open('thesis', {step:'school'}, false, false)
  await screen.findByText('已采用学校模板 · 学校目录')
  fireEvent.click(screen.getByRole('button', {name:'图件配置'}))
  await screen.findByText('暂无可配置的正图。')
  expect(screen.queryByRole('button', {name:'保存资源配置'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'下一步 文献与初稿'}))
  await screen.findByRole('button', {name:'第 5 步：文献与初稿', current:'step'})
  expect(fetch.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(0)
})

it('uses the latest profile revision when alternating thesis figure and chapter saves', async () => {
  const fetch = open('thesis', {step:'school'}, false, true)
  await screen.findByRole('heading', {name:'已采用学校模板 · 学校目录'})
  fireEvent.click(screen.getByRole('button', {name:'图件配置'}))
  const chapter = await screen.findByRole('combobox', {name:'入稿章节 登记流程正图'})
  fireEvent.change(chapter, {target:{value:thesisChapter.id}})
  fireEvent.change(screen.getByRole('textbox', {name:'图注 登记流程正图'}), {target:{value:'初始图注。'}})
  fireEvent.click(screen.getByRole('button', {name:'保存资源配置'}))
  await waitFor(() => expect(fetch.mock.calls.filter(([url, init]) => url.endsWith('/thesis-requirements') && init?.method !== 'PUT')).toHaveLength(2))

  fireEvent.click(screen.getByRole('button', {name:'学校模板'}))
  const purpose = await screen.findByRole('combobox', {name:'章节用途'})
  await waitFor(() => expect(purpose.matches(':disabled')).toBe(false))
  fireEvent.change(purpose, {target:{value:'results'}})
  fireEvent.change(screen.getByRole('textbox', {name:'章节内容'}), {target:{value:'报告已核对结果。'}})
  fireEvent.click(screen.getByRole('button', {name:'资料整理'}))
  expect(screen.queryByRole('textbox', {name:'章节内容'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'学校模板'}))
  expect(screen.getByRole('textbox', {name:'章节内容'})).toHaveProperty('value', '报告已核对结果。')
  fireEvent.click(screen.getByRole('button', {name:'保存章节内容'}))
  await screen.findByText('章节内容已保存。')
  await waitFor(() => expect(fetch.mock.calls.filter(([url, init]) => url.endsWith('/thesis-figure-resources') && init?.method !== 'PUT')).toHaveLength(2))

  fireEvent.click(screen.getByRole('button', {name:'图件配置'}))
  const caption = screen.getByRole('textbox', {name:'图注 登记流程正图'})
  await waitFor(() => expect(caption).toHaveProperty('disabled', false))
  fireEvent.change(caption, {target:{value:'核对后的图注。'}})
  fireEvent.click(screen.getByRole('button', {name:'保存资源配置'}))
  await waitFor(() => expect(caption).toHaveProperty('disabled', false))
  expect(screen.getByRole('button', {name:'保存资源配置'})).toHaveProperty('disabled', true)
  expect(fetch.mock.calls.filter(([, init]) => init?.method === 'PUT').map(([,init]) =>
    JSON.parse(String(init?.body)).expected_revision)).toEqual([1,2,3])
})

it.each([{step:'word'}, {step:'manuscripts', view:'feedback'}])('opens the fixed thesis chat from a legacy $step $view bookmark', async ({step, view}) => {
  open('thesis', {step, ...(view ? {view} : {}), manuscript:'paper', revision:'2', writingRequest:'previous'})
  expect((await screen.findByRole('region', {name:'修改对话'})).textContent).toBe('previous')
  expect(screen.getByRole('button', {name:'第 5 步：文献与初稿', current:'step'})).toBeTruthy()
  expect(new URLSearchParams(location.hash.slice(1)).get('writingRequest')).toBe('previous')
})

it('pins the current thesis conversation and keeps history navigation on the selected version', async () => {
  open('thesis', {step:'manuscripts'})
  expect((await screen.findByRole('region', {name:'修改对话'})).textContent).toBe('original')
  await waitFor(() => expect(location.hash).toContain('writingRequest=original'))
  fireEvent.click(screen.getByRole('button', {name:'历史版本'}))
  await screen.findByText('Previous thesis')
  expect(screen.queryByRole('region', {name:'修改对话'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'查看这版正文'}))
  expect((await screen.findByRole('region', {name:'修改对话'})).textContent).toBe('previous')
})

it('still resolves a bookmarked saved thesis Word export', async () => {
  open('thesis', {step:'word', manuscript:'m1', revision:'1'})
  const word = await screen.findByRole('link', {name:exportFixture.filename})
  expect(word.getAttribute('href')).toBe(exportFixture.download_url)
  expect(screen.queryByRole('region', {name:'修改对话'})).toBeNull()
})

it.each(['journals', 'word', 'reviews', 'manuscripts'])('opens the current SCI draft and chat directly from %s', async step => {
  open('sci', { step })
  expect((await screen.findByRole('region', {name:'修改对话'})).textContent).toBe('original')
  const nav = screen.getByRole('navigation', { name: '项目操作步骤' })
  expect([...nav.querySelectorAll('button')].map(b => b.textContent)).toEqual(['1项目资料', '2上传资料', '3图件拼版', '4模板设定和资源配置', '5文献与初稿'])
  expect(screen.queryByText('Read original')).toBeNull()
  await waitFor(() => expect(location.hash).toContain('writingRequest=original'))
})

it('shows the full Cell Press outline without writing tips and adds optional sections on request', async () => {
  const fetch = open('sci', {step:'sci-template'})
  const picker = await screen.findByRole('combobox', {name:'SCI 模板'})
  expect(screen.queryByText('作者名单')).toBeNull()
  fireEvent.change(picker, {target:{value:'cell-press-research-v1'}})
  const list = screen.getByRole('list', {name:'稿件结构'})
  const rows = [...list.querySelectorAll('.sci-template-section-row')]
  expect(rows.map(row => {
    const english = row.querySelector('[lang="en"]')
    return english instanceof HTMLTextAreaElement ? english.value : english?.textContent
  })).toEqual([
    'Title','Author list','Author affiliations and footnotes','Contact information','Summary','Keywords',
    'Introduction','Design','Results','Discussion','Materials and Methods','Supplemental information','References',
  ])
  expect(list.querySelector('p')).toBeNull()
  expect(within(list).getAllByText('在 Word 填写')).toHaveLength(3)

  const handle = screen.getByRole('button', {name:'拖动 摘要'})
  const methods = screen.getByRole('button', {name:'拖动 材料与方法'})
  const methodGroup = methods.closest('li')!
  const discussionGroup = screen.getByRole('button', {name:'拖动 讨论'}).closest('li')!
  const summaryGroup = handle.closest('li')!
  expect(within(methodGroup).getByText('Supplemental information')).toBeTruthy()
  expect(within(summaryGroup).getByText('Keywords')).toBeTruthy()
  let top = 0
  for (const group of list.children) {
    const height = group.children.length * 50
    vi.spyOn(group, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, top, 760, height))
    top += height
  }
  for (const grip of [methods, handle]) Object.defineProperty(grip, 'setPointerCapture', {value:vi.fn()})

  const methodsStart = methodGroup.getBoundingClientRect().top + 25
  pointer(methods, 'pointerdown', methodsStart)
  pointer(methods, 'pointermove', methodsStart - 12)
  expect([...list.querySelectorAll('[data-dragging]')]).toEqual([methodGroup])
  expect(methodGroup.style.transform).toBe('')
  pointer(methods, 'pointermove', methodsStart - 35)
  expect(methodGroup.style.transform).toBe('translateY(-50px)')
  expect(discussionGroup.style.transform).toBe('translateY(100px)')
  pointer(methods, 'pointercancel', methodsStart - 35)

  pointer(handle, 'pointerdown', 225)
  pointer(handle, 'pointermove', 340)
  expect(summaryGroup.style.transform).toBe('translateY(100px)')
  pointer(handle, 'pointerup', 340)
  expect(screen.getByRole('textbox', {name:'第 5 项英文标题'})).toHaveProperty('value','Introduction')
  expect(screen.getByRole('textbox', {name:'第 7 项英文标题'})).toHaveProperty('value','Summary')
  expect(within(summaryGroup).getByText('Keywords')).toBeTruthy()
  fireEvent.keyDown(handle, {key:'ArrowUp'})

  fireEvent.click(screen.getByRole('button', {name:'添加 设计'}))
  expect(screen.getByRole('textbox', {name:'第 8 项英文标题'})).toHaveProperty('value','Design')
  expect(list.querySelector('p')).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'删除第 8 章'}))
  const introduction = screen.getByRole('button', {name:'拖动 引言'}).closest('li')!
  expect(within(introduction).getByRole('button', {name:'添加 设计'})).toBeTruthy()
  expect(screen.getByRole('textbox', {name:'第 9 项英文标题'})).toHaveProperty('value','Results')
  fireEvent.click(screen.getByRole('button', {name:'添加 补充材料'}))
  fireEvent.click(screen.getByRole('button', {name:'使用模板并继续'}))
  await screen.findByRole('heading', {name:'资源配置'})
  const save = fetch.mock.calls.find(([url, init]) => url.endsWith('/sci-template') && init?.method === 'PUT')
  const saved = JSON.parse(String(save?.[1]?.body))
  expect(saved.template_id).toBe('cell-press-research-v1')
  expect(saved.sections.map((section: {en:string}) => section.en)).toEqual([
    'Title','Summary','Introduction','Results','Discussion','Materials and Methods','Supplemental information','References',
  ])
})

it('drags editable SCI chapters around fixed endpoints and saves new chapters and levels', async () => {
  const fetch = open('sci', {step:'materials'})
  fireEvent.click(await screen.findByRole('button', {name:'下一步 图件拼版'}))
  await screen.findByRole('button', {name:'第 3 步：图件拼版', current:'step'})
  fireEvent.click(await screen.findByRole('button', {name:'下一步 模板设定和资源配置'}))
  const picker = await screen.findByRole('combobox', {name:'SCI 模板'})
  expect(within(picker).getAllByRole('option').map(option => option.textContent)).toEqual([
    'Frontiers in Genetics · Original Research', 'Cell Press 风格研究论文',
  ])
  expect(picker).toHaveProperty('value','frontiers-genetics-research-v1')
  const titleLevel = screen.getByRole('combobox', {name:'第 1 项标题级别'})
  const chapterLevel = screen.getByRole('combobox', {name:'第 2 项标题级别'})
  expect(within(titleLevel).getAllByRole('option').map(option => option.textContent)).toEqual([
    '论文标题样式', '1 级标题', '2 级标题', '3 级标题', '4 级标题', '5 级标题',
  ])
  expect(within(chapterLevel).getAllByRole('option').map(option => option.textContent)).toEqual([
    '1 级标题', '2 级标题', '3 级标题', '4 级标题', '5 级标题',
  ])
  expect(screen.getByRole('textbox', {name:'第 4 项中文标题'})).toHaveProperty('value','材料与方法')
  expect(screen.getByRole('button', {name:'标题（固定位置）'})).toHaveProperty('disabled', true)
  const references = screen.getByRole('button', {name:'参考文献（固定位置）'})
  expect(references).toHaveProperty('disabled', true)
  expect(screen.queryByRole('button', {name:/^(上移|下移)/})).toBeNull()
  fireEvent.change(screen.getByRole('textbox', {name:'第 5 项中文标题'}), {target:{value:'主要发现'}})
  fireEvent.change(screen.getByRole('textbox', {name:'第 5 项英文标题'}), {target:{value:'Principal\n findings'}})
  const handle = screen.getByRole('button', {name:'拖动 主要发现'})
  const list = screen.getByRole('list', {name:'初稿章节'})
  const heading = screen.getByRole('heading', {name:'初稿章节'})
  const addChapter = screen.getByRole('button', {name:'添加章节'})
  expect(addChapter.parentElement).toBe(heading.parentElement)
  expect(screen.queryByRole('link', {name:'查看期刊投稿指南'})).toBeNull()
  const rows = [...list.children] as HTMLElement[]
  rows.forEach((row, index) => vi.spyOn(row, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 50 * index, 760, 50)))
  Object.defineProperty(handle, 'setPointerCapture', {value:vi.fn()})
  const number = handle.nextElementSibling
  expect(number?.textContent).toBe('5.')
  expect(number?.nextElementSibling).toBe(screen.getByRole('textbox', {name:'第 5 项中文标题'}))
  pointer(handle, 'pointerdown', 225)
  pointer(handle, 'pointermove', 173)
  expect(rows[4].dataset.dragging).toBe('true')
  expect(rows[4].style.transform).toBe('translateY(-50px)')
  expect(rows[3].style.transform).toBe('translateY(50px)')
  pointer(handle, 'pointercancel', 173)
  expect(rows[4].style.transform).toBe('')
  expect(screen.getByRole('textbox', {name:'第 5 项中文标题'})).toHaveProperty('value','主要发现')
  pointer(handle, 'pointerdown', 225)
  pointer(handle, 'pointermove', 173)
  pointer(handle, 'pointerup', 173)
  expect(screen.getByRole('textbox', {name:'第 4 项中文标题'})).toHaveProperty('value','主要发现')
  fireEvent.change(screen.getByRole('combobox', {name:'第 4 项标题级别'}), {target:{value:'2'}})
  fireEvent.click(addChapter)
  expect(screen.getByRole('button', {name:'使用模板并继续'})).toHaveProperty('disabled', true)
  fireEvent.change(screen.getByRole('textbox', {name:'第 7 项中文标题'}), {target:{value:'数据可用性'}})
  fireEvent.change(screen.getByRole('textbox', {name:'第 7 项英文标题'}), {target:{value:'Data availability'}})
  fireEvent.change(screen.getByRole('combobox', {name:'第 7 项标题级别'}), {target:{value:'5'}})
  fireEvent.click(screen.getByRole('button', {name:'使用模板并继续'}))
  await screen.findByRole('heading', {name:'资源配置'})
  expect(new URLSearchParams(location.hash.slice(1)).get('view')).toBe('resources')
  expect(screen.getByRole('button', {name:'第 4 步：模板设定和资源配置', current:'step'})).toBeTruthy()
  const save = fetch.mock.calls.find(([url, init]) => url.endsWith('/sci-template') && init?.method === 'PUT')
  const input = JSON.parse(String(save?.[1]?.body))
  expect(input).toMatchObject({expected_revision:1, template_id:'frontiers-genetics-research-v1', figure_workflow:true})
  expect(input.sections.map((section: {id:string}) => section.id)).toEqual([
    'title','abstract','introduction','results','materials_and_methods','discussion',
    expect.stringMatching(/^sci-section-[a-f0-9]{32}$/),'references',
  ])
  expect(input.sections[3]).toEqual({id:'results', en:'Principal findings', zh:'主要发现', level:2})
  expect(input.sections[6]).toMatchObject({en:'Data availability', zh:'数据可用性', level:5})
  fireEvent.click(screen.getByRole('button', {name:'返回模板设定'}))
  expect((await screen.findByRole('combobox', {name:'SCI 模板'}))).toHaveProperty('value','frontiers-genetics-research-v1')
  expect(screen.getByRole('textbox', {name:'第 4 项中文标题'})).toHaveProperty('value','主要发现')
  expect(screen.getByRole('textbox', {name:'第 4 项英文标题'})).toHaveProperty('value','Principal findings')
  expect(screen.getByRole('combobox', {name:'第 4 项标题级别'})).toHaveProperty('value','2')
  expect(screen.getByRole('textbox', {name:'第 7 项中文标题'})).toHaveProperty('value','数据可用性')
  expect(screen.getByRole('combobox', {name:'第 7 项标题级别'})).toHaveProperty('value','5')
})

it('keeps the review synthesis chapter without adding research topics as headings', async () => {
  const fetch = open('sci', {step:'sci-template'}, true)
  expect(await screen.findByRole('textbox', {name:'第 5 项中文标题'})).toHaveProperty('value','主题综合')
  expect(screen.queryByRole('textbox', {name:'第 1 个主题小节标题'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'使用模板并继续'}))
  const continueToDraft = await screen.findByRole('button', {name:'下一步 文献与初稿'})
  await waitFor(() => expect(continueToDraft).toHaveProperty('disabled', false))
  fireEvent.click(continueToDraft)
  await screen.findByRole('button', {name:'第 5 步：文献与初稿', current:'step'})
  const save = fetch.mock.calls.find(([url, init]) => url.endsWith('/sci-template') && init?.method === 'PUT')
  const input = JSON.parse(String(save?.[1]?.body))
  expect(input.combine_review_topics).toBe(true)
  expect(input.sections).toHaveLength(8)
})

it('reads a bookmarked SCI request without replacing it with the newest draft', async () => {
  open('sci', { step: 'manuscripts', manuscript: 'paper', revision: '2', writingRequest: 'previous', view: 'writing' })
  expect((await screen.findByRole('region', {name:'修改对话'})).textContent).toBe('previous')
})

it('opens an exact earlier SCI draft from the comparison link', async () => {
  open('sci', { step: 'manuscripts', manuscript: 'paper', revision: '2', writingRequest: 'previous', view: 'body' })
  expect(await screen.findByText('Read previous')).toBeTruthy()
  expect(screen.queryByRole('region', {name:'修改对话'})).toBeNull()
})
