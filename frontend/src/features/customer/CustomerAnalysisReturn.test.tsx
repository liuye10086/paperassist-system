// B05 task 5 (wireframe 17, B05-1): an opinion that needs an analysis result sends the customer to the analysis
// results inside the paper project and back to the same opinion, where a new upload is only an unsaved draft.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import ReviewsWorkspace from '../reviews/ReviewsWorkspace'
import { taskFixture } from '../tasks/taskFixtures'
import CustomerWorkspace from './CustomerWorkspace'

const uploader = vi.hoisted(() => ({ real: false }))
vi.mock('../files/BatchUpload', async importOriginal => {
  const { default: Upload } = await importOriginal<typeof import('../files/BatchUpload')>()
  return { default: (props: Parameters<typeof Upload>[0]) => uploader.real ? <Upload {...props} /> :
    <button type="button" onClick={() => props.onChanged(['fnew'])}>模拟上传完成</button> }
})

const projectId = 'paper-review'
const base = '/api/v1/projects/' + projectId
const reviews = base + '/reviews'
const address = '#customer-project=' + projectId + '&step='
const sourceId = 'f2a6939b-b706-4037-b294-68b106ebd602'
const task = {
  ...taskFixture, id: 'review-task', project_id: projectId, task_type: 'review_round_plan', phase: 'verify', status: 'succeeded',
  display_status: 'succeeded', error_code: null, reason_code: null,
  input_version: { kind: 'review_round_plan', round_id: 'round1', base_version_id: 'v1', workflow_version: 'review_round_plan_v1' },
}
const opinion = (number: number, needs: { kind: string; description: string }[]) => ({
  id: `${sourceId}:${number}`, source_id: sourceId, number, original_number: String(number), original_text: '意见原文 ' + number,
  source_location: null, revision: 1, status: 'waiting_material', uncompleted_reason: '', decision: null, category: 'method',
  locations: [], translation: null, plan: '', evidence_ids: [], needs, flags: [], conflicting_item_ids: [],
  proposed_action: 'modify', not_adopt_reason: '',
})
const analysisItem = opinion(1, [{ kind: 'analysis', description: '补充生存分析' }, { kind: 'literature', description: '补充文献' }])
const materialItem = opinion(2, [{ kind: 'material', description: '补充原始记录' }])
const round = {
  id: 'round1', project_id: projectId, title: '一审意见', project_type: 'sci', round_number: 1, revision: 1, synthetic: false,
  manuscript: { id: 'm1', revision: 1, version_id: 'v1', title: '送审稿' },
  sources: [{ id: sourceId, role: 'reviewer', label: '审稿人 1', format: 'text', original_text: '原文', segments: [], warnings: [] }],
  items: [analysisItem, materialItem], materials: [], constraints: { school_confirmation_id: null, journal_target_id: null },
  versions: [], decisions: [], task, wait: null, created_at: task.created_at, real_model_calls: false, real_network_calls: false,
}
const research = { id: 'ra', name: '分析项目甲', research_topic: '生存', project_type: 'research', file_count: 0,
  created_at: task.created_at, updated_at: task.updated_at }
const deliveries = '/api/v1/projects/ra/customer-workspace/deliveries'
const delivery = { id: 's1', delivery_id: 'd1', title: '生存分析', kind: 'analysis', revision: 1,
  published_at: '2026-11-18T08:00:00Z', member_count: 1 }
const newDocument = { file_id: 'fnew', filename: '生存分析.docx', document_version_id: 'pnew', version: 1, kind: 'docx_document' }
const itemParam = encodeURIComponent(analysisItem.id)
const origin = `customer-project=${projectId}&step=reviews&view=supplements&round=round1&item=${itemParam}`
const target = '#' + new URLSearchParams({ 'customer-project': projectId, step: 'reviews', view: 'analysis-results',
  return: new URLSearchParams(origin).toString(), returnLabel: 'review-item', returnRound: '1', returnItem: '1' }).toString()

let uploaded = false
const secondRound = { ...round, id: 'round2', round_number: 2,
  task: { ...task, input_version: { ...task.input_version, round_id: 'round2' } } }
