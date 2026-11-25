import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import type {Reference} from '../literature/literatureApi'
import {literatureTask} from '../literature/fixtures'
import {manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import {methodFields, validManuscript, type Candidates} from '../manuscripts/manuscriptTypes'
import {preparePaperDraft} from '../manuscripts/preparePaperDraft'
import {submitPaperDraft} from '../manuscripts/submitPaperDraft'
import {TaskRequestError} from '../tasks/taskApi'
import {liveRequest} from '../manuscripts/writingLiveFixtures'
import type {Project} from '../projects/projectTypes'
import {SciDraftGenerator, ThesisDraftGenerator} from './SciDraftGenerator'
import type {ThesisRequirements} from './thesisProjectRequirements'
import type {SciSettings} from './sciProjectSettings'

vi.mock('../manuscripts/preparePaperDraft', async original => ({...await original<typeof import('../manuscripts/preparePaperDraft')>(), preparePaperDraft: vi.fn()}))
vi.mock('../manuscripts/submitPaperDraft', async original => ({...await original<typeof import('../manuscripts/submitPaperDraft')>(), submitPaperDraft: vi.fn(), findPaperDraft: vi.fn(async () => null)}))
const stamp = '2026-11-21T12:00:00Z', base = '/api/v1/projects/p1'
const project: Project = {id: 'p1', project_type: 'sci', name: 'Paper', research_topic: 'Topic', default_output_language: 'en', created_at: stamp, updated_at: stamp, file_count: 1}
const settings: SciSettings = {article_type: 'narrative_review', proposed_title: 'Review', review_sections: [], keywords: ['cohort'], target_journal: {choice: 'science', name: null}}
const item: Reference = {id: 'ref1', reference_id: 'bib1', project_id: 'p1', pmid: '234',
  record: {pmid: '234', title: 'Study title', authors: [], year: 2024, journal: 'J', doi: null, abstract: [{label: 'Results', text: 'Saved abstract.'}], abstract_status: 'available',
    full_text_status: 'not_acquired', verification_status: 'not_verified', doi_resolution_status: 'not_checked', keywords: [], mesh_terms: [], full_text_links: []},
  source: {search_id: 'search1', receipt_id: 'receipt1', query: 'cohort', effective_query: 'cohort', retrieved_at: stamp, source_kind: 'synthetic_fixture', cached: false, ordinal: 1, source_download_url: base + '/literature/receipts/receipt1/source'},
  selection: {status: 'candidate', note: 'Existing note', revision: 1}, created_at: stamp, updated_at: stamp}
function serve(type: 'research' | 'narrative_review' = 'narrative_review', custom?: (url: string, options?: RequestInit) => Response | undefined) {
  let reference = structuredClone(item)
  const plan: Candidates = {project_type: 'sci', citation_drafts: [], methods_fields: [...methodFields],
    items: [{id:'run1', kind:'analysis_run', file_id: 'file1', label:'Analysis', version:1, allowed_roles:['computed_results'], download_url:null},
      {id:'doc1', kind:'document_version', file_id:'file1', label:'Study.docx', version:1, allowed_roles:['methods'], download_url:null}],
    paper_plan:{title:'Paper', kind:type, keywords:['cohort'], materials:[], sections:[], token:'a'.repeat(64), omitted_count:0}}
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const response = custom?.(url, options)
    if (response) return response
    if (url === base + '/manuscripts/candidates') return Response.json(plan)
    if (url === base + '/manuscripts') return Response.json({items:[manuscriptFixture]})
    if (url === base + '/literature/references/ref1' && options?.method === 'PATCH') {
      const change = JSON.parse(String(options.body))
      expect(change).toMatchObject({expected_revision: reference.selection.revision, note: 'Existing note'})
      reference = {...reference, selection:{...reference.selection, status:change.status, revision:reference.selection.revision + 1}}
      return Response.json(reference)
    }
    if (url.startsWith(base + '/literature/references?')) {
      const entries = url.includes('selection=shortlisted') && reference.selection.status !== 'shortlisted' ? [] : [reference]
      return Response.json({project_id:'p1', items:entries, page_size:10, page:1, total:entries.length})
    }
    throw new Error('unexpected ' + url)
  })
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}
beforeEach(() => {
  if (!validManuscript(manuscriptFixture, project.id)) throw new Error('Invalid synthetic manuscript')
  vi.mocked(preparePaperDraft).mockResolvedValue({root: manuscriptFixture, manuscriptId: 'm1', version: manuscriptFixture.versions[0]})
  vi.mocked(submitPaperDraft).mockResolvedValue(liveRequest)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); sessionStorage.clear() })
