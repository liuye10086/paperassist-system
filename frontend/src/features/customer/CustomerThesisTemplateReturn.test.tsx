// B04 task 8: a thesis chapter without a school template goes to the template page with a `chapter` return token
// and comes back to that chapter once the template is adopted (wireframe 13b); project details save and continue (23).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale, translate } from '../../shared/i18n'
import { AdoptActions } from '../school-templates/CustomerTemplateAdopt'
import CustomerWorkspace from './CustomerWorkspace'

type Stub = { returnPlace?: string; onAdopted?: (id: string) => void; onContinue?: () => void
  onNavigate?: (next: { view: string; templateId: string }) => void }
const server = vi.hoisted(() => ({ adopted: false, before: 'unbound' as 'unbound' | 'changed' | 'ready', after: 'renamed' as 'renamed' | 'gone' | 'duplicate' }))
vi.mock('../school-templates/SchoolTemplates', () => ({
  default: ({ returnPlace, onAdopted, onContinue, onNavigate }: Stub) => <div>
    <p>{`return-place:${returnPlace ?? ''}`}</p>
    <button type="button" onClick={() => onNavigate?.({ view: 'detail', templateId: 'template-2' })}>打开模板详情</button>
    <AdoptActions name="学校模板" change={false} bound={false} busy={false} ready returnPlace={returnPlace}
      onAdopt={() => { server.adopted = true; onAdopted?.('confirm2') }} onRetry={() => {}} />
    {onContinue && <button type="button" onClick={onContinue}>继续 写作资料与引用</button>}
  </div>,
}))

const project = {
  id: 'customer-thesis-8', name: '毕业论文样例', research_topic: '运动干预',
  project_type: 'thesis', file_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
}
const base = '/api/v1/projects/' + project.id
const purposes = ['abstract', 'introduction', 'materials_and_methods', 'results', 'discussion', 'conclusion', 'references', 'acknowledgements', 'manual', 'other']
const profile = (revision: number, bound: string | null) => ({ revision, school: '北京体育大学', department: '', major: '', degree_type: '硕士',
  education_level: '研究生', applicable_version: '2026', bound_confirmation_id: bound })
const oldChapters = [{ id: 'old-intro', title: '第一章 绪论', level: 1 }, { id: 'old-design', title: '第 3 章 研究设计', level: 1 }]
const renamedChapters = [{ id: 'new-intro', title: '第一章 绪论', level: 1 }, { id: 'new-design', title: '第 3 章 研究设计', level: 1 },
  { id: 'new-results', title: '第四章 研究结果', level: 1 }]
function readiness() {
  if (!server.adopted) {
    if (server.before === 'unbound') return { ready: false, blocking_reasons: ['school_template_not_bound'], profile: profile(1, null),
      confirmation_id: null, chapters: [], purposes, template_source_file_ids: [] }
    return { ready: server.before === 'ready', blocking_reasons: server.before === 'ready' ? [] : ['school_template_source_changed'],
      profile: profile(2, 'confirm1'), confirmation_id: 'confirm1', chapters: oldChapters, purposes, template_source_file_ids: [] }
  }
  const chapters = server.before === 'unbound' ? oldChapters : server.after === 'gone' ? [{ id: 'new-other', title: '第一章 引言', level: 1 }]
    : server.after === 'duplicate' ? [...renamedChapters, { ...renamedChapters[1], id: 'new-design-2' }] : renamedChapters
  return { ready: true, blocking_reasons: [], profile: profile(3, 'confirm2'), confirmation_id: server.before === 'unbound' ? 'confirm1' : 'confirm2',
    chapters, purposes, template_source_file_ids: [] }
}
function serve() {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === base) return Response.json(project)
    if (url === base + '/manuscripts/candidates') return Response.json({ items: [], citation_drafts: [], methods_fields: [], project_type: 'thesis', thesis: readiness() })
    if (url === base + '/manuscripts/preview') return new Response(null, { status: 500 })
    if (url === base + '/manuscripts') return Response.json({ items: [] })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const materials = `customer-project=${project.id}&step=manuscripts&view=materials`
function trip(origin: string, chapter: string) {
  return '#' + new URLSearchParams({ 'customer-project': project.id, step: 'school', return: origin, returnLabel: 'chapter', returnChapter: chapter }).toString()
}

