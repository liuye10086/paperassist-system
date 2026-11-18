import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { exportFixture, manuscriptFixture } from '../manuscripts/manuscriptFixtures'
import { emptyProfile, type Profile } from '../school-templates/contracts'
import CustomerFeedback from './CustomerFeedback'
import CustomerProjectCreate from './CustomerProjectCreate'
import CustomerWorkspace from './CustomerWorkspace'
import { customerBase, type Feedback } from './customerWorkspaceApi'

const project = {
  id: 'customer-project-1', name: '客户项目样例', research_topic: '比较病例与对照',
  project_type: 'research', file_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
}
const base = '/api/v1/projects/' + project.id
const customer = customerBase(project.id)
const delivery = {
  id: 'released-1', kind: 'analysis', title: '已发布演示成果', revision: 1,
  member_count: 1, published_at: project.created_at,
}
const memberUrl = customer + '/deliveries/released-1/members/figure-1/download'

beforeEach(() => { setApiSession('csrf', 'customer-test'); sessionStorage.clear() })
afterEach(() => {
  cleanup()
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it.each([
  ['sci', '写作资料与引用'],
  ['thesis', '写作资料与引用'],
  ['research', '上传资料'],
])('opens the original file list link in a %s project', async (projectType, heading) => {
  window.history.replaceState(null, '', `#project=${project.id}&section=files`)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === base) return Response.json({ ...project, project_type: projectType })
    if (url === base + '/sci-settings') return Response.json({ settings: null, revision: 1 })
    if (url === base + '/thesis-requirements') return Response.json({ revision: 0, language: 'zh-CN', title: '', keywords: [], sections: [], template: null })
    if (url.startsWith(base + '/files?')) return Response.json({ items: [{ id: 'file-1', filename: '历史材料.xlsx', file_type: 'xlsx', parse_status: 'parsed' }], total: 1, page: 1, page_size: 5 })
    if (url.startsWith(base + '/paper-materials')) return Response.json({ items: [], targets: [] })
    return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
  }))

  render(<CustomerWorkspace />)

  await screen.findByRole('heading', { name: heading, level: 1 })
  expect(await screen.findByText('历史材料.xlsx')).toBeTruthy()
})