const chapters = [
  {id:'cover', title:'学位声明', level:1}, {id:'intro', title:'第一章 绪论', level:1},
  {id:'intro-sub', title:'1.1 研究设计依据', level:2}, {id:'methods', title:'试验安排', level:1},
  {id:'results', title:'第二章 观察指标', level:1}, {id:'custom', title:'独立专题', level:1},
]
const thesisRequirements: ThesisRequirements = {title:'学位论文',keywords:['sleep'],school:'示例学院',education_level:'硕士',
  language:'zh-CN', revision:3, sections:[],template:{name:'学院目录',confirmation_id:'confirmed',chapters}}
const thesisCandidates = {
  project_type:'thesis', citation_drafts:[],methods_fields:[...methodFields],
  items:[{kind:'document_version',id:'doc',file_id:'file',label:'报告.docx',version:1,allowed_roles:['methods'],download_url:null}] as Candidates['items'],
  thesis:{ready:true, confirmation_id:'confirmed', profile:{revision:3,school:'示例学院',major:'',department:'',degree_type:'',
    education_level:'硕士',applicable_version:'',bound_confirmation_id:'confirmed'}, blocking_reasons:[] as string[],chapters,
    protected_chapter_purposes:{cover:'manual'},purposes:['manual','introduction','results','discussion'],
    template_source_file_ids:['directory'],template_source_filenames:['学院目录.docx']},
  paper_plan:{kind:'thesis',title:'学位论文',keywords:['sleep'],sections:[
    {id:'p-methods',chapter_id:'methods',purpose:'materials_and_methods',label:'试验安排',text:'采用连续入组。'},
    {id:'p-results',chapter_id:'results',purpose:'results',label:'第二章 观察指标',text:'观察组评分较高。'},
  ], materials:[{section_id:'p-results',kind:'figure',filename:'评分.png',result:'两组评分。',
    selection:{id:'fig',file_id:'fig',kind:'original',role:'image_observation'}}],token:'b'.repeat(64),omitted_count:0},
}
function serveThesis(candidates = thesisCandidates) {
  return serve('research', url => url.endsWith('/manuscripts/candidates') ? Response.json(candidates) : undefined)
}
function mountThesis(onSubmitted = vi.fn(), onOpenOrganizer = vi.fn()) {
  return render(<ThesisDraftGenerator project={{...project,project_type:'thesis'}} requirements={thesisRequirements}
    onOpenMaterials={vi.fn()} onOpenProject={vi.fn()} onOpenOrganizer={onOpenOrganizer} onSubmitted={onSubmitted}/>)
}
it('uses the school outline, saved requirements and shortlisted abstracts and only asks about the ambiguous chapter', async () => {
  serveThesis()
  const done = vi.fn()
  mountThesis(done)
  const choose = await screen.findByRole('combobox',{name:'独立专题'})
  expect(screen.getAllByRole('combobox')).toHaveLength(1)
  expect(screen.getByRole('textbox',{name:'检索词'})).toHaveProperty('value','sleep')
  for (const name of ['学院目录.docx','报告.docx','评分.png','采用连续入组。','观察组评分较高。']) expect(screen.getByText(name)).toBeTruthy()
  const generate = screen.getByRole('button',{name:'生成毕业论文初稿'})
  expect(generate).toHaveProperty('disabled',true)
  fireEvent.change(choose,{target:{value:'discussion'}})
  fireEvent.click(await screen.findByRole('checkbox',{name:'Study title'}))
  await waitFor(() => expect(screen.getByRole('checkbox',{name:'Study title'})).toHaveProperty('checked',true))
  expect(screen.getByText('Saved abstract.')).toBeTruthy()
  fireEvent.click(generate)
  await waitFor(() => expect(done).toHaveBeenCalledOnce())
  expect(preparePaperDraft).toHaveBeenCalledWith(expect.objectContaining({references:[{project_reference_id:'ref1',search_id:'search1'}],
    input:expect.objectContaining({output_language:'zh-CN',paper_plan_token:'b'.repeat(64),sources:[{id:'doc',file_id:'file',kind:'document_version',role:'methods'}],
      thesis:{confirmation_id:'confirmed',profile_revision:3,chapter_mappings:chapters.map((c,i) => ({
        chapter_id:c.id, purpose:['manual','introduction','introduction','materials_and_methods','results','discussion'][i],
        output_language:'project',result_group_ids:i===4?['p-results']:[],
      }))}})}))
  expect(submitPaperDraft).toHaveBeenCalledWith(expect.objectContaining({documentKind:'thesis'}))
})
it('blocks generation when the school directory is unavailable and links to its repair step', async () => {
  serveThesis({...thesisCandidates, thesis:{...thesisCandidates.thesis,ready:false,blocking_reasons:['school_template_not_ready']}})
  const open = vi.fn()
  mountThesis(vi.fn(),open)
  const repair = await screen.findByRole('button',{name:'前往模板与资料整理'})
  fireEvent.click(repair)
  expect(open).toHaveBeenCalledOnce()
  expect(screen.getByRole('button',{name:'生成毕业论文初稿'})).toHaveProperty('disabled',true)
})