beforeEach(() => {
  setApiSession('csrf', 'customer-test')
  sessionStorage.clear()
  Object.assign(server, { adopted: false, before: 'unbound', after: 'renamed' })
})
afterEach(() => {
  cleanup()
  setLocale('zh-CN')
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it.each([
  ['zh-CN', 'en', 'focus=chapters', '章节与复核', 'Chapters and review'],
  ['en', 'zh-CN', 'focus=chapters', 'Chapters and review', '章节与复核'],
  ['zh-CN', 'en', 'chapter=old-design', '章节与复核', '章节与复核'],
  ['en', 'zh-CN', 'chapter=old-design', 'Chapters and review', 'Chapters and review'],
] as const)('uses the current locale for the section return and keeps named chapters (%s to %s, %s)', async (from, to, location, title, expected) => {
  serve()
  setLocale(from)
  const origin = materials + '&' + location
  const address = trip(origin, title)
  window.history.replaceState(null, '', address)
  render(<CustomerWorkspace />)
  await screen.findByRole('link', { name: translate('返回 {place}', { place: title }) })
  act(() => setLocale(to))
  expect(screen.getByText(translate('正在为“{place}”采用学校模板', { place: expected }))).toBeTruthy()
  expect(screen.getByRole('link', { name: translate('返回 {place}', { place: expected }) }).getAttribute('href')).toBe('#' + origin)
  expect(screen.getByRole('button', { name: translate('完成并返回 {place}', { place: expected }) })).toBeTruthy()
  expect(window.location.hash).toBe(address)
})

it('goes from chapters without a template to the template page with a return token and back to the chapters', async () => {
  serve()
  window.history.replaceState(null, '', '#' + materials)
  render(<CustomerWorkspace />)
  expect(await screen.findByText('还没有采用学校模板。采用后才能按学校格式核对本章标题和级别。')).toBeTruthy()
  expect(screen.queryByText('请先绑定学校模板')).toBeNull()
  fireEvent.click(await screen.findByRole('button', { name: '去采用学校模板（完成后回到章节与复核）' }))
  await waitFor(() => expect(window.location.hash).toBe(trip(materials + '&focus=chapters', '章节与复核')))
  expect(await screen.findByText('正在为“章节与复核”采用学校模板')).toBeTruthy()
  expect(screen.getByRole('link', { name: '返回 章节与复核' })).toBeTruthy()
  expect(screen.getByText('return-place:章节与复核')).toBeTruthy()
  // Switching views inside the template page keeps the token.
  fireEvent.click(screen.getByRole('button', { name: '打开模板详情' }))
  await waitFor(() => expect(new URLSearchParams(window.location.hash.slice(1)).get('template')).toBe('template-2'))
  expect(new URLSearchParams(window.location.hash.slice(1)).get('returnLabel')).toBe('chapter')
  expect(screen.getByRole('link', { name: '返回 章节与复核' })).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '采用这份模板' }))
  const heading = await screen.findByRole('heading', { name: '学校章节配置' })
  await waitFor(() => expect(document.activeElement).toBe(heading))
  expect(screen.getByRole('group', { name: '第 3 章 研究设计' })).toBeTruthy()
  await waitFor(() => expect(window.location.hash).toBe('#' + materials))
  expect(screen.queryByText('原位置已不可用，已回到章节与复核。')).toBeNull()
})