it('creates a customer project, opens five steps, and sends feedback on a published delivery', async () => {
  const feedback: Feedback[] = []
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith('/api/v1/projects?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url === '/api/v1/projects' && init?.method === 'POST') return Response.json(project, { status: 201 })
    if (url === base) return Response.json(project)
    if (url === customer + '/progress') return Response.json({
      status: 'needs_materials', requirement_version: 1, submitted_at: project.created_at,
      updated_at: project.updated_at, note: '请补充样本分组表。', feedback: [],
    })
    if (url.startsWith(base + '/files?')) {
      const page = Number(new URL(url, 'http://testserver').searchParams.get('page'))
      return Response.json({ items: [{ id: `file-${page}`, filename: `资料-${page}.xlsx`, parse_status: 'stored' }],
        total: 6, page, page_size: 5 })
    }
    if (url.startsWith(base + '/file-batches?')) {
      return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    }
    if (url === customer + '/deliveries') return Response.json({ items: [delivery] })
    if (url === customer + '/deliveries/released-1') return Response.json({
      ...delivery, members: [{ id: 'figure-1', name: 'heatmap.png', format: 'png', size_bytes: 1000, download_url: memberUrl }],
      package_url: null, feedback,
    })
    if (url === customer + '/feedback' && init?.method === 'POST') {
      const entry = { id: 'feedback-1', message: JSON.parse(String(init.body)).message, created_at: project.created_at }
      feedback.push(entry)
      return Response.json(entry, { status: 201 })
    }
    return Response.json({ detail: { code: 'project_not_found' } }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  render(<CustomerWorkspace />)
  expect(screen.queryByRole('heading', { name: '我的项目' })).toBeNull()
  const projectPager = screen.getByRole('navigation', { name: '项目分页' })
  expect(Array.from(projectPager.children, child => child.textContent)).toEqual(['上一页', '共 0 个项目 · 第 1 / 1 页', '下一页'])
  fireEvent.click(screen.getByRole('button', { name: '新建项目' }))
  const dialog = screen.getByRole('dialog', { name: '新建项目' })
  expect(within(dialog).getByLabelText('项目名称').closest('form')?.classList.contains('project-form')).toBe(true)
  fireEvent.change(within(dialog).getByLabelText('项目名称'), { target: { value: project.name } })
  fireEvent.change(within(dialog).getByLabelText('研究目标'), { target: { value: project.research_topic } })
  fireEvent.click(within(dialog).getByRole('button', { name: '创建项目' }))
  const detailsHeading = await screen.findByRole('heading', { name: '项目资料', level: 1 })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(screen.getByRole('textbox', { name: '修改项目名称' })).toHaveProperty('value', project.name)
  expect(document.activeElement).toBe(detailsHeading)
  const stepper = screen.getByRole('navigation', { name: '项目操作步骤' })
  expect(within(stepper).getAllByRole('button')).toHaveLength(5)
  expect(within(stepper).queryByRole('button', { name: /执行分析/ })).toBeNull()
  const [, create] = fetch.mock.calls.find(([url]) => url === '/api/v1/projects')!
  expect(new Headers(create?.headers).get('Idempotency-Key')).toBeTruthy()
  expect(JSON.parse(String(create?.body))).toMatchObject({
    name: project.name, research_topic: project.research_topic, project_type: 'research', delivery_kinds: ['analysis'],
  })
  fireEvent.click(within(stepper).getByRole('button', { name: /任务进度/ }))
  const progressHeading = await screen.findByRole('heading', { name: '任务进度', level: 1 })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(document.activeElement).toBe(progressHeading)
  await screen.findByText('待补资料')
  expect(screen.getByText('请补充样本分组表。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '补交资料' }))
  const uploadHeading = await screen.findByRole('heading', { name: '上传资料', level: 1 })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(document.activeElement).toBe(uploadHeading)
  const filePager = await screen.findByRole('navigation', { name: '文件分页' })
  expect(Array.from(filePager.children, child => child.textContent)).toEqual(['上一页', '第 1 / 2 页 · 共 6 个文件', '下一页'])
  fireEvent.click(within(filePager).getByRole('button', { name: '下一页' }))
  await screen.findByText('资料-2.xlsx')
  expect(within(await screen.findByRole('navigation', { name: '文件分页' })).getByText('第 2 / 2 页 · 共 6 个文件')).toBeTruthy()
  fireEvent.click(within(stepper).getByRole('button', { name: /查看交付/ }))
  const deliveriesHeading = await screen.findByRole('heading', { name: '已发布交付', level: 1 })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(document.activeElement).toBe(deliveriesHeading)
  fireEvent.click(await screen.findByRole('button', { name: '查看交付 已发布演示成果' }))
  expect((await screen.findByRole('link', { name: '下载 heatmap.png' })).getAttribute('href')).toBe(memberUrl)
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: delivery.title, level: 1 }))
  fireEvent.change(screen.getByRole('textbox', { name: '反馈内容' }), { target: { value: '热图配色清晰。' } })
  fireEvent.click(screen.getByRole('button', { name: '发送反馈' }))
  await screen.findByText('反馈已发送。')
  await screen.findByText('热图配色清晰。')
  const [, sent] = fetch.mock.calls.find(([url]) => url === customer + '/feedback')!
  expect(JSON.parse(String(sent?.body))).toEqual({ message: '热图配色清晰。', snapshot_id: delivery.id })
  expect(new Headers(sent?.headers).get('Idempotency-Key')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '返回交付列表' }))
  expect(document.activeElement).toBe(await screen.findByRole('button', { name: '查看交付 已发布演示成果' }))
})