it('shows assigned thesis figures and keeps only independent originals as automatic image inputs', async () => {
  const figure = {figure_id:'thesis-figure',chapter_id:'thesis:figure:confirmed:results',chapter_label:'第二章 观察指标',
    title:'病例登记流程图',caption:'登记、核对和归档。',panel_file_ids:['fig-panel']}
  const originals: Candidates['items'] = ['fig-panel', 'independent'].map(id => ({kind:'original', id, file_id:id, label:id + '.png',
    version:null, allowed_roles:['image_observation'], download_url:null}))
  const candidates = {...thesisCandidates,items:[...thesisCandidates.items,...originals],
    paper_plan:{...thesisCandidates.paper_plan,thesis_figures:[figure]}}
  const old = manuscriptFixture.versions[0]
  const previous = {...old,input:{...old.input, sources:[{kind:'original',id:'fig-panel',file_id:'fig-panel',role:'image_observation'}],
    figure_notes:[{figure_id:'fig-panel',caption:'旧的单张图注。',panels:[]}]}}
  serve('research', url => url.endsWith('/manuscripts/candidates') ? Response.json(candidates) :
    url.endsWith('/manuscripts') ? Response.json({items:[{...manuscriptFixture,versions:[previous]}]}) : undefined)
  mountThesis()
  const panel = within(await screen.findByRole('region', {name:'本次配图（1 张）'}))
  expect(panel.getByText(figure.title)).toBeTruthy()
  expect(panel.getByText(figure.chapter_label)).toBeTruthy()
  expect(panel.getByText(figure.caption)).toBeTruthy()
  fireEvent.change(screen.getByRole('combobox',{name:'独立专题'}),{target:{value:'discussion'}})
  fireEvent.click(screen.getByRole('button',{name:'生成毕业论文初稿'}))
  await waitFor(() => expect(preparePaperDraft).toHaveBeenCalledOnce())
  const input = vi.mocked(preparePaperDraft).mock.calls[0][0].input
  expect(input.sources.map(source => source.id)).toEqual(['doc','independent'])
  expect(input.figure_notes).toEqual([])
})