it('returns to the same chapter by title after adopting a new template and asks only for the unmatched ones', async () => {
  server.before = 'ready'
  const fetch = serve()
  window.history.replaceState(null, '', '#' + materials)
  render(<CustomerWorkspace />)
  const intro = await screen.findByRole('group', { name: '第一章 绪论' })
  expect(within(intro).queryByText(/章节层级/)).toBeNull()
  fireEvent.change(within(intro).getByLabelText('内容用途'), { target: { value: 'introduction' } })
  fireEvent.change(within(screen.getByRole('group', { name: '第 3 章 研究设计' })).getByLabelText('内容用途'), { target: { value: 'materials_and_methods' } })
  fireEvent.click(within(screen.getByRole('navigation', { name: '资料编排步骤' })).getByRole('button', { name: /方法/ }))
  fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: '运动干预能否改善血脂' } })
  fireEvent.click(within(screen.getByRole('navigation', { name: '资料编排步骤' })).getByRole('button', { name: /来源/ }))
  // The source changed, so the chapters ask for a template again, each with its own way back.
  server.before = 'changed'
  fireEvent.click(screen.getByRole('button', { name: '改用学校模板（完成后回到章节与复核）' }))
  await screen.findByText('正在为“章节与复核”采用学校模板')
  fireEvent.click(screen.getByRole('link', { name: '返回 章节与复核' }))
  fireEvent.click(await screen.findByRole('button', { name: '去采用学校模板（完成后回到第 3 章 研究设计）' }))
  await waitFor(() => expect(window.location.hash).toBe(trip(materials + '&chapter=old-design', '第 3 章 研究设计')))
  expect(await screen.findByRole('link', { name: '返回 第 3 章 研究设计' })).toBeTruthy()
  expect(screen.getByText('正在为“第 3 章 研究设计”采用学校模板')).toBeTruthy()
  expect(screen.getByText('return-place:第 3 章 研究设计')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '继续 写作资料与引用' })).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: '采用这份模板' }))
  const design = await screen.findByRole('group', { name: '第 3 章 研究设计' })
  await waitFor(() => expect(document.activeElement).toBe(design))
  expect(design.id).toBe('thesis-chapter-new-design')
  await waitFor(() => expect(window.location.hash).toBe('#' + materials))
  expect(screen.getByText('已按新采用的模板更新章节，请核对标为待选择的章节。')).toBeTruthy()
  expect(within(screen.getByRole('group', { name: '第一章 绪论' })).getByLabelText('内容用途')).toHaveProperty('value', 'introduction')
  expect(within(design).getByLabelText('内容用途')).toHaveProperty('value', 'materials_and_methods')
  const results = screen.getByRole('group', { name: '第四章 研究结果' })
  expect(within(results).getByText('待选择')).toBeTruthy()
  expect(within(design).queryByText('待选择')).toBeNull()
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.click(within(screen.getByRole('navigation', { name: '资料编排步骤' })).getByRole('button', { name: /方法/ }))
  expect(screen.getByLabelText('研究问题')).toHaveProperty('value', '运动干预能否改善血脂')

  fireEvent.change(within(results).getByLabelText('内容用途'), { target: { value: 'discussion' } })
  expect(within(results).queryByText('待选择')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '预览写作材料' }))
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url === base + '/manuscripts/preview')).toBe(true))
  const body = JSON.parse(String(fetch.mock.calls.find(([url]) => url === base + '/manuscripts/preview')?.[1]?.body))
  expect(body.thesis).toEqual({ confirmation_id: 'confirm2', profile_revision: 3, chapter_mappings: [
    { chapter_id: 'new-intro', purpose: 'introduction', output_language: 'project', result_group_ids: [] },
    { chapter_id: 'new-design', purpose: 'materials_and_methods', output_language: 'project', result_group_ids: [] },
    { chapter_id: 'new-results', purpose: 'discussion', output_language: 'project', result_group_ids: [] },
  ] })
})

it('says the chapter is no longer available when the adopted template has no chapter of that title', async () => {
  Object.assign(server, { before: 'changed', after: 'gone' })
  serve()
  window.history.replaceState(null, '', '#' + materials)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去采用学校模板（完成后回到第 3 章 研究设计）' }))
  fireEvent.click(await screen.findByRole('button', { name: '采用这份模板' }))
  expect(await screen.findByText('原位置已不可用，已回到章节与复核。')).toBeTruthy()
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: '学校章节配置' })))
})

it('leaves both identically titled replacement chapters unassigned and focuses the chapter list', async () => {
  Object.assign(server, { before: 'ready', after: 'duplicate' })
  const fetch = serve()
  window.history.replaceState(null, '', '#' + materials)
  render(<CustomerWorkspace />)
  const original = await screen.findByRole('group', { name: '第 3 章 研究设计' })
  fireEvent.change(within(original).getByLabelText('内容用途'), { target: { value: 'materials_and_methods' } })
  server.before = 'changed'
  fireEvent.click(screen.getByRole('button', { name: '改用学校模板（完成后回到章节与复核）' }))
  fireEvent.click(await screen.findByRole('link', { name: '返回 章节与复核' }))
  fireEvent.click(await screen.findByRole('button', { name: '去采用学校模板（完成后回到第 3 章 研究设计）' }))
  fireEvent.click(await screen.findByRole('button', { name: '采用这份模板' }))
  await screen.findByText('已按新采用的模板更新章节，请核对标为待选择的章节。')
  const matches = screen.getAllByRole('group', { name: '第 3 章 研究设计' })
  expect(matches).toHaveLength(2)
  for (const chapter of matches) {
    expect(within(chapter).getByLabelText('内容用途')).toHaveProperty('value', '')
    expect(within(chapter).getByText('待选择')).toBeTruthy()
  }
  await screen.findByText('原位置已不可用，已回到章节与复核。')
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: '学校章节配置' })))
  expect(fetch.mock.calls.some(([,init]) => init?.method==='POST')).toBe(false)
})