it('preserves Back and Forward after a cancelled departure from an upload', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === base) return Response.json(project)
    const items = url.startsWith('/api/v1/projects?') ? [project] : []
    return Response.json({ items, total: items.length, page: 1, page_size: 5 })
  }))
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '打开项目 ' + project.name }))
  const details = window.location.hash
  fireEvent.click(await screen.findByRole('button', { name: '下一步 上传资料' }))
  const upload = window.location.hash
  const input = await screen.findByLabelText('批量选择 Excel / Word / PDF / 图片 文件')
  fireEvent.change(input, { target: { files: [new File(['sample'], 'sample.xlsx')] } })

  await act(async () => window.history.back())
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(window.location.hash).toBe(upload))
  expect(screen.getByText(/sample\.xlsx/)).toBeTruthy()

  await act(async () => window.history.back())
  await waitFor(() => expect(window.location.hash).toBe(details))
  await screen.findByRole('button', { name: '下一步 上传资料' })
  await act(async () => window.history.forward())
  await waitFor(() => expect(window.location.hash).toBe(upload))
  await screen.findByLabelText('批量选择 Excel / Word / PDF / 图片 文件')
})

it('keeps a foreign project address outside the customer steps and delivery API', async () => {
  window.history.replaceState(null, '', '#customer-project=foreign&step=deliveries')
  const fetch = vi.fn(async () => Response.json({ detail: { code: 'project_not_found' } }, { status: 404 }))
  vi.stubGlobal('fetch', fetch)
  render(<CustomerWorkspace />)
  await screen.findByText('项目不存在或无权访问。')
  expect(screen.queryByRole('navigation', { name: '项目操作步骤' })).toBeNull()
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  expect(fetch).toHaveBeenCalledWith('/api/v1/projects/foreign', expect.anything())
})

it('validates SCI inputs, creates a review project, and reads its saved SCI settings', async () => {
  const sci = { ...project, id: 'sci-project', project_type: 'sci' }
  const settings = {
    article_type: 'narrative_review', proposed_title: '单细胞研究的文献综述',
    target_journal: { choice: 'science', name: null },
    keywords: ['RNA-seq', '细胞分化', '单细胞', '转录组'],
    review_sections: [{ id: 'section-1', heading: '文献主题', content: '描述领域现状。' }],
  }
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith('/api/v1/projects?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url === '/api/v1/projects' && init?.method === 'POST') return Response.json(sci, { status: 201 })
    if (url === '/api/v1/projects/sci-project') return Response.json(sci)
    if (url === '/api/v1/projects/sci-project/sci-settings') return Response.json({ revision: 1, settings })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  render(<CustomerWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: '新建项目' }))
  const dialog = within(screen.getByRole('dialog'))
  fireEvent.change(dialog.getByLabelText('项目类型'), { target: { value: 'sci' } })
  fireEvent.change(dialog.getByLabelText('项目名称'), { target: { value: sci.name } })
  fireEvent.change(dialog.getByLabelText('研究目标'), { target: { value: sci.research_topic } })
  fireEvent.click(dialog.getByRole('button', { name: '创建项目' }))
  expect(dialog.getByRole('alert').textContent).toContain('请选择论文类型。')
  expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  fireEvent.change(dialog.getByLabelText('论文类型'), { target: { value: 'narrative_review' } })
  fireEvent.change(dialog.getByLabelText('拟定论文题目'), { target: { value: settings.proposed_title } })
  fireEvent.click(dialog.getByRole('radio', { name: 'Science' }))
  for (const keyword of settings.keywords) {
    fireEvent.change(dialog.getByLabelText('关键词'), { target: { value: ` ${keyword} ` } })
    fireEvent.click(dialog.getByRole('button', { name: '添加关键词' }))
  }
  expect(dialog.queryByLabelText('主要结果或结论')).toBeNull()
  fireEvent.click(dialog.getByRole('button', { name: '添加小标题' }))
  fireEvent.change(dialog.getByLabelText('小标题'), { target: { value: '文献主题' } })
  fireEvent.change(dialog.getByLabelText('需要涵盖的内容'), { target: { value: '描述领域现状。' } })
  fireEvent.click(dialog.getByRole('button', { name: '创建项目' }))
  expect(await screen.findByText('描述领域现状。')).toBeTruthy()
  expect(screen.queryByRole('navigation', { name: '项目操作步骤' })).toBeNull()
  const [, create] = fetch.mock.calls.find(([url]) => url === '/api/v1/projects')!
  const sections = [{ ...settings.review_sections[0], id: expect.any(String) }]
  expect(JSON.parse(String(create?.body))).toMatchObject({ project_type: 'sci', sci_settings: { ...settings, review_sections: sections } })
  expect(JSON.parse(String(create?.body))).not.toHaveProperty('delivery_kinds')
})

