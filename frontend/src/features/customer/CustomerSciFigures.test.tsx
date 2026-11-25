import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import CustomerSciFigures from './CustomerSciFigures'

const base = '/api/v1/projects/p1'
const png = {id:'png-file', filename:'image.png', file_type:'png'}
const tiff = {id:'tiff-file', filename:'blot.tif', file_type:'tiff'}
const jpeg = {id:'jpeg-file', filename:'replacement.jpg', file_type:'jpeg'}
const page = <T,>(items: T[], number = 1, total = items.length) => ({items, page:number, page_size:20, total})
const figure = (status: 'queued' | 'succeeded', projectType: 'sci' | 'thesis' = 'sci') => ({id:'version1', root_id:'root1', revision:1, parent_id:null,
  config:{title:'实验组图', mode:'composite', columns:1, panels:[
    {label:'A', source:{source_id:tiff.id, source_kind:'original_file'}}, {label:'B', source:{source_id:png.id, source_kind:'original_file'}},
  ]}, task:{id:'task1', status}, task_id:'task1', manifest:null,
  members:status === 'succeeded' ? [{id:'view', key:'figure.png', role:'preview', format:'png', download_url:base + `/${projectType}-figures/version1/members/view/download`}] : [],
})

function serve(projectType: 'sci' | 'thesis') {
  let saved = false
  let failed = false
  const endpoint = base + `/${projectType}-figures`
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === endpoint && init?.method === 'POST') {
      if (!failed) { failed = true; return Response.json({detail:{code:'server_error'}}, {status:500}) }
      saved = true
      return Response.json(figure('queued', projectType))
    }
    if (url.startsWith(endpoint + '?')) return Response.json({page:1, page_size:20, total:Number(saved), items:saved ? [figure('succeeded', projectType)] : []})
    if (url === endpoint + '/version1') return Response.json(figure('succeeded', projectType))
    if (url.startsWith(endpoint + '/assembly?')) {
      const number = Number(new URL(url, 'https://test.example').searchParams.get('page'))
      return Response.json({available:saved ? page([]) : page(number === 1 ? [png] : [tiff], number, 21),
        groups:page([]), has_pending:false})
    }
    if (url === base + '/files/png-file/download' || url === base + '/files/tiff-file/image-preview' || url === figure('succeeded', projectType).members[0].download_url) {
      return new Response('fixture image', {headers:{'Content-Type':'image/png'}})
    }
    throw new Error(`Unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:figure')
    static revokeObjectURL = vi.fn()
  })
  render(<CustomerSciFigures projectType={projectType} projectId="p1" registerLeaveGuard={() => () => {}} onContinue={vi.fn()} />)
  return fetcher
}

afterEach(() => {cleanup(); vi.unstubAllGlobals()})

it.each(['sci','thesis'] as const)('groups used %s originals and releases removed ones after successful revision', async projectType => {
  const endpoint = base + `/${projectType}-figures`
  let phase: 'original' | 'generating' | 'updated' = 'original'
  const ready = {revision:1, title:'实验组图', columns:1, originals:[tiff, png]}
  const current = {...ready, revision:2, originals:[tiff, jpeg]}
  const queued = {...figure('queued', projectType), revision:2, id:'version2',
    config:{...figure('queued', projectType).config, panels:[
      {label:'A', source:{source_id:tiff.id}}, {label:'B', source:{source_id:jpeg.id}},
    ]}}
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith(endpoint + '/assembly?')) {
      return Response.json({available:page(phase === 'original' ? [jpeg] : phase === 'updated' ? [png] : []),
        groups:page([{root_id:'root1', latest_revision:phase === 'original' ? 1 : 2,
          current:phase === 'updated' ? current : ready, pending_title:phase === 'generating' ? ready.title : null,
          pending_originals:phase === 'generating' ? [tiff, jpeg] : []}]),
        has_pending:phase === 'generating'})
    }
    if (url === endpoint && init?.method === 'POST') {
      phase = 'generating'
      return Response.json(queued, {status:201})
    }
    if (url.startsWith(endpoint + '?')) return Response.json(page([queued]))
    if (url === endpoint + '/version2') return Response.json({...queued,
      task:{...queued.task, status:phase === 'updated' ? 'succeeded' : 'running'}})
    if (url.startsWith(base + '/files/')) return new Response('fixture image', {headers:{'Content-Type':'image/png'}})
    throw new Error(`Unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:figure')
    static revokeObjectURL = vi.fn()
  })
  render(<CustomerSciFigures projectType={projectType} projectId="p1" registerLeaveGuard={() => () => {}} onContinue={vi.fn()} />)
  const unused = within(screen.getByRole('region', {name:'待拼原图'}))
  const used = within(screen.getByRole('region', {name:'已拼图'}))
  await unused.findByRole('checkbox', {name:jpeg.filename})
  expect(unused.queryByRole('checkbox', {name:png.filename})).toBeNull()
  expect(await used.findByText(png.filename)).toBeTruthy()
  expect(used.queryByRole('checkbox')).toBeNull()

  fireEvent.click(used.getByRole('button', {name:'编辑 实验组图'}))
  fireEvent.click(screen.getByRole('button', {name:`移除 ${png.filename}`}))
  expect(used.getByRole('checkbox', {name:png.filename})).toHaveProperty('checked', false)
  fireEvent.click(unused.getByRole('checkbox', {name:jpeg.filename}))
  fireEvent.click(screen.getByRole('button', {name:'保存修改'}))
  await screen.findByText('正图正在生成，完成后可在资源配置中选用。')
  const post = fetcher.mock.calls.find(([url, init]) => url === endpoint && init?.method === 'POST')
  expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({root_id:'root1', expected_revision:1, file_ids:[tiff.id,jpeg.id]})

  const editTab = screen.getByRole('button', {name:'编辑拼版'})
  fireEvent.click(editTab)
  await screen.findByText('暂无待拼原图。')
  expect(screen.getByRole('button', {name:'编辑 实验组图'})).toHaveProperty('disabled', true)
  phase = 'updated'
  fireEvent.click(editTab)
  const refreshed = within(screen.getByRole('region', {name:'待拼原图'}))
  await refreshed.findByRole('checkbox', {name:png.filename})
  expect(refreshed.queryByRole('checkbox', {name:jpeg.filename})).toBeNull()
})

