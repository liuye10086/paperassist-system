// B05 task 6 (wireframe 18, B05-2): writing materials take a published analysis result from the customer's own
// analysis project and come back to the files view, where a file with the same name shows where it came from.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import CustomerWorkspace from './CustomerWorkspace'

vi.mock('../files/BatchUpload', () => ({ default: () => <input aria-label="模拟已选文件" defaultValue="" /> }))
vi.mock('../literature/ProjectLiterature', () => ({ default: () => <p>文献列表</p> }))

const research = { id: 'ra', name: '分析项目甲', research_topic: '生存', project_type: 'research', file_count: 0,
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z' }
const deliveries = '/api/v1/projects/ra/customer-workspace/deliveries'
const delivery = { id: 's1', delivery_id: 'd1', title: '生存分析', kind: 'analysis', revision: 1,
  published_at: '2026-11-18T08:00:00Z', member_count: 1 }
const file = (id: string, filename: string) => ({ id, filename, file_type: 'docx', size_bytes: 10, uploaded_at: '2026-11-19T00:00:00Z',
  parse_status: 'parsed', error: null, purposes: [], metadata_revision: 1, uploader_recorded: true })
const settings = { article_type: 'research', proposed_title: 'Planned article', target_journal: { choice: 'science', name: null },
  keywords: ['lineage'], findings: [] }

describe.each(['sci', 'thesis'] as const)('analysis results for writing materials (%s)', projectType => {
  const projectId = 'paper-' + projectType
  const base = '/api/v1/projects/' + projectId
  const files = `customer-project=${projectId}&step=materials&view=files`
  const target = '#' + new URLSearchParams({ 'customer-project': projectId, step: 'materials', view: 'analysis-results',
    return: files, returnLabel: 'materials' }).toString()
  let uploaded = false
  let notesReady: Promise<void>
  let fetch: ReturnType<typeof vi.fn>

  beforeEach(() => {
    uploaded = false
    notesReady = Promise.resolve()
    setApiSession('csrf', 'customer-test')
    sessionStorage.clear()
    vi.stubGlobal('URL', class extends URL { static createObjectURL = vi.fn(() => 'blob:x'); static revokeObjectURL = vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    fetch = vi.fn(async (url: string) => {
      if (url === base) return Response.json({ id: projectId, name: '合成论文', project_type: projectType, research_topic: '课题',
        file_count: 0, created_at: research.created_at, updated_at: research.updated_at, default_output_language: 'zh-CN' })
      if (url === base + '/sci-settings') return Response.json({ settings, revision: 1 })
      if (url === base + '/thesis-requirements') return Response.json({ keywords: [] })
      if (url.startsWith(base + '/files?')) {
        const items = uploaded ? [file('f1', '生存分析.docx'), file('f2', '其他.docx')] : []
        return Response.json({ items, total: items.length, page: 1, page_size: 5 })
      }
      if (url.startsWith(base + '/paper-materials?')) {
        await notesReady
        return Response.json({ items: [], targets: [{ id: 't1', label: '发现 1' }] })
      }
      if (url.startsWith('/api/v1/projects?type=research')) return Response.json({ items: [research], total: 1, page: 1, page_size: 100 })
      if (url === deliveries) return Response.json({ items: [delivery] })
      if (url === deliveries + '/s1') return Response.json({ ...delivery, feedback: [], package_url: null,
        members: [{ id: 'w1', name: '生存分析.docx', format: 'docx', size_bytes: 10, download_url: deliveries + '/s1/members/w1/download' }] })
      if (url.endsWith('/members/w1/download')) return new Response('bytes')
      return new Response(null, { status: 404 })
    })
    vi.stubGlobal('fetch', fetch)
  })
  afterEach(() => {
    cleanup()
    clearApiSession()
    setLocale('zh-CN')
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    window.history.replaceState(null, '', window.location.pathname)
  })
  const writes = () => fetch.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')

  it('takes a result, keeps the chosen upload while away and prefills where a matching file came from', async () => {
    window.history.replaceState(null, '', '#' + files)
    render(<CustomerWorkspace />)
    fireEvent.change(await screen.findByLabelText('模拟已选文件'), { target: { value: '已选 生存分析.docx' } })
    fireEvent.click(screen.getByRole('button', { name: '从我的分析项目取用成果' }))
    await waitFor(() => expect(window.location.hash).toBe(target))
    expect(await screen.findByText('正在为“写作资料”取分析成果')).toBeTruthy()
    expect(screen.getByRole('link', { name: '返回 写作资料' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '从我的分析项目取用成果' })).toBeNull()
    fireEvent.click(await screen.findByRole('button', { name: /分析项目甲 · 生存分析/ }))
    await waitFor(() => expect(window.location.hash).toContain('analysisProject=ra&analysisSnapshot=s1'))
    fireEvent.click(await screen.findByRole('link', { name: '下载 生存分析.docx' }))
    expect(await screen.findByText('下载所需文件后，可以返回 写作资料 继续上传。')).toBeTruthy()

    fireEvent.click(screen.getByRole('link', { name: '返回 写作资料' }))
    await waitFor(() => expect(window.location.hash).toBe('#' + files))
    // Focus comes back to the writing materials instead of dropping to the page body.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: '从我的分析项目取用成果' })))
    expect(screen.getByLabelText('模拟已选文件')).toHaveProperty('value', '已选 生存分析.docx')
    let finishReadingNotes!: () => void
    notesReady = new Promise<void>(resolve => { finishReadingNotes = resolve })
    uploaded = true
    fireEvent.click(screen.getByRole('button', { name: '刷新资料' }))
    const list = await screen.findByRole('list', { name: '已上传资料' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows[0].textContent).toContain('来自 分析项目甲 · 生存分析')
    expect(rows[1].textContent).not.toContain('来自')
    const editOtherFile = within(rows[1]).getByRole('button', { name: '填写 其他.docx 的图表资料' })
    expect(editOtherFile).toHaveProperty('disabled', true)
    finishReadingNotes()
    await waitFor(() => expect(editOtherFile).toHaveProperty('disabled', false))
    fireEvent.click(editOtherFile)
    expect(await screen.findByRole('textbox', { name: '主要结果' })).toHaveProperty('value', '')
    fireEvent.click(screen.getByRole('button', { name: '返回项目文件' }))
    fireEvent.click(await screen.findByRole('button', { name: '填写 生存分析.docx 的图表资料' }))
    expect(await screen.findByRole('textbox', { name: '主要结果' })).toHaveProperty('value', '来自 分析项目甲 · 生存分析')
    expect(writes()).toEqual([])
  })

  it('has no entry while a paragraph waits for a source', async () => {
    const paragraph = new URLSearchParams({ return: `customer-project=${projectId}&step=manuscripts&view=writing`,
      returnLabel: 'paragraph', returnSection: '讨论', returnParagraph: '2' }).toString()
    window.history.replaceState(null, '', '#' + files + '&' + paragraph)
    render(<CustomerWorkspace />)
    await screen.findByLabelText('模拟已选文件')
    expect(screen.getByRole('link', { name: '返回 讨论第 2 段' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '从我的分析项目取用成果' })).toBeNull()
  })

  it('drops the token when the customer chooses a step', async () => {
    window.history.replaceState(null, '', target)
    render(<CustomerWorkspace />)
    await screen.findByText('正在为“写作资料”取分析成果')
    fireEvent.click(screen.getByRole('button', { name: '写作资料与引用' }))
    await waitFor(() => expect(window.location.hash).toBe(`#customer-project=${projectId}&step=materials`))
    expect(screen.queryByText('正在为“写作资料”取分析成果')).toBeNull()
    expect(await screen.findByRole('button', { name: '从我的分析项目取用成果' })).toBeTruthy()
  })

  it('has English for the entry', async () => {
    setLocale('en')
    window.history.replaceState(null, '', '#' + files)
    render(<CustomerWorkspace />)
    expect(await screen.findByRole('button', { name: 'Use results from my analysis projects' })).toBeTruthy()
  })
})