it('creates a thesis with its own requirements after switching away from an SCI draft', async () => {
  const thesis = { ...project, project_type: 'thesis' }
  const requirements = { education_level: '硕士', school: '合成大学', title: '单细胞表达特征', keywords: ['单细胞', '表达', '分群', '验证'] }
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => Response.json(thesis, { status: 201 }))
  const created = vi.fn()
  vi.stubGlobal('fetch', fetch)
  render(<CustomerProjectCreate onCreated={created} onClose={vi.fn()} />)
  const type = screen.getByLabelText('项目类型')
  fireEvent.change(type, { target: { value: 'sci' } })
  fireEvent.change(screen.getByLabelText('拟定论文题目'), { target: { value: 'Saved SCI draft' } })
  fireEvent.change(type, { target: { value: 'thesis' } })
  expect(screen.queryByLabelText('拟定论文题目')).toBeNull()
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: thesis.name } })
  fireEvent.change(screen.getByLabelText('研究目标'), { target: { value: thesis.research_topic } })
  fireEvent.click(screen.getByRole('button', { name: '创建项目' }))
  expect(screen.getByRole('alert').textContent).toContain('请选择学位层次。')
  expect(fetch).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('学位层次'), { target: { value: requirements.education_level } })
  fireEvent.change(screen.getByLabelText('论文语种'), { target: { value: 'en' } })
  fireEvent.change(screen.getByLabelText('学校名称'), { target: { value: requirements.school } })
  fireEvent.change(screen.getByLabelText('论文题目'), { target: { value: requirements.title } })
  for (const word of requirements.keywords) {
    fireEvent.change(screen.getByLabelText('关键词'), { target: { value: word } })
    fireEvent.click(screen.getByRole('button', { name: '添加关键词' }))
  }
  fireEvent.click(screen.getByRole('button', { name: '创建项目' }))
  await waitFor(() => expect(created).toHaveBeenCalledWith(thesis))
  const [, init] = fetch.mock.calls[0]
  expect(JSON.parse(String(init?.body))).toEqual({
    name: thesis.name, research_topic: thesis.research_topic, project_type: 'thesis', default_output_language: 'en',
    thesis_requirements: requirements,
  })
})