it.each([
  {projectType:'sci', draft:'another layout'},
  {projectType:'thesis', draft:'this layout'},
] as const)('returns every original after cancelling a $projectType layout while editing $draft', async ({projectType, draft}) => {
  const endpoint = base + `/${projectType}-figures`
  const saved = figure('succeeded', projectType)
  const group = {root_id:saved.root_id, latest_revision:2,
    current:{revision:1, title:saved.config.title, columns:1, originals:[tiff, png]},
    pending_title:null, pending_originals:[]}
  let cancelled = false
  let sendAssembly!: (response: Response) => void
  const refreshedAssembly = new Promise<Response>(resolve => { sendAssembly = resolve })
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith(endpoint + '/assembly?')) {
      if (cancelled) return refreshedAssembly
      return Response.json({available:page([jpeg]), groups:page([group]), has_pending:false})
    }
    if (url.startsWith(endpoint + '?')) return Response.json(page(cancelled ? [] : [saved]))
    if (url === endpoint + '/version1') return Response.json(saved)
    if (url === endpoint + '/root1/cancel' && init?.method === 'POST') {
      cancelled = true
      return new Response(null, {status:204})
    }
    if (url.startsWith(base + '/files/') || url === saved.members[0].download_url) {
      return new Response('fixture image', {headers:{'Content-Type':'image/png'}})
    }
    throw new Error(`Unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('confirm', vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true))
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:figure')
    static revokeObjectURL = vi.fn()
  })
  render(<CustomerSciFigures projectType={projectType} projectId="p1" registerLeaveGuard={() => () => {}} onContinue={vi.fn()} />)
  const savedTab = screen.getByRole('button', {name:'已保存正图'})
  fireEvent.click(savedTab)
  fireEvent.click(await screen.findByRole('button', {name:/实验组图.*已完成/}))
  await screen.findByRole('img', {name:'预览 实验组图'})
  fireEvent.click(screen.getByRole('button', {name:'编辑拼版'}))
  const unused = within(screen.getByRole('region', {name:'待拼原图'}))
  const used = within(screen.getByRole('region', {name:'已拼图'}))
  const availableOriginal = await unused.findByRole('checkbox', {name:jpeg.filename})
  await waitFor(() => expect(availableOriginal).toHaveProperty('disabled', false))
  fireEvent.click(draft === 'this layout' ? used.getByRole('button', {name:'编辑 实验组图'}) : availableOriginal)
  const draftTitle = '本地修改'
  fireEvent.change(screen.getByRole('textbox', {name:'正图名称'}), {target:{value:draftTitle}})

  const cancelButton = used.getByRole('button', {name:'取消拼版 实验组图'})
  fireEvent.click(cancelButton)
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  fireEvent.click(cancelButton)

  await unused.findByRole('status')
  expect(unused.queryByRole('checkbox')).toBeNull()
  expect(used.queryByText('实验组图')).toBeNull()
  const post = fetcher.mock.calls.find(([url]) => url === endpoint + '/root1/cancel')
  expect(post?.[1]?.method).toBe('POST')
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({expected_revision:2})
  sendAssembly(Response.json({available:page([tiff, png, jpeg]), groups:page([]), has_pending:false}))
  await unused.findByRole('checkbox', {name:tiff.filename})
  expect(unused.getByRole('checkbox', {name:png.filename})).toHaveProperty('checked', false)
  expect(unused.getByRole('checkbox', {name:jpeg.filename})).toHaveProperty('checked', draft === 'another layout')
  if (draft === 'this layout') expect(screen.queryByRole('textbox', {name:'正图名称'})).toBeNull()
  else expect(screen.getByRole('textbox', {name:'正图名称'})).toHaveProperty('value', draftTitle)

  fireEvent.click(savedTab)
  expect(screen.queryByRole('button', {name:/实验组图.*已完成/})).toBeNull()
  await screen.findByText('此项目还没有保存正图。')
})

it.each(['当前行', '已保存正图', '已拼图下一页'])('can cancel an edit from %s', async location => {
  const endpoint = base + '/sci-figures'
  const saved = figure('succeeded')
  const group = {root_id:saved.root_id, latest_revision:1,
    current:{revision:1, title:saved.config.title, columns:1, originals:[tiff, png]},
    pending_title:null, pending_originals:[]}
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') throw new Error(`Unexpected write ${url}`)
    if (url.startsWith(endpoint + '/assembly?')) {
      const groupPage = url.includes('group_page=2') ? 2 : 1
      return Response.json({available:page([]), groups:page(groupPage === 1 ? [group] : [], groupPage, 21), has_pending:false})
    }
    if (url.startsWith(endpoint + '?')) return Response.json(page([{...saved, latest_revision:1}]))
    if (url === endpoint + '/version1') return Response.json(saved)
    if (url.startsWith(base + '/files/') || url === saved.members[0].download_url) {
      return new Response('fixture image', {headers:{'Content-Type':'image/png'}})
    }
    throw new Error(`Unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:figure')
    static revokeObjectURL = vi.fn()
  })
  const confirm = vi.fn()
  vi.stubGlobal('confirm', confirm)
  render(<CustomerSciFigures projectId="p1" registerLeaveGuard={() => () => {}} onContinue={vi.fn()} />)

  const edit = await screen.findByRole('button', {name:'编辑 实验组图'})
  fireEvent.click(edit)
  expect(screen.getByRole('button', {name:'取消编辑 实验组图'})).toBe(edit)
  expect(edit.textContent).toBe('取消')
  expect(edit).toHaveProperty('disabled', false)
  expect(screen.queryByRole('button', {name:'取消修改'})).toBeNull()

  if (location !== '当前行') fireEvent.change(screen.getByRole('textbox', {name:'正图名称'}), {target:{value:'本地修改'}})
  if (location === '已保存正图') {
    fireEvent.click(screen.getByRole('button', {name:'已保存正图'}))
    expect((await screen.findByRole('button', {name:/实验组图.*已完成/})).getAttribute('aria-pressed')).toBe('true')
  }
  if (location === '已拼图下一页') {
    fireEvent.click(within(screen.getByRole('navigation', {name:'已拼图分页'})).getByRole('button', {name:'下一页'}))
    await screen.findByText('第 2 / 2 页')
  }

  fireEvent.click(screen.getByRole('button', {name:'取消编辑 实验组图'}))
  expect(confirm).not.toHaveBeenCalled()
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  expect(screen.queryByRole('button', {name:'取消编辑 实验组图'})).toBeNull()
  expect(screen.queryByRole('textbox', {name:'正图名称'})).toBeNull()
  if (location !== '已拼图下一页') expect(screen.getByRole('button', {name:'编辑 实验组图'}).textContent).toBe('编辑')
})