it('sends an obsolete thesis figure assignment back to the school organizer', async () => {
  const candidates = {...thesisCandidates,paper_plan:{...thesisCandidates.paper_plan,thesis_figures_need_configuration:true}}
  const open = vi.fn()
  serveThesis(candidates)
  mountThesis(vi.fn(),open)
  await screen.findByText('请先在资源配置中核对并保存图件。')
  expect(screen.getByRole('button',{name:'生成毕业论文初稿'})).toHaveProperty('disabled',true)
  fireEvent.click(screen.getByRole('button',{name:'前往模板与资料整理'}))
  expect(open).toHaveBeenCalledOnce()
})
it('classifies the university outline, keeps the full order collapsed and asks once for an unfamiliar chapter tree', async () => {
  const labels = [
    [1,'摘  要'],[1,'ABSTRACT'],[1,'目  录'],[1,'1 引言'],[2,'1.1 问题的提出'],
    [1,'2 文献综述'],[2,'2.1 国内研究现状'],[2,'2.2 国外研究现状'],
    [1,'3 研究设计'],[2,'3.1研究对象、方法和技术路线'],[3,'3.1.2研究方法'],[4,'3.1.2.1 某某法'],
    [4,'……'],[1,'4 研究过程与分析（根据实际情况填写）'],[2,'4.1 研究部分（根据实际情况填写）'],
    [1,'5 研究结论与建议'],[2,'5.2 研究建议'],[3,'……（根据实际情况填写）'],
    [1,'参考文献'],[1,'附  录'],[2,'附录A XX访谈提纲'],[1,'致  谢'],[1,'个人简历'],
    [1,'6 独立课题'],[2,'6.1 专题甲'],[3,'6.1.1 子题乙'],
  ] as const
  const outline = labels.map(([level,title],i) => ({id:'part'+i,title,level}))
  serveThesis({...thesisCandidates, thesis:{...thesisCandidates.thesis,chapters:outline},
    paper_plan:{...thesisCandidates.paper_plan,sections:[],materials:[]}})
  mountThesis()
  const choose = await screen.findByRole('combobox',{name:'6 独立课题'})
  expect(screen.getAllByRole('combobox')).toHaveLength(1)
  expect(screen.getByText('学校目录（26 个章节）').closest('details')?.open).toBe(false)
  fireEvent.change(choose,{target:{value:'discussion'}})
  fireEvent.click(screen.getByRole('button',{name:'生成毕业论文初稿'}))
  await waitFor(() => expect(preparePaperDraft).toHaveBeenCalledOnce())
  const mappings = vi.mocked(preparePaperDraft).mock.calls[0][0].input.thesis!.chapter_mappings
  expect(mappings.map(m => m.chapter_id)).toEqual(outline.map(c => c.id))
  expect(mappings.map(m => m.purpose)).toEqual([
    'abstract','abstract','manual','introduction','introduction','introduction','introduction','introduction',
    'materials_and_methods','materials_and_methods','materials_and_methods','materials_and_methods','materials_and_methods',
    'results','results','conclusion','conclusion','conclusion','references','manual','manual','acknowledgements','manual',
    'discussion','discussion','discussion',
  ])
  expect(mappings[1].output_language).toBe('en')
})
it('reopens safely after an older manuscript loses its school binding', async () => {
  const old = manuscriptFixture.versions[0]
  const previous = {...old,input:{...old.input,thesis:{confirmation_id:'older',profile_revision:1,
    chapter_mappings:[{chapter_id:'intro',purpose:'introduction',output_language:'project',result_group_ids:[]}]}}}
  serve('research',url => url.endsWith('/manuscripts/candidates') ? Response.json({...thesisCandidates,
    thesis:{...thesisCandidates.thesis,ready:false,confirmation_id:null,chapters:[],blocking_reasons:['school_template_not_bound']}}) :
    url.endsWith('/manuscripts') ? Response.json({items:[{...manuscriptFixture,versions:[previous]}]}) : undefined)
  mountThesis()
  expect(await screen.findByRole('button',{name:'前往模板与资料整理'})).toBeTruthy()
  expect(screen.queryByText('第一章 绪论')).toBeNull()
})
it('shows carried thesis evidence and reported findings and honors an explicit removal of the old citations', async () => {
  const old = manuscriptFixture.versions[0]
  const citation = {id:'cited',revision:1}, finding = {text:'历史观察结果。',source_ids:['doc']}
  const cited = {...old, input:{...old.input,reported_result:finding,citation_draft:citation,
    sources:[{kind:'document_version',id:'doc',file_id:'file',role:'user_results'}]}, snapshot:{...old.snapshot,
    citation_snapshot:{paragraphs:[{fragments:[{bindings:[{evidence:[{id:'e1',quote:'Original saved excerpt.'}]}]}]}]}}}
  serve('research',url => url.endsWith('/manuscripts/candidates') ? Response.json(thesisCandidates) :
    url.endsWith('/manuscripts') ? Response.json({items:[{...manuscriptFixture,versions:[cited]}]}) : undefined)
  mountThesis()
  const keep = await screen.findByRole('checkbox',{name:'沿用上次稿件的引用'})
  expect(keep).toHaveProperty('checked',true)
  expect(screen.getByText('Original saved excerpt.')).toBeTruthy()
  expect(screen.getByText(finding.text)).toBeTruthy()
  fireEvent.click(keep)
  fireEvent.change(screen.getByRole('combobox',{name:'独立专题'}),{target:{value:'discussion'}})
  fireEvent.click(screen.getByRole('button',{name:'生成毕业论文初稿'}))
  await waitFor(() => expect(preparePaperDraft).toHaveBeenCalledOnce())
  const {input} = vi.mocked(preparePaperDraft).mock.calls[0][0]
  expect(input.citation_draft).toBeNull()
  expect(input.reported_result).toEqual(finding)
  expect(input.thesis?.chapter_mappings.find(c => c.chapter_id === 'results')?.result_group_ids).toEqual(['p-results','reported-result'])
})
it('lets the customer place a carried finding when a changed school outline has two results chapters', async () => {
  const old = manuscriptFixture.versions[0]
  const previous = {...old,input:{...old.input,reported_result:{text:'已保存的结果。',source_ids:['doc']},
    sources:[{id:'doc',file_id:'file',kind:'document_version',role:'user_results'}]}}
  const outline = [...chapters.filter(c => c.id !== 'custom'), {id:'second-results',title:'实验结果',level:1}]
  serve('research',url => url.endsWith('/manuscripts/candidates') ? Response.json({...thesisCandidates,
    thesis:{...thesisCandidates.thesis,chapters:outline}}) :
    url.endsWith('/manuscripts') ? Response.json({items:[{...manuscriptFixture,versions:[previous]}]}) : undefined)
  mountThesis()
  const select = await screen.findByRole('combobox',{name:'已有结果属于哪个章节？'})
  const generate = screen.getByRole('button',{name:'生成毕业论文初稿'})
  expect(generate).toHaveProperty('disabled',true)
  fireEvent.change(select,{target:{value:'second-results'}})
  fireEvent.click(generate)
  await waitFor(() => expect(preparePaperDraft).toHaveBeenCalledOnce())
  const chaptersSent = vi.mocked(preparePaperDraft).mock.calls[0][0].input.thesis!.chapter_mappings
  expect(chaptersSent.find(c => c.chapter_id === 'results')?.result_group_ids).toEqual(['p-results'])
  expect(chaptersSent.find(c => c.chapter_id === 'second-results')?.result_group_ids).toEqual(['reported-result'])
})
it('offers one recovery action on reopening a failed version and a new preparation only after recovery is rejected', async () => {
  const first = manuscriptFixture.versions[0]
  const failed = {...first, status:'failed', current_changes:[], input:{...first.input, paper_plan_token:'a'.repeat(64),
    sources:[{kind:'document_version', id:'doc1', file_id:'file1', role:'methods'}]},
    snapshot:{...first.snapshot, references:[{number:1,text:'Paper',project_reference_id:item.id}]}}
  serve('narrative_review', url => {
    if (url === base + '/manuscripts') return Response.json({items:[{...manuscriptFixture,versions:[failed]}]})
    if (url.includes('selection=shortlisted')) return Response.json({project_id:'p1',total:1,page:1,page_size:10,
      items:[{...item,selection:{...item.selection,status:'shortlisted'}}]})
  })
  vi.mocked(preparePaperDraft).mockRejectedValueOnce(new TaskRequestError('当前资料已变更，请使用当前资料生成。',409))
  render(<SciDraftGenerator project={project} settings={settings} onSubmitted={vi.fn()}/>)
  const retry = await screen.findByRole('button',{name:'恢复原整理任务并生成初稿'})
  expect(screen.queryByRole('button',{name:'使用当前资料生成'})).toBeNull()
  fireEvent.click(retry)
  expect(await screen.findByRole('button',{name:'使用当前资料生成'})).toBeTruthy()
  expect(preparePaperDraft).toHaveBeenCalledWith(expect.objectContaining({existingRevision:1,manuscriptId:'m1',references:[]}))
})
it('persists a checkbox once per change and directly uses the saved shortlist and own upload on the current manuscript', async () => {
  const api = serve(), onSubmitted = vi.fn()
  const mount = () => render(<SciDraftGenerator project={project} settings={settings} onSubmitted={onSubmitted}/>)
  const first = mount()
  const checkbox = await screen.findByRole('checkbox', {name: 'Study title'})
  expect(screen.getByText('Saved abstract.')).toBeTruthy()
  fireEvent.click(checkbox)
  await waitFor(() => expect(screen.getByRole('checkbox', {name:'Study title'})).toHaveProperty('checked',true))
  first.unmount()
  mount()
  expect(await screen.findByRole('checkbox', {name:'Study title'})).toHaveProperty('checked',true)
  fireEvent.click(screen.getByRole('checkbox', {name:'Study title'}))
  await waitFor(() => expect(screen.getByRole('checkbox', {name:'Study title'})).toHaveProperty('checked',false))
  fireEvent.click(screen.getByRole('checkbox', {name:'Study title'}))
  const generate = screen.getByRole('button', {name:'生成初稿'})
  await waitFor(() => expect(generate).toHaveProperty('disabled',false))
  fireEvent.click(generate)
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith('m1',1,liveRequest.id))
  expect(preparePaperDraft).toHaveBeenCalledWith(expect.objectContaining({manuscriptId:'m1', references:[{project_reference_id:'ref1', search_id:'search1'}],
    input: expect.objectContaining({expected_revision:1, sources:[{kind:'document_version', file_id:'file1', id:'doc1', role:'methods'}]})}))
  expect(api.mock.calls.filter(([, options]) => options?.method==='PATCH')).toHaveLength(3)
})
it('asks just for results on an empty research project and never sends an unrelated analysis as evidence', async () => {
  serve('research')
  const onOpenProject = vi.fn()
  render(<SciDraftGenerator project={project} settings={{...settings, article_type:'research', figure_findings:[], proposed_title:'Paper'}} onSubmitted={vi.fn()} onOpenProject={onOpenProject}/>)
  expect(await screen.findByText('请在项目信息中补充主要结果。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', {name:'补充主要结果'}))
  expect(onOpenProject).toHaveBeenCalledOnce()
  expect(screen.getByRole('button', {name:'生成初稿'})).toHaveProperty('disabled',true)
  expect(preparePaperDraft).not.toHaveBeenCalled()
})