it('opens an existing published analysis delivery from an older paper project', async () => {
  const legacy = { ...project, project_type: 'thesis', has_analysis_history: true }
  const fetch = vi.fn(async (url: string) => {
    if (url === base) return Response.json(legacy)
    if (url === customer + '/deliveries') return Response.json({ items: [delivery] })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=deliveries`)
  render(<CustomerWorkspace />)
  expect(await screen.findByRole('heading', { name: '已发布交付' })).toBeTruthy()
  expect(await screen.findByText(delivery.title)).toBeTruthy()
  expect(screen.queryByRole('navigation', { name: '项目操作步骤' })).toBeNull()
})

it('confirms and explicitly binds a Word school template from the thesis customer workspace', async () => {
  let profile: Profile = emptyProfile
  let templateCreated = false
  let confirmed = false
  const template = {
    id: 'template-old', name: '合成毕业论文模板', school: '合成大学', version_label: '2026',
    analysis_sha256: 'a'.repeat(64), task: { id: 'template-task', status: 'succeeded' },
    sources: [{ id: 'template-source', role: 'template', file_id: 'template-word', filename: '论文模板.docx' }],
    analysis: {
      chapters: [{ id: 'chapter-1', title: '第 1 章 绪论', level: 1 }],
      rules: [{ id: 'rule-1', label: '正文字体', value: '宋体' }],
      sections: [], notes: [], missing: ['发布日期未注明'], unsupported: ['手写签名待核对'],
      identity_fields: [{ label: '作者签名', required: true }],
      conflicts: [{ id: 'size', label: '正文字号冲突', options: [{ id: 'body-size', value: '12 磅' }] }],
    },
  }
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (url === base) return Response.json({ ...project, project_type: 'thesis' })
    if (url === base + '/thesis-profile') {
      if (init?.method === 'PUT') {
        const { expected_revision, ...fields } = body
        profile = { ...profile, ...fields, revision: expected_revision + 1 }
      }
      return Response.json(profile)
    }
    if (url.startsWith(base + '/files?')) return Response.json({
      items: [
        { id: 'template-word', filename: '论文模板.docx', parse_status: 'parsed' },
        { id: 'historical-pdf', filename: '旧项目规范.pdf', parse_status: 'parsed' },
      ], total: 2, page: 1, page_size: 50,
    })
    if (url.startsWith(base + '/file-batches?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url === base + '/school-templates') {
      const item = { ...template, confirmation: confirmed ? { id: 'rules-1', chapters: template.analysis.chapters } : null }
      if (init?.method === 'POST') {
        templateCreated = true
        return Response.json(item, { status: 202 })
      }
      return Response.json({ items: templateCreated ? [item] : [] })
    }
    if (url === base + '/school-templates/template-old/confirm') {
      confirmed = true
      return Response.json({ id: 'rules-1' }, { status: 201 })
    }
    if (url === base + '/thesis-template-binding') {
      profile = { ...profile, revision: profile.revision + 1, bound_confirmation_id: body.confirmation_id }
      return Response.json(profile)
    }
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=school`)
  render(<CustomerWorkspace />)
  const steps = await screen.findByRole('navigation', { name: '毕业论文项目步骤' })
  expect(within(steps).getByRole('button', { name: '学校模板' }).getAttribute('aria-current')).toBe('step')
  fireEvent.click(screen.getByRole('button', { name: '学校资料' }))
  const school = screen.getByRole('textbox', { name: '学校' })
  await waitFor(() => expect(school.matches(':disabled')).toBe(false))
  fireEvent.change(school, { target: { value: '合成大学' } })
  fireEvent.change(screen.getByRole('textbox', { name: '学位类型' }), { target: { value: '硕士' } })
  fireEvent.change(screen.getByRole('textbox', { name: '适用年份 / 版本' }), { target: { value: '2026' } })
  fireEvent.click(screen.getByRole('button', { name: '保存学校资料' }))
  await waitFor(() => expect(profile).toMatchObject({ school: '合成大学', degree_type: '硕士', revision: 1 }))
  fireEvent.click(screen.getByRole('button', { name: '新建模板版本' }))
  const picker = screen.getByLabelText('批量选择 DOCX 文件')
  expect(picker.getAttribute('accept')).toBe('.docx')
  fireEvent.change(picker, { target: { files: [new File(['test'], '旧项目规范.pdf')] } })
  fireEvent.click(screen.getByRole('button', { name: '开始上传' }))
  expect(screen.getByRole('alert').textContent).toContain('学校模板和补充规范请选择 DOCX 文件。')
  expect(fetch.mock.calls.some(([url, init]) => url === base + '/file-batches' && init?.method === 'POST')).toBe(false)
  fireEvent.change(picker, { target: { files: [] } })
  await within(screen.getByLabelText('模板 DOCX 原件')).findByRole('option', { name: '论文模板.docx' })
  expect(within(screen.getByLabelText('补充规范 DOCX')).queryByRole('option', { name: '旧项目规范.pdf' })).toBeNull()
  fireEvent.change(screen.getByLabelText('模板 DOCX 原件'), { target: { value: 'template-word' } })
  fireEvent.click(screen.getByRole('button', { name: '提交模板解析' }))
  await screen.findByRole('heading', { name: '合成毕业论文模板' })
  fireEvent.click(screen.getByRole('button', { name: '解析规则' }))
  expect(screen.getByText('发布日期未注明')).toBeTruthy()
  expect(screen.getByText('作者签名')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '规则确认' }))
  const confirm = screen.getByRole('button', { name: '确认模板规则' })
  expect(confirm.matches(':disabled')).toBe(true)
  fireEvent.change(screen.getByLabelText('正文字号冲突'), { target: { value: 'body-size' } })
  fireEvent.click(confirm)
  expect(profile.bound_confirmation_id).toBeNull()
  fireEvent.click(await screen.findByRole('button', { name: '绑定此确认版本' }))
  await waitFor(() => expect(profile.bound_confirmation_id).toBe('rules-1'))
  expect(await screen.findByText('当前绑定版本', { selector: 'strong' })).toBeTruthy()
  expect(fetch.mock.calls.every(([url]) => !url.includes('rule-suggestion') && !url.includes('/tasks/'))).toBe(true)
  const call = fetch.mock.calls.find(([url]) => url.endsWith('/confirm'))!
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    decisions: [{ conflict_id: 'size', option_id: 'body-size' }],
    chapters: template.analysis.chapters,
  })
})