it.each([
  {projectType:'sci', status:'succeeded'},
  {projectType:'thesis', status:'failed'},
] as const)('keeps the selected $projectType figure in one row when the update is $status', async ({projectType, status}) => {
  const endpoint = base + `/${projectType}-figures`
  const prior = {...figure('succeeded', projectType), latest_revision:2}
  const queued = {...figure('queued', projectType), id:'version3', revision:3, parent_id:'version2',
    config:{...prior.config, title:'更新后的实验组图'}}
  const result = {...queued, task:{...queued.task, status}, members:status === 'succeeded'
    ? prior.members.map(member => ({...member, download_url:member.download_url.replace('/version1/', '/version3/')})) : []}
  let finish!: (response: Response) => void
  const detail = new Promise<Response>(resolve => { finish = resolve })
  let finished = false
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith(endpoint + '/assembly?')) return Response.json({available:page([]), groups:page([]), has_pending:false})
    if (url.startsWith(endpoint + '?')) return Response.json(page([finished
      ? {...(status === 'succeeded' ? result : prior), latest_revision:3} : prior]))
    if (url === endpoint + '/version1') return Response.json(prior)
    if (url === endpoint + '/version3') return detail
    if (url === endpoint && init?.method === 'POST') return Response.json(queued, {status:201})
    if (url.startsWith(base + '/files/') || url.includes('/members/')) return new Response('fixture image', {headers:{'Content-Type':'image/png'}})
    throw new Error(`Unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:figure')
    static revokeObjectURL = vi.fn()
  })
  render(<CustomerSciFigures projectType={projectType} projectId="p1" registerLeaveGuard={() => () => {}} onContinue={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', {name:'已保存正图'}))
  fireEvent.click(await screen.findByRole('button', {name:/实验组图.*已完成/}))
  await screen.findByRole('img', {name:'预览 实验组图'})
  fireEvent.click(screen.getByRole('button', {name:'编辑 实验组图'}))
  fireEvent.change(screen.getByRole('textbox', {name:'正图名称'}), {target:{value:queued.config.title}})
  fireEvent.click(screen.getByRole('button', {name:'保存修改'}))

  await screen.findByText('正图正在生成，完成后可在资源配置中选用。')
  expect(screen.getAllByRole('button', {name:/实验组图.*(待执行|已完成)/})).toHaveLength(1)
  expect(screen.getByRole('button', {name:/更新后的实验组图.*待执行/}).getAttribute('aria-pressed')).toBe('true')
  const post = fetcher.mock.calls.find(([url, init]) => url === endpoint && init?.method === 'POST')
  expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({root_id:prior.root_id, expected_revision:2})
  finished = true
  finish(Response.json(result))

  const completed = status === 'succeeded' ? result : prior
  await screen.findByRole('img', {name:`预览 ${completed.config.title}`})
  expect(screen.getAllByRole('button', {name:/实验组图.*已完成/})).toHaveLength(1)
  expect(screen.getByRole('button', {name:`${completed.config.title} 已完成`}).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('link', {name:`下载 ${completed.config.title}（PNG）`}).getAttribute('href')).toBe(completed.members[0].download_url)
  expect(screen.queryByText(/第 \d+ 版|基于第/)).toBeNull()
  if (status === 'failed') expect((await screen.findByRole('alert')).textContent).toBe('正图更新失败。仍可使用上一次生成的正图。')
})

it('keeps the group in place and disables cancellation after a concurrent revision starts', async () => {
  const endpoint = base + '/sci-figures'
  const current = {revision:1, title:'实验组图', columns:1, originals:[tiff, png]}
  let generating = false
  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith(endpoint + '/assembly?')) {
      return Response.json({available:page([]), groups:page([{root_id:'root1', latest_revision:generating ? 2 : 1, current,
        pending_title:generating ? '新版本' : null, pending_originals:generating ? [tiff, png] : []}]), has_pending:generating})
    }
    if (url === endpoint + '/root1/cancel' && init?.method === 'POST') {
      generating = true
      return Response.json({detail:{code:'research_revision_conflict'}}, {status:409})
    }
    throw new Error(`Unexpected request ${url}`)
  }))
  render(<CustomerSciFigures projectId="p1" registerLeaveGuard={() => () => {}} onContinue={vi.fn()} />)
  const used = within(screen.getByRole('region', {name:'已拼图'}))
  const unused = within(screen.getByRole('region', {name:'待拼原图'}))
  fireEvent.click(await used.findByRole('button', {name:'取消拼版 实验组图'}))
  expect((await used.findByRole('alert')).textContent).toBe('此正图已有更新或正在生成。请核对最新列表后重试。')
  await used.findByText('生成中')
  expect(used.getByRole('button', {name:'取消拼版 实验组图'})).toHaveProperty('disabled', true)
  expect(unused.queryByRole('checkbox')).toBeNull()
})

it('refreshes the library and drops only the original claimed by another tab', async () => {
  const endpoint = base + '/sci-figures'
  let otherTabSaved = false
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith(endpoint + '/assembly?')) {
      const claimed = {root_id:'elsewhere', latest_revision:1, current:null, pending_title:'另一张正图', pending_originals:[png]}
      return Response.json({available:page(otherTabSaved ? [jpeg] : [png, jpeg]),
        groups:page(otherTabSaved ? [claimed] : []), has_pending:otherTabSaved})
    }
    if (url === endpoint && init?.method === 'POST') {
      otherTabSaved = true
      return Response.json({detail:{code:'paper_figure_original_in_use', params:{file_ids:[png.id]}}}, {status:409})
    }
    if (url.startsWith(base + '/files/')) return new Response('fixture image', {headers:{'Content-Type':'image/png'}})
    throw new Error(`Unexpected request ${url}`)
  }))
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:figure')
    static revokeObjectURL = vi.fn()
  })
  render(<CustomerSciFigures projectId="p1" registerLeaveGuard={() => () => {}} onContinue={vi.fn()} />)
  fireEvent.click(await screen.findByRole('checkbox', {name:png.filename}))
  fireEvent.click(screen.getByRole('checkbox', {name:jpeg.filename}))
  fireEvent.click(screen.getByRole('button', {name:'保存为正图'}))
  expect(await screen.findByText('所选原图已用于其他正图或正在拼版，请重新选择。')).toBeTruthy()
  await screen.findByText('另一张正图')
  expect(screen.queryByRole('checkbox', {name:png.filename})).toBeNull()
  expect(screen.queryByRole('button', {name:`移除 ${png.filename}`})).toBeNull()
  expect(screen.getByRole('checkbox', {name:jpeg.filename})).toHaveProperty('checked', true)
})

it.each(['sci','thesis'] as const)('selects supported %s originals across pages, reorders panel labels, and retries the same save', async projectType => {
  const fetcher = serve(projectType)
  const original = await screen.findByRole('checkbox', {name:'image.png'})
  expect(screen.queryByText('实验笔记.docx')).toBeNull()
  fireEvent.click(original)
  fireEvent.click(within(screen.getByRole('navigation', {name:'原图分页'})).getByRole('button', {name:'下一页'}))
  fireEvent.click(await screen.findByRole('checkbox', {name:'blot.tif'}))
  const layout = screen.getByRole('combobox', {name:'拼版布局'})
  fireEvent.change(layout, {target:{value:'vertical'}})
  const grid = screen.getByRole('list', {name:'拼版预览'})
  const handle = screen.getByRole('button', {name:'拖动 blot.tif'})
  const dataTransfer = {setData:vi.fn(), effectAllowed:'', dropEffect:''}
  fireEvent.dragStart(handle, {dataTransfer})
  fireEvent.dragOver(grid.children[0], {dataTransfer})
  fireEvent.drop(grid.children[0], {dataTransfer})
  expect(grid.children[0].textContent).toContain('A')
  expect(grid.children[0].textContent).toContain('blot.tif')
  fireEvent.keyDown(handle, {key:'ArrowDown'})
  expect(grid.children[0].textContent).toContain('image.png')
  fireEvent.keyDown(handle, {key:'ArrowUp'})
  expect(grid.children[1].textContent).toContain('B')
  expect(grid.children[1].textContent).toContain('image.png')
  await within(grid).findByRole('img', {name:'预览 blot.tif'})
  expect(fetcher.mock.calls.some(([url]) => url === base + '/files/tiff-file/image-preview')).toBe(true)
  fireEvent.change(screen.getByRole('textbox', {name:'正图名称'}), {target:{value:'实验组图'}})
  fireEvent.click(screen.getByRole('button', {name:'保存为正图'}))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', {name:'保存为正图'}))
  await screen.findByRole('img', {name:'预览 实验组图'})
  expect(screen.getByRole('button', {name:/实验组图.*已完成/})).toBeTruthy()
  expect(screen.getByRole('link', {name:'下载 实验组图（PNG）'}).getAttribute('href')).toBe(figure('succeeded', projectType).members[0].download_url)
  const posts = fetcher.mock.calls.filter(([url, init]) => url === base + `/${projectType}-figures` && init?.method === 'POST')
  expect(posts).toHaveLength(2)
  expect(JSON.parse(String(posts[1][1]?.body))).toEqual({title:'实验组图', file_ids:[tiff.id,png.id], columns:1})
  expect(new Headers(posts[0][1]?.headers).get('Idempotency-Key')).toBeTruthy()
  expect(new Headers(posts[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(posts[1][1]?.headers).get('Idempotency-Key'))
})

it('allows moving to the template with no figures selected', async () => {
  const next = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({available:page([]), groups:page([]), has_pending:false})))
  render(<CustomerSciFigures projectId="p1" registerLeaveGuard={() => () => {}} onContinue={next} />)
  fireEvent.click(await screen.findByRole('button', {name:'下一步 模板设定和资源配置'}))
  await waitFor(() => expect(next).toHaveBeenCalledTimes(1))
})

it('saves an original directly and waits for that saved figure before continuing', async () => {
  const next = vi.fn()
  const single = {...figure('queued'), config:{title:'image', mode:'reuse', columns:1,
    panels:[{label:'', source:{source_id:png.id, source_kind:'original_file'}}]}}
  let finish!: (response: Response) => void
  const detail = new Promise<Response>(resolve => { finish = resolve })
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith(base + '/sci-figures/assembly?')) return Response.json({available:page([png]), groups:page([]), has_pending:false})
    if (url === base + '/files/png-file/download') return new Response('fixture image', {headers:{'Content-Type':'image/png'}})
    if (url === base + '/sci-figures' && init?.method === 'POST') return Response.json(single, {status:201})
    if (url.startsWith(base + '/sci-figures?')) return Response.json({page:1, page_size:20, total:1, items:[single]})
    if (url === base + '/sci-figures/version1') return detail
    throw new Error(`Unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn(() => 'blob:figure')
    static revokeObjectURL = vi.fn()
  })
  render(<CustomerSciFigures projectId="p1" registerLeaveGuard={() => () => {}} onContinue={next} />)
  fireEvent.click(await screen.findByRole('checkbox', {name:png.filename}))
  expect(screen.queryByRole('combobox', {name:'拼版布局'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'保存为正图'}))
  await screen.findByText('正图正在生成，完成后可在资源配置中选用。')
  const continueButton = screen.getByRole('button', {name:'下一步 模板设定和资源配置'})
  expect(continueButton).toHaveProperty('disabled', true)
  const post = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({title:'image', file_ids:[png.id], columns:1})
  finish(Response.json({...single, task:{id:'task1', status:'succeeded'}}))
  await waitFor(() => expect(continueButton).toHaveProperty('disabled', false))
  fireEvent.click(continueButton)
  expect(next).toHaveBeenCalledOnce()
})
