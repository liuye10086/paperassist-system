// B05 task 6 (wireframe 18, B05-2): writing materials take a published analysis result from the customer's own
// analysis project and come back to the files view, where a file with the same name shows where it came from.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import CustomerWorkspace from './CustomerWorkspace'

vi.mock('../literature/ProjectLiterature', () => ({ default: () => <p>文献列表</p> }))
const uploadLabel = '批量选择 Excel / Word / 图片文件'

const research = { id: 'ra', name: '分析项目甲', research_topic: '生存', project_type: 'research', file_count: 0,
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z' }
const deliveries = '/api/v1/projects/ra/customer-workspace/deliveries'
const delivery = { id: 's1', delivery_id: 'd1', title: '生存分析', kind: 'analysis', revision: 1,
  published_at: '2026-11-18T08:00:00Z', member_count: 1 }
const file = (id: string, filename: string) => ({ id, filename, file_type: 'docx', size_bytes: 10, uploaded_at: '2026-11-19T00:00:00Z',
  parse_status: 'parsed', error: null, purposes: [], metadata_revision: 1, uploader_recorded: true })

afterEach(() => {
  cleanup()
  clearApiSession()
  setLocale('zh-CN')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', window.location.pathname)
})

describe('published analysis results on the thesis writing materials page', () => {
  const projectId = 'paper-thesis'
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
      if (url === base) return Response.json({ id: projectId, name: '合成论文', project_type: 'thesis', research_topic: '课题',
        file_count: 0, created_at: research.created_at, updated_at: research.updated_at, default_output_language: 'zh-CN' })
      if (url === base + '/thesis-requirements') return Response.json({revision:1,language:'zh-CN',keywords:[],title:'',
        school:'',education_level:'',template:null,sections:[]})
      if (url.startsWith(base + '/file-batches?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
      if (url.startsWith(base + '/files?')) {
        const items = uploaded ? [file('f1', '生存分析.docx'), file('f2', '其他.docx')] : []
        return Response.json({ items, total: items.length, page: 1, page_size: 5 })
      }
      if (url.startsWith(base + '/paper-materials')) {
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
  const writes = () => fetch.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')

  it('takes a result, keeps the chosen upload while away and prefills where a matching file came from', async () => {
    window.history.replaceState(null, '', '#' + files)
    render(<CustomerWorkspace />)
    fireEvent.change(await screen.findByLabelText(uploadLabel), { target: { files: [new File(['bytes'], '待上传说明.docx')] } })
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
    expect(screen.getByText(/待上传说明\.docx/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText(uploadLabel), { target: { files: [] } })
    let finishReadingNotes!: () => void
    notesReady = new Promise<void>(resolve => { finishReadingNotes = resolve })
    uploaded = true
    fireEvent.click(screen.getByRole('button', { name: '刷新资料' }))
    const list = await screen.findByRole('list', { name: '已上传资料' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows[0].textContent).toContain('来自 分析项目甲 · 生存分析')
    expect(rows[1].textContent).not.toContain('来自')
    expect(within(list).queryByRole('button', {name:'添加说明'})).toBeNull()
    fireEvent.click(screen.getByRole('button', {name:'下一步 图件拼版'}))
    fireEvent.click(screen.getByRole('button', {name:'下一步 模板与资料整理'}))
    fireEvent.click(await screen.findByRole('button', {name:'资料整理'}))
    const otherFile = within((await screen.findByText('其他.docx')).closest('li')!)
    const editOtherFile = otherFile.getByRole('button', { name: '添加说明' })
    expect(editOtherFile).toHaveProperty('disabled', true)
    finishReadingNotes()
    await waitFor(() => expect(editOtherFile).toHaveProperty('disabled', false))
    fireEvent.click(editOtherFile)
    expect(await screen.findByRole('textbox', { name: '文件说明（选填）' })).toHaveProperty('value', '')
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    fireEvent.click(within(screen.getByText('生存分析.docx').closest('li')!).getByRole('button', { name: '添加说明' }))
    expect(await screen.findByRole('textbox', { name: '文件说明（选填）' })).toHaveProperty('value', '来自 分析项目甲 · 生存分析')
    expect(writes()).toEqual([])
  })

  it('opens historical paragraph return links on the current upload step', async () => {
    const paragraph = new URLSearchParams({ return: `customer-project=${projectId}&step=manuscripts&view=writing`,
      returnLabel: 'paragraph', returnSection: '讨论', returnParagraph: '2' }).toString()
    window.history.replaceState(null, '', '#' + files + '&' + paragraph)
    render(<CustomerWorkspace />)
    await screen.findByLabelText(uploadLabel)
    expect(screen.getByRole('heading', { name: '上传资料' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '从我的分析项目取用成果' })).toBeTruthy()
  })

  it('drops the token when the customer chooses a step', async () => {
    window.history.replaceState(null, '', target)
    render(<CustomerWorkspace />)
    await screen.findByText('正在为“写作资料”取分析成果')
    fireEvent.click(screen.getByRole('button', { name: '第 2 步：上传资料' }))
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

it('opens a historical SCI results-picker link on the upload page without fetching the named analysis delivery', async () => {
  const projectId = 'paper-sci'
  const base = '/api/v1/projects/' + projectId
  const fetch = vi.fn(async (url: string) => {
    if (url === base) return Response.json({ ...research, id: projectId, project_type: 'sci' })
    if (url.startsWith(base + '/files?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', '#customer-project=' + projectId + '&step=materials&view=analysis-results&analysisProject=ra&analysisSnapshot=s1')
  render(<CustomerWorkspace />)
  await screen.findByRole('button', { name: '下一步 图件拼版' })
  expect(screen.getByRole('heading', { name: '上传资料', level: 1 })).toBeTruthy()
  expect(screen.getByLabelText(uploadLabel)).toBeTruthy()
  expect(screen.queryByRole('button', { name: '从我的分析项目取用成果' })).toBeNull()
  const urls = fetch.mock.calls.map(([url]) => url)
  expect(urls.some(url => url.startsWith('/api/v1/projects?') || url.startsWith(deliveries))).toBe(false)
})