it('carries a selected thesis result source into a confirmed results chapter', async () => {
  const profile = { ...emptyProfile, school: '合成大学', revision: 2, bound_confirmation_id: 'rules-1' }
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === base) return Response.json({ ...project, project_type: 'thesis' })
    if (url === base + '/manuscripts/candidates') return Response.json({
      items: [{ kind: 'original', id: 'thesis-result', file_id: 'thesis-result', label: '结果记录.docx',
        version: null, allowed_roles: ['user_results'], download_url: null }],
      citation_drafts: [], methods_fields: [], project_type: 'thesis',
      thesis: {
        ready: true, blocking_reasons: [], profile, confirmation_id: 'rules-1',
        chapters: [{ id: 'results-chapter', title: '实验结果', level: 1 }], purposes: ['results'], template_source_file_ids: [],
      },
    })
    if (url === base + '/manuscripts' && !init?.method) return Response.json({ items: [] })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=manuscripts`)
  render(<CustomerWorkspace />)
  expect(await screen.findByRole('heading', { name: '章节与复核', level: 1 })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '整理事实稿资料' }))
  const chapter = await screen.findByRole('group', { name: '实验结果' })
  fireEvent.change(within(chapter).getByLabelText('内容用途'), { target: { value: 'results' } })
  fireEvent.click(screen.getByRole('checkbox', { name: '结果记录.docx' }))
  const materials = screen.getByRole('navigation', { name: '资料编排步骤' })
  fireEvent.click(within(materials).getByRole('button', { name: '结果' }))
  fireEvent.change(screen.getByLabelText('用户提供的主要结果'), { target: { value: '合成实验记录共 24 份。' } })
  fireEvent.click(screen.getByRole('checkbox', { name: '关联结果来源 结果记录.docx' }))
  fireEvent.click(within(materials).getByRole('button', { name: '来源' }))
  fireEvent.click(within(chapter).getByRole('checkbox', { name: '用户提供的结果与出处' }))
  fireEvent.click(screen.getByRole('button', { name: '预览事实稿' }))
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url === base + '/manuscripts/preview')).toBe(true))
  const preview = JSON.parse(String(fetch.mock.calls.find(([url]) => url === base + '/manuscripts/preview')?.[1]?.body))
  expect(preview).toMatchObject({
    reported_result: { text: '合成实验记录共 24 份。', source_ids: ['thesis-result'] },
    thesis: { confirmation_id: 'rules-1', profile_revision: 2, chapter_mappings: [
      { chapter_id: 'results-chapter', purpose: 'results', result_group_ids: ['reported-result'] },
    ] },
  })
})

it.each(['research', 'narrative_review'] as const)('carries %s project settings into the SCI manuscript entry', async article_type => {
  const settings = {
    article_type, main_results: '项目主要发现，仅供写作参考',
    target_journal: { choice: 'other', name: 'Synthetic Journal' },
    keywords: ['single-cell', 'lineage'], figure_plan: [{ title: '图 1', description: '细胞分化示意' }],
  }
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === base) return Response.json({ ...project, project_type: 'sci' })
    if (url === base + '/sci-settings') return Response.json({ settings, revision: 1 })
    if (url === base + '/manuscripts/candidates') return Response.json({
      items: [
        { kind: 'original', id: 'uploaded-1', file_id: 'uploaded-1', label: '合成结果 Word', version: null,
          allowed_roles: ['user_results'], download_url: null },
        { kind: 'original', id: 'legacy-pdf', file_id: 'legacy-pdf', label: '历史来源.pdf', version: null,
          allowed_roles: ['user_results'], download_url: null },
        { kind: 'document_version', id: 'legacy-parse', file_id: 'legacy-pdf', label: '历史来源解析', version: 1,
          allowed_roles: ['user_results'], download_url: null },
      ],
      citation_drafts: [], methods_fields: [],
    })
    if (url === base + '/manuscripts' && !_init?.method) return Response.json({ items: [] })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=manuscripts`)
  render(<CustomerWorkspace />)
  await screen.findByRole('heading', { name: '稿件与复核', level: 1 })
  expect(await screen.findByText(settings.main_results, { selector: 'dd' })).toBeTruthy()
  expect(screen.getByText('细胞分化示意')).toBeTruthy()
  expect(screen.getByText('single-cell · lineage', { selector: 'dd' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '任务进度' })).toBeNull()
  expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: '整理事实稿资料' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: '合成结果 Word' }))
  expect(screen.queryByRole('checkbox', { name: /^历史来源/ })).toBeNull()
  if (article_type === 'research') {
    fireEvent.click(screen.getByRole('button', { name: /结果/ }))
    expect(screen.getByLabelText('用户提供的主要结果')).toHaveProperty('value', settings.main_results)
    fireEvent.click(screen.getByRole('checkbox', { name: '关联结果来源 合成结果 Word' }))
  } else {
    expect(screen.queryByRole('button', { name: /结果/ })).toBeNull()
  }
  fireEvent.click(screen.getByRole('button', { name: '预览事实稿' }))
  await waitFor(() => expect(fetch.mock.calls.some(([url, init]) => url === base + '/manuscripts/preview' && init?.method === 'POST')).toBe(true))
  const submitted = JSON.parse(String(fetch.mock.calls.find(([url]) => url === base + '/manuscripts/preview')?.[1]?.body))
  if (article_type === 'research') expect(submitted.reported_result).toEqual({ text: settings.main_results, source_ids: ['uploaded-1'] })
  else expect(submitted).not.toHaveProperty('reported_result')
})