it.each([2, 50])('counts %i planned review images including section-bound files when preparing a draft', async imageCount => {
  const images = Array.from({length:imageCount}, (_, index) => ({
    section_id:index ? 'discussion' : 'theme', kind:'figure', filename:'map-' + index + '.png', result:'',
    selection:{kind:'original', id:'image' + index, file_id:'image' + index, role:'image_observation'},
  }))
  serve('narrative_review', url => {
    if (url.endsWith('/manuscripts/candidates')) return Response.json({project_type:'sci', methods_fields:[...methodFields], citation_drafts:[],
      items:[{kind:'original', id:'image0', file_id:'image0', label:'map-0.png', version:null, allowed_roles:['image_observation'], download_url:null},
        {kind:'document_version', id:'doc1', file_id:'notes', label:'Notes.docx', version:1, allowed_roles:['methods'], download_url:null}],
      paper_plan:{kind:'narrative_review', title:'Review', keywords:[], sections:[{id:'theme', label:'Neurobiology', text:''}],
        materials:images, token:'a'.repeat(64), omitted_count:0}})
    if (url.includes('selection=shortlisted')) return Response.json({project_id:'p1', total:1, page:1, page_size:10,
      items:[{...item,selection:{...item.selection,status:'shortlisted'}}]})
  })
  render(<SciDraftGenerator project={project} settings={settings} onSubmitted={vi.fn()}/>)
  const summary = await screen.findByText('本次配图（' + imageCount + ' 张）')
  fireEvent.click(summary)
  expect(screen.getByText('map-0.png · Neurobiology')).toBeTruthy()
  expect(screen.getByText('map-1.png · Synthesis and limitations')).toBeTruthy()
  expect(screen.getByRole('button', {name:'生成初稿'})).toHaveProperty('disabled', imageCount === 50)
  if (imageCount === 50) expect(screen.getByText('本项目超过单次写作可使用的 50 项资料。')).toBeTruthy()
})