let fetch: ReturnType<typeof vi.fn>
beforeEach(() => {
  uploader.real = false
  uploaded = false
  setApiSession('csrf', 'customer-test')
  sessionStorage.clear()
  vi.stubGlobal('URL', class extends URL { static createObjectURL = vi.fn(() => 'blob:x'); static revokeObjectURL = vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === base) return Response.json({ id: projectId, name: '合成客户论文', project_type: 'sci', research_topic: '定向验证',
      file_count: 0, created_at: task.created_at, updated_at: task.updated_at, default_output_language: 'zh-CN' })
    if (url === reviews + '/inputs') return Response.json({ project_type: 'sci', manuscripts: [{ id: 'm1', title: '送审稿', current_revision: 1,
      versions: [{ id: 'v1', revision: 1, status: 'published', title: '送审稿' }] }],
      documents: uploaded ? [newDocument] : [], journal_targets: [], school_confirmations: [] })
    if (url === reviews + '/rounds') return Response.json({ items: [round, secondRound] })
    if (url === reviews + '/rounds/round1/plans' && init?.method === 'POST') return Response.json({ ...round, revision: 2 })
    if (url === reviews + '/rounds/round1') return Response.json(round)
    if (url === reviews + '/rounds/round2') return Response.json(secondRound)
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

it.each(['stay', 'reopen', 'visit another opinion'])('preselects this opinion’s actual batch file after parsing (%s)', async navigation => {
  uploader.real = true
  const ordinary = fetch.getMockImplementation()!
  const batches = base + '/file-batches'
  const batchItem = { id: '', ordinal: 0, filename: newDocument.filename, size_bytes: 1, status: 'pending', file_id: null as string | null, task: null, error: null }
  const batch = { id: 'accepted-batch', project_id: projectId, created_at: task.created_at, revision: 1, items: [batchItem] }
  const old = { ...batch, id: 'previous-batch', items: [{ ...batchItem, id: 'older-item', status: 'parsed', file_id: 'old-same-name' }] }
  fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === reviews + '/inputs') {
      const response = await ordinary(url, init)
      const inputs = await response.json()
      inputs.documents.push({ ...newDocument, file_id: 'old-same-name', document_version_id: 'old-version' })
      return Response.json(inputs)
    }
    if (url === batches && init?.method === 'POST') {
      batchItem.id = JSON.parse(String(init.body)).items[0].client_id
      return Response.json(batch)
    }
    if (url.startsWith(batches + '/accepted-batch/items/')) {
      batch.revision = 2; batchItem.status = 'queued'; batchItem.file_id = 'fnew'
      return Response.json(batchItem)
    }
    if (url === batches + '/accepted-batch') return Response.json(batch)
    if (url.startsWith(batches+'?')) {
      const items = batchItem.id ? [batch, old] : [old]
      return Response.json({ items, total: items.length, page: 1, page_size: 5 })
    }
    return ordinary(url, init)
  })
  window.history.replaceState(null, '', '#' + origin)
  const page = render(<CustomerWorkspace />)
  const start = await screen.findByRole('button', { name: '开始上传' })
  const upload = within(start.closest('section')!)
  fireEvent.change(start.closest('section')!.querySelector('input[type=file]')!, { target: { files: [new File(['x'],newDocument.filename)] } })
  fireEvent.click(start)
  await upload.findByText(/已保存，等待解析/)
  const visitOpinion = (hash: string) => act(() => {
    window.history.replaceState(null, '', '#' + hash)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
  if (navigation === 'reopen') {
    page.unmount()
    render(<CustomerWorkspace />)
  } else if (navigation === 'visit another opinion') {
    visitOpinion(origin.replace(itemParam,encodeURIComponent(materialItem.id)))
    await screen.findByText('为 第 1 轮 · 意见 2 上传')
  }
  await screen.findByRole('button', { name: '重新读取批次' })
  uploaded = true; batchItem.status = 'parsed'; batch.revision = 4
  fireEvent.click(screen.getByRole('button', { name: '重新读取批次' }))
  if (navigation === 'visit another opinion') {
    await waitFor(()=>expect(screen.getAllByText(/已解析 1 \/ 1/)).toHaveLength(2))
    expect(screen.queryByRole('button', {name:'查看并保存处理计划'})).toBeNull()
    visitOpinion(origin)
  }
  const plan = await screen.findByRole('button', { name: '查看并保存处理计划' })
  expect(writes().filter(([url])=>url.startsWith(reviews))).toHaveLength(0)
  fireEvent.click(plan)
  const boxes=screen.getAllByRole('checkbox',{name:/生存分析\.docx/})
  expect(boxes).toHaveLength(3)
  expect(boxes.filter(box=>(box as HTMLInputElement).checked)).toHaveLength(2)
  fireEvent.click(screen.getByRole('button',{name:'保存本轮计划修改'}))
  await waitFor(()=>expect(writes().filter(([url])=>url.endsWith('/round1/plans'))).toHaveLength(1))
  const saved=JSON.parse(String(writes().find(([url])=>url.endsWith('/round1/plans'))![1].body))
  expect(saved.materials).toEqual([{kind:'document_version',file_id:'fnew',id:'pnew'}])
  expect(saved.items.find((item:{id:string})=>item.id===analysisItem.id).evidence_ids).toEqual(['pnew'])
  expect(saved.items.find((item:{id:string})=>item.id===materialItem.id).evidence_ids).toEqual([])
})
const science = () => screen.findByRole('heading', { name: '分析材料补充' })
const article = (name: RegExp) => screen.getAllByRole('article').find(item => name.test(item.querySelector('h4')?.textContent ?? ''))!

it('labels opinions waiting for an analysis result and offers the analysis trip only for them', async () => {
  window.history.replaceState(null, '', address + 'reviews&view=science&round=round1')
  render(<CustomerWorkspace />)
  await science()
  const analysis = await waitFor(() => article(/意见 1/))
  expect(analysis.querySelector('h4')?.textContent).toContain('等分析结果')
  expect(within(analysis).getByRole('button', { name: '去分析项目取结果' })).toBeTruthy()
  const material = article(/意见 2/)
  expect(material.querySelector('h4')?.textContent).toContain('待补材料')
  expect(within(material).queryByRole('button', { name: '去分析项目取结果' })).toBeNull()
  expect(within(material).getByRole('button', { name: '上传补充材料' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '前往已发布分析交付' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '逐条意见' }))
  const rows = await screen.findAllByRole('button', { name: /审稿人 1/ })
  expect(rows.map(row => row.querySelector('small')?.textContent)).toEqual(['等分析结果', '待补材料'])
})

it('goes to the analysis results with a token to the opinion and comes back to an unsaved draft', async () => {
  window.history.replaceState(null, '', address + `reviews&view=plan&round=round1&item=${itemParam}`)
  render(<CustomerWorkspace />)
  fireEvent.change(await screen.findByRole('textbox', { name: '修改计划' }), { target: { value: '待核对的草稿' } })
  fireEvent.click(screen.getByRole('button', { name: '分析材料补充' }))
  await science()
  fireEvent.click(within(article(/意见 1/)).getByRole('button', { name: '去分析项目取结果' }))
  await waitFor(() => expect(window.location.hash).toBe(target))
  expect(await screen.findByText('正在为“第 1 轮 · 意见 1”取分析结果')).toBeTruthy()
  expect(screen.getByRole('heading', { name: '选择分析成果', level: 1 })).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: /分析项目甲 · 生存分析/ }))
  await waitFor(() => expect(window.location.hash).toContain('analysisProject=ra&analysisSnapshot=s1'))
  expect(window.location.hash).toContain('returnLabel=review-item')
  fireEvent.click(await screen.findByRole('link', { name: '下载 生存分析.docx' }))
  expect(await screen.findByText('下载所需文件后，可以返回 第 1 轮 · 意见 1 继续上传。')).toBeTruthy()

  fireEvent.click(screen.getByRole('link', { name: '返回 第 1 轮 · 意见 1' }))
  await waitFor(() => expect(window.location.hash).toBe('#' + origin))
  const place = await screen.findByText('为 第 1 轮 · 意见 1 上传 · 来自 分析项目甲 · 生存分析')
  await waitFor(() => expect(document.activeElement).toBe(place))
  uploaded = true
  fireEvent.click(screen.getByRole('button', { name: '模拟上传完成' }))
  expect(await screen.findByText('新文件已勾选为本轮材料和 意见 1 的依据，尚未保存。')).toBeTruthy()
  expect(writes()).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: '查看并保存处理计划' }))
  expect(await screen.findByRole('textbox', { name: '修改计划' })).toHaveProperty('value', '待核对的草稿')
  const boxes = screen.getAllByRole('checkbox', { name: /生存分析\.docx/ }) as HTMLInputElement[]
  expect(boxes.length).toBe(2)
  expect(boxes.every(box => box.checked)).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '保存本轮计划修改' }))
  await waitFor(() => expect(writes()).toHaveLength(1))
  const body = JSON.parse(String(writes()[0][1].body))
  expect(body.materials).toEqual([{ kind: 'document_version', file_id: 'fnew', id: 'pnew' }])
  expect(body.items.find((entry: { id: string }) => entry.id === analysisItem.id).evidence_ids).toEqual(['pnew'])
  expect(body.items.find((entry: { id: string }) => entry.id === analysisItem.id).plan).toBe('待核对的草稿')
})