it.each(['research', 'thesis'] as const)('does not fetch SCI modules from a %s deep link', async project_type => {
  const fetch = vi.fn(async (url: string) => {
    if (url === base) return Response.json({ ...project, project_type })
    if (project_type === 'thesis' && url === base + '/thesis-requirements') {
      return Response.json({ revision: 0, education_level: '', language: 'zh-CN', school: '', title: '', keywords: [], sections: [], template: null })
    }
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=journals`)
  render(<CustomerWorkspace />)
  await screen.findByRole('heading', { name: '项目资料', level: 1 })
  expect(screen.queryByRole('heading', { name: '期刊适配与 Word' })).toBeNull()
  const expectedRequests = project_type === 'thesis' ? [base, base + '/thesis-requirements'] : [base]
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(expectedRequests)
})

it('shows the saved journal intent with a generic Word route and no submission history fetch', async () => {
  const settings = {
    article_type: 'narrative_review', main_results: '综述结论',
    target_journal: { choice: 'other', name: 'Synthetic Journal' },
    keywords: ['lineage'], figure_plan: [{ title: '图 1', description: '主题关系' }],
  }
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === base) return Response.json({ ...project, project_type: 'sci' })
    if (url === base + '/sci-settings') return Response.json({ settings, revision: 2 })
    if (url.endsWith('/journals/config')) return Response.json({ default_limit: 3, max_limit: 10 })
    return Response.json({ items: [] })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=journals`)
  render(<CustomerWorkspace />)
  await screen.findByRole('heading', { name: '期刊适配与 Word', level: 1 })
  expect((await screen.findByText('Synthetic Journal')).closest('section')?.textContent).toContain('目标期刊意向')
  expect(screen.queryByRole('button', { name: '投稿记录' })).toBeNull()
  expect(fetch.mock.calls.every(([url, init]) => url.startsWith(base) && !url.endsWith('/submission-events') && !init?.method)).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '通用 Word 与固定版本' }))
  await screen.findByRole('heading', { name: '固定版本与 Word', level: 1 })
  expect(window.location.hash).toContain('step=word')
})