it('lists configured SCI figures and sends recovery to resources while a placement needs repair', async () => {
  const resources = vi.fn()
  serve('narrative_review', url => {
    if (url.endsWith('/manuscripts/candidates')) return Response.json({project_type:'sci', methods_fields:[...methodFields], citation_drafts:[], items:[],
      paper_plan:{kind:'narrative_review', title:'Review', keywords:[], sections:[], token:'a'.repeat(64), omitted_count:0,
        materials:[{section_id:'discussion', kind:'figure', filename:'Old automatically placed.png', result:'',
          selection:{id:'old-figure', file_id:'old-figure', kind:'original', role:'image_observation'}}],
        sci_figures:[{figure_id:'new-figure', chapter_id:'discussion', chapter_label:'Synthesis', title:'Selected formal figure', caption:'A caption.'}],
        sci_figures_need_configuration:true}})
    if (url.includes('selection=shortlisted')) return Response.json({project_id:'p1', total:1, page:1, page_size:10,
      items:[{...item, selection:{...item.selection,status:'shortlisted'}}]})
  })
  render(<SciDraftGenerator project={project} settings={settings} onOpenResources={resources} onSubmitted={vi.fn()}/>)
  expect(await screen.findByText('Selected formal figure')).toBeTruthy()
  expect(screen.getByText('Synthesis')).toBeTruthy()
  expect(screen.getByText('A caption.')).toBeTruthy()
  expect(screen.queryByText(/Old automatically placed/)).toBeNull()
  const generate = screen.getByRole('button', {name:'生成初稿'})
  expect(generate).toHaveProperty('disabled', true)
  fireEvent.click(generate)
  expect(preparePaperDraft).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', {name:'前往资源配置'}))
  expect(resources).toHaveBeenCalledOnce()
})