it('goes back to the opinion address with browser Back and drops the token on a step choice', async () => {
  window.history.replaceState(null, '', address + 'reviews&view=science&round=round1')
  render(<CustomerWorkspace />)
  await science()
  fireEvent.click(within(article(/意见 1/)).getByRole('button', { name: '去分析项目取结果' }))
  await waitFor(() => expect(window.location.hash).toBe(target))
  await act(async () => window.history.back())
  await waitFor(() => expect(window.location.hash).toBe('#' + origin))
  expect(await screen.findByText('为 第 1 轮 · 意见 1 上传')).toBeTruthy()
  await act(async () => window.history.forward())
  await screen.findByRole('heading', { name: '选择分析成果' })
  fireEvent.click(screen.getByRole('button', { name: '意见与返修' }))
  await waitFor(() => expect(window.location.hash).toBe(address + 'reviews'))
  expect(screen.queryByText(/取分析结果/)).toBeNull()
  expect(screen.queryByText('项目不存在或无权访问。')).toBeNull()
})

it.each(['another opinion', 'another round'])('restores the downloaded source after reload and keeps it out of %s', async other => {
  window.history.replaceState(null, '', target)
  const first = render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: /分析项目甲 · 生存分析/ }))
  fireEvent.click(await screen.findByRole('link', { name: '下载 生存分析.docx' }))
  await screen.findByText(/下载所需文件后/)
  fireEvent.click(screen.getByRole('link', { name: '返回 第 1 轮 · 意见 1' }))
  const original = '为 第 1 轮 · 意见 1 上传 · 来自 分析项目甲 · 生存分析'
  await screen.findByText(original)
  first.unmount()
  const restored = render(<CustomerWorkspace />)
  expect(await screen.findByText(original)).toBeTruthy()
  if (other === 'another opinion') {
    fireEvent.click(screen.getByRole('button', { name: '分析材料补充' }))
    await science()
    fireEvent.click(within(article(/意见 2/)).getByRole('button', { name: '上传补充材料' }))
  } else {
    restored.unmount()
    window.history.replaceState(null, '', '#' + origin.replace('round=round1', 'round=round2'))
    render(<CustomerWorkspace />)
  }
  const place = await screen.findByText(other === 'another opinion' ? /^为 第 1 轮 · 意见 2 上传/ : /^为 第 2 轮 · 意见 1 上传/)
  expect(place.textContent).not.toContain('来自')
  expect(writes()).toEqual([])
})

