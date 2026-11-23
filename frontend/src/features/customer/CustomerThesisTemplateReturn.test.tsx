import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
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
const oldChapters = [{ id: 'old-intro', title: '第一章 绪论', level: 1 }, { id: 'old-design', title: '第 3 章 研究设计', level: 1 }]
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
  ['without an adopted template', null, '保存并继续 上传资料', 'materials'],
  ['with an adopted template', { name: 'GS501', confirmation_id: 'confirm1', chapters: oldChapters }, '保存并继续 上传资料', 'materials'],
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
  fireEvent.click(screen.getByRole('button', { name: '保存并继续 上传资料' }))
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
  fireEvent.click(screen.getByRole('button', { name: '保存并继续上传资料' }))
  if (fail) {
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByLabelText('拟定论文题目')).toHaveProperty('value', '血清指标与心血管预后')
  } else {
    expect(await screen.findByRole('heading', { name: '上传资料', level: 1 })).toBeTruthy()
  }
  expect(window.location.hash).toBe(`#customer-project=${sci.id}&step=${step}`)
})