it('uses the frozen plan for selected SCI figures without including unassigned original images as writing sources', async () => {
  serve('narrative_review', url => {
    if (url.endsWith('/manuscripts/candidates')) return Response.json({project_type:'sci', methods_fields:[...methodFields], citation_drafts:[],
      items:[{kind:'original', id:'unused', file_id:'unused', label:'Unused.png', version:null,
        allowed_roles:['methods','image_observation'], download_url:null},
      {kind:'document_version', id:'notes', file_id:'document', label:'Notes.docx', version:1, allowed_roles:['methods'], download_url:null}],
      paper_plan:{kind:'narrative_review', title:'Review', keywords:[], sections:[], token:'a'.repeat(64), omitted_count:0,
        materials:[], sci_figures:[{figure_id:'fixed-figure', chapter_id:'discussion', chapter_label:'Synthesis', title:'Panel', caption:'Description'}]}})
    if (url.includes('selection=shortlisted')) return Response.json({project_id:'p1', total:1, page:1, page_size:10,
      items:[{...item, selection:{...item.selection,status:'shortlisted'}}]})
  })
  render(<SciDraftGenerator project={project} settings={settings} onSubmitted={vi.fn()} />)
  const generate = screen.getByRole('button', {name:'生成初稿'})
  await waitFor(() => expect(generate).toHaveProperty('disabled', false))
  fireEvent.click(generate)
  await waitFor(() => expect(preparePaperDraft).toHaveBeenCalledWith(expect.objectContaining({input:expect.objectContaining({
    paper_plan_token:'a'.repeat(64), sources:[{id:'notes', kind:'document_version', file_id:'document', role:'methods'}],
  })})))
})

it('searches from the same page using the project keywords and displays the returned abstract', async () => {
  const query = {research_topic:'Topic',source_context:{kind:'project_topic',label:'',text:'Topic'},query:'cohort',year_from:null,year_to:null,publication_types:[],sort:'relevance',limit:20,output_language:'en'}
  const task = {...literatureTask, status:'succeeded', display_status:'succeeded', reason_code:null}
  const api = serve('narrative_review', (url, options) => {
    if (url.endsWith('/searches') && options?.method === 'POST') return Response.json(task)
    if (url.endsWith('/searches/search1')) return Response.json({id:'search1',project_id:'p1',task,input:query,effective_query:'cohort',
      query_translation:null,matched_count:1,retrieved_count:1,missing_pmids:[],warnings:[],created_at:stamp,updated_at:stamp,source_url:'https://pubmed.ncbi.nlm.nih.gov/'})
    if (url.includes('search_id=search1')) return Response.json({project_id:'p1', items:[{...item,record:{...item.record,title:'Query result'}}], total:1, page:1, page_size:10})
  })
  render(<SciDraftGenerator project={project} settings={settings} onSubmitted={vi.fn()}/>)
  expect(screen.getByRole('textbox', {name:'检索词'})).toHaveProperty('value','cohort')
  fireEvent.click(screen.getByRole('button', {name:'搜索文献'}))
  expect(await screen.findByRole('checkbox', {name:'Query result'})).toBeTruthy()
  const sent = api.mock.calls.find(([url]) => url.endsWith('/searches'))
  expect(JSON.parse(String(sent?.[1]?.body))).toEqual(query)
  expect(screen.getByText('Saved abstract.')).toBeTruthy()
})