it('drops the chapter token on a step click and ignores one that points to another project', async () => {
  serve()
  window.history.replaceState(null, '', '#' + materials)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '去采用学校模板（完成后回到章节与复核）' }))
  await screen.findByRole('link', { name: '返回 章节与复核' })
  fireEvent.click(within(screen.getByRole('navigation', { name: '毕业论文项目步骤' })).getByRole('button', { name: '学校模板' }))
  await waitFor(() => expect(window.location.hash).toBe(`#customer-project=${project.id}&step=school`))
  expect(screen.queryByRole('link', { name: '返回 章节与复核' })).toBeNull()
  expect(screen.getByText('return-place:')).toBeTruthy()
  // Without a token, adopting stays on the template page and offers the next step.
  fireEvent.click(screen.getByRole('button', { name: '采用这份模板' }))
  expect(window.location.hash).toBe(`#customer-project=${project.id}&step=school`)
  fireEvent.click(screen.getByRole('button', { name: '继续 写作资料与引用' }))
  await waitFor(() => expect(window.location.hash).toBe(`#customer-project=${project.id}&step=materials`))
  cleanup()

  window.history.replaceState(null, '', trip('customer-project=other-project&step=manuscripts&view=materials', '第 3 章'))
  render(<CustomerWorkspace />)
  expect(await screen.findByText('return-place:')).toBeTruthy()
  expect(screen.queryByRole('link', { name: '返回 第 3 章' })).toBeNull()
})

const requirements = (template: { name: string; confirmation_id: string; chapters: typeof oldChapters } | null) => ({
  revision: 2, education_level: '硕士', language: 'zh-CN', school: '北京体育大学', title: '运动干预对中老年人血脂的影响',
  keywords: ['运动', '血脂', '干预', '中老年'], sections: [], template,
})
function serveRequirements(template: Parameters<typeof requirements>[0], fail = false) {
  let saved = requirements(template)
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === base) return Response.json(project)
    if (url === base + '/thesis-requirements') {
      if (init?.method === 'PUT') {
        if (fail) return Response.json({ code: 'internal_error', message: '保存失败' }, { status: 500 })
        saved = { ...saved, revision: saved.revision + 1 }
      }
      return Response.json(saved)
    }
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

it.each([
  ['without an adopted template', null, '保存并继续 学校模板', 'school'],
  ['with an adopted template', { name: 'GS501', confirmation_id: 'confirm1', chapters: oldChapters }, '保存并继续 写作资料与引用', 'materials'],
] as const)('saves the thesis details and continues %s', async (_name, template, action, step) => {
  serveRequirements(template)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=details`)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑毕业论文需求' }))
  fireEvent.change(screen.getByLabelText('论文题目'), { target: { value: '运动干预与血脂' } })
  fireEvent.click(screen.getByRole('button', { name: action }))
  await waitFor(() => expect(window.location.hash).toBe(`#customer-project=${project.id}&step=${step}`))
})

it('stays on the thesis details with the input kept when saving fails', async () => {
  serveRequirements(null, true)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=details`)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑毕业论文需求' }))
  fireEvent.change(screen.getByLabelText('论文题目'), { target: { value: '运动干预与血脂' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并继续 学校模板' }))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(window.location.hash).toBe(`#customer-project=${project.id}&step=details`)
  expect(screen.getByLabelText('论文题目')).toHaveProperty('value', '运动干预与血脂')
})

it.each([[false, 'materials'], [true, 'details']] as const)('saves the SCI details and continues to writing materials (failing: %s)', async (fail, step) => {
  const sci = { ...project, id: 'customer-sci-8', project_type: 'sci' }
  const sciBase = '/api/v1/projects/' + sci.id
  let settings = { article_type: 'narrative_review', proposed_title: '血清指标与预后综述', target_journal: { choice: 'science', name: null },
    keywords: ['血清', '预后', '队列', '综述'], review_sections: [{ id: 'section-1', heading: '文献主题', content: '描述领域现状。' }] }
  let revision = 1
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === sciBase) return Response.json(sci)
    if (url === sciBase + '/sci-settings') {
      if (init?.method === 'PUT') {
        if (fail) return Response.json({ code: 'internal_error', message: '保存失败' }, { status: 500 })
        settings = JSON.parse(String(init.body)).settings
        revision += 1
      }
      return Response.json({ revision, settings })
    }
    if (url.startsWith(sciBase + '/files?') || url.startsWith(sciBase + '/file-batches?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url.startsWith(sciBase + '/paper-materials')) return Response.json({ items: [], targets: [] })
    return new Response(null, { status: 404 })
  }))
  window.history.replaceState(null, '', `#customer-project=${sci.id}&step=details`)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑 SCI 建项资料' }))
  fireEvent.change(screen.getByLabelText('拟定论文题目'), { target: { value: '血清指标与心血管预后' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并继续 写作资料与引用' }))
  if (fail) {
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByLabelText('拟定论文题目')).toHaveProperty('value', '血清指标与心血管预后')
  } else {
    expect(await screen.findByRole('heading', { name: '写作资料与引用', level: 1 })).toBeTruthy()
  }
  expect(window.location.hash).toBe(`#customer-project=${sci.id}&step=${step}`)
})