it('loads Word for the selected historical SCI version without requesting optional exports', async () => {
  const download_url = base + '/manuscripts/m1/exports/export1/download'
  const old = { ...manuscriptFixture.versions[0], snapshot: { ...manuscriptFixture.versions[0].snapshot, project_id: project.id },
    exports: [{ ...exportFixture, download_url }] }
  const current = { ...old, id: 'v2', revision: 2, task_id: 'draft-2', parent_version_id: old.id, exports: [] }
  const fetch = vi.fn(async (url: string) => {
    if (url === base) return Response.json({ ...project, project_type: 'sci' })
    if (url === base + '/manuscripts') return Response.json({
      items: [{ ...manuscriptFixture, project_id: project.id, current_revision: 2, versions: [current, old] }],
    })
    if (url === base + '/manuscripts/m1/versions/1/exports') return Response.json({ items: old.exports })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=word`)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '查看版本 1' }))
  expect(await screen.findByText('固定版本 1')).toBeTruthy()
  expect((await screen.findByRole('link', { name: '下载 DOCX' })).getAttribute('href')).toBe(download_url)
  expect(screen.queryByRole('link', { name: /PDF|交付登记/ })).toBeNull()
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([base, base + '/manuscripts', base + '/manuscripts/m1/versions/1/exports'])
})

it('accepts Word, Excel and images including TIFF in the SCI upload picker without creating a PDF batch', async () => {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === base) return Response.json({ ...project, project_type: 'sci' })
    if (url === base + '/sci-settings') return Response.json({ settings: null, revision: 0 })
    return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=materials`)
  render(<CustomerWorkspace />)
  const upload = await screen.findByLabelText('批量选择 Excel / Word / 图片文件')
  expect(upload.getAttribute('accept')).toBe('.xlsx,.docx,.png,.jpg,.jpeg,.tif,.tiff')
  fireEvent.change(upload, { target: { files: [new File(['test'], 'not-a-fact-source.pdf')] } })
  fireEvent.click(screen.getByRole('button', { name: '开始上传' }))
  expect(screen.getByRole('alert').textContent).toContain('SCI 写作资料请选择 Word、Excel 或图片。')
  expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})

it('recovers the original project by idempotency key when creation receipt was lost', async () => {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === '/api/v1/projects') throw new TypeError('Response lost')
    return Response.json(project)
  })
  const created = vi.fn()
  vi.stubGlobal('fetch', fetch)
  render(<CustomerProjectCreate onCreated={created} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: project.name } })
  fireEvent.change(screen.getByLabelText('研究目标'), { target: { value: project.research_topic } })
  fireEvent.click(screen.getByRole('button', { name: '创建项目' }))
  const retry = await screen.findByRole('button', { name: '重试创建项目' })
  const [, request] = fetch.mock.calls[0]
  const key = new Headers(request?.headers).get('Idempotency-Key')
  expect(key).toBeTruthy()
  fireEvent.click(retry)
  await waitFor(() => expect(created).toHaveBeenCalledWith(project))
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/v1/projects', `/api/v1/project-create-requests/${key}`])
})

it('keeps the feedback draft and idempotency key after an invalid success receipt', async () => {
  const entry = { id: 'saved', message: '请补充颜色说明。', created_at: project.created_at }
  const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>()
    .mockResolvedValueOnce(new Response('<html></html>'))
    .mockResolvedValueOnce(Response.json(entry))
  vi.stubGlobal('fetch', fetch)
  const saved = vi.fn()
  render(<CustomerFeedback projectId={project.id} entries={[]} onSaved={saved} />)
  const input = screen.getByRole('textbox', { name: '反馈内容' }) as HTMLTextAreaElement
  fireEvent.change(input, { target: { value: entry.message } })
  fireEvent.click(screen.getByRole('button', { name: '发送反馈' }))
  await screen.findByText('反馈发送结果待确认，请重试原请求。')
  expect(input.value).toBe(entry.message)
  expect(saved).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '重试发送反馈' }))
  await screen.findByText('反馈已发送。')
  expect(saved).toHaveBeenCalledOnce()
  const [first, second] = fetch.mock.calls.map(([, init]) => new Headers(init?.headers).get('Idempotency-Key'))
  expect(first).toBeTruthy()
  expect(second).toBe(first)
})