it('places SCI draft generation after the references and their pagination', async () => {
  serve('narrative_review', url => {
    if (url === base + '/literature/references?page=1') {
      const items = Array.from({length: 10}, (_, index) => ({...item, id:'ref' + index}))
      return Response.json({project_id:'p1', items, total:11, page:1, page_size:10})
    }
  })
  render(<SciDraftGenerator project={project} settings={settings} onSubmitted={vi.fn()} />)
  const pagination = await screen.findByRole('navigation', {name:'候选文献分页'})
  const generate = screen.getByRole('button', {name:'生成初稿'})
  expect(pagination.compareDocumentPosition(generate) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it('uses all selected pages, including choices outside the visible search', async () => {
  const selected = Array.from({length: 12}, (_, index) => ({...item, id:'ref' + (index + 1),
    selection:{...item.selection,status:'shortlisted'}}))
  serve('narrative_review', url => {
    if (!url.includes('selection=shortlisted')) return
    const page = Number(new URL(url, 'http://test').searchParams.get('page'))
    return Response.json({project_id:'p1',items:selected.slice((page - 1) * 10, page * 10),page,page_size:10,total:selected.length})
  })
  const onSubmitted = vi.fn()
  render(<SciDraftGenerator project={project} settings={settings} onSubmitted={onSubmitted}/>)
  const button = screen.getByRole('button',{name:'生成初稿'})
  await waitFor(() => expect(button).toHaveProperty('disabled',false))
  fireEvent.click(button)
  await waitFor(() => expect(onSubmitted).toHaveBeenCalledOnce())
  expect(vi.mocked(preparePaperDraft).mock.calls[0][0].references.map(row => row.project_reference_id)).toEqual(selected.map(ref => ref.id))
})

it.each([
  ['failed','ncbi_not_configured',null,'NCBI 配置尚未就绪'],
  ['failed','confirmation_required','ncbi_unavailable','NCBI 暂时不可用'],
  ['succeeded',null,null,'本次检索没有返回候选文献。请调整检索词后重试。'],
] as const)('distinguishes an empty search from an empty project (%s %s %s)', async (status, reason, code, message) => {
  const task = {...literatureTask, status, display_status:status, reason_code:reason, error_code:code}
  const input = {research_topic:'Topic',source_context:{kind:'project_topic',label:'',text:'Topic'},query:'cohort',year_from:null,year_to:null,publication_types:[],sort:'relevance',limit:20,output_language:'en'}
  const resume = vi.fn()
  serve('narrative_review', (url, options) => {
    if (url.endsWith('/searches') && options?.method === 'POST') {
      Object.assign(input, JSON.parse(String(options.body)))
      return Response.json(task)
    }
    if (url.endsWith('/tasks/search1/resume') && options?.method === 'POST') {
      resume(JSON.parse(String(options.body)))
      return Response.json(task)
    }
    if (url.endsWith('/searches/search1')) return Response.json({id:'search1',project_id:'p1',task,input,effective_query:'cohort',query_translation:null,
      matched_count:status === 'failed' ? null : 0,retrieved_count:0,missing_pmids:[],warnings:[],created_at:stamp,updated_at:stamp,source_url:'https://pubmed.ncbi.nlm.nih.gov/'})
    if (url.includes('search_id=search1')) return Response.json({project_id:'p1',items:[],total:0,page:1,page_size:10})
  })
  render(<SciDraftGenerator project={project} settings={settings} onSubmitted={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button', {name:'搜索文献'}))
  expect(await screen.findByText(message, {exact:false})).toBeTruthy()
  if (status === 'failed') expect(screen.getByRole('button', {name:'重新检索'})).toBeTruthy()
  if (code === 'ncbi_unavailable') {
    fireEvent.click(screen.getByRole('button', {name:'重新检索'}))
    await waitFor(() => expect(resume).toHaveBeenCalledWith({operation:'retry', wait_id:null, expected_task_revision:task.revision, input_version:task.input_version}))
  }
  expect(screen.queryByText('此项目还没有保存的候选文献。')).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'查看已有候选'}))
  expect(await screen.findByRole('checkbox',{name:'Study title'})).toBeTruthy()
})

it('names unparsed files and requires the explicit available-materials action', async () => {
  serve('research', url => {
    if (url.endsWith('/manuscripts/candidates')) return Response.json({project_type:'sci', methods_fields:[...methodFields], citation_drafts:[],
      items:[{kind:'original',id:'f1',file_id:'f1',label:'Pending.docx',version:null,allowed_roles:['methods'],download_url:null}],
      paper_plan:{title:'Paper',kind:'research',keywords:[],sections:[{id:'main',label:'Finding',text:'Author supplied result.'}],
        materials:[],token:'a'.repeat(64),omitted_count:0}})
  })
  render(<SciDraftGenerator project={project} settings={{...settings,article_type:'research',figure_findings:[],proposed_title:'Paper'}} onSubmitted={vi.fn()}/>)
  expect(await screen.findByText('Pending.docx')).toBeTruthy()
  expect(screen.getByText('以下文件尚无可读正文。本次仅使用已保存的文件说明。')).toBeTruthy()
  expect(screen.getByRole('button',{name:'使用现有资料继续生成'})).toHaveProperty('disabled',false)
  expect(preparePaperDraft).not.toHaveBeenCalled()
})