it('keeps the operator labels and buttons unchanged', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === reviews + '/inputs') return Response.json({ project_type: 'sci', manuscripts: [], documents: [], journal_targets: [], school_confirmations: [] })
    if (url === reviews + '/rounds') return Response.json({ items: [round] })
    if (url === reviews + '/rounds/round1') return Response.json(round)
    return Response.json({ items: [] })
  }))
  render(<ReviewsWorkspace projectId={projectId} projectType="sci" active view="items" roundId="round1"
    onSelectRound={vi.fn()} onOpenTask={vi.fn()} />)
  const rows = await screen.findAllByRole('button', { name: /审稿人 1/ })
  expect(rows.map(row => row.querySelector('small')?.textContent)).toEqual(['待补材料', '待补材料'])
  expect(screen.queryByText('等分析结果')).toBeNull()
})

it('has English for the trip', async () => {
  setLocale('en')
  window.history.replaceState(null, '', address + 'reviews&view=science&round=round1')
  render(<CustomerWorkspace />)
  await screen.findByRole('heading', { name: 'Additional analysis materials' })
  const analysis = await waitFor(() => article(/1/))
  expect(analysis.querySelector('h4')?.textContent).toContain('Waiting for analysis results')
  expect(within(analysis).getByRole('button', { name: 'Get results from an analysis project' })).toBeTruthy()
})
