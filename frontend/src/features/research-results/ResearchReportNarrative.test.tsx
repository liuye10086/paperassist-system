import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import {clearApiSession, setApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import ResearchReport from './ResearchReport'
import {ReportNarrativeView} from './ResearchReportNarrative'
import {RESEARCH_LOADING_MESSAGE} from './api'

const base = '/api/v1/projects/p1'
const endpoint = `${base}/research-report-narratives`
const initialFinding = {id: 'finding', setId: 'set1', title: 'Frozen spatial findings'}
const props = {projectId: 'p1', active: true, selectedId: '', initialFinding}
const record = {
  id: 'narrative-1', binding_sha256: 'a'.repeat(64), bundle_sha256: 'b'.repeat(64), artifact_sha256: 'c'.repeat(64),
  task: {id: 'narrative-task', status: 'succeeded', revision: 3}, allowed_actions: [], model_calls: [],
  result: {
    narrative: {
      abstract: 'The report contains fixed spatial observations.', design_and_data: 'Design information was unavailable.',
      quality_control: 'The retained area was reviewed.', methods_summary: 'Spatial expression was summarized.',
      key_findings: 'Two figures are available.', limitations: 'Replicates are not established.', reader_cautions: 'Review the spatial coordinates.',
    },
    figures: [{number: 1, title: 'Spatial panel', reading: 'Read the colour scale.', observations: 'The signal varies across the field.', interpretation: 'Variation is descriptive.', limitations: 'Tissue coverage is limited.', caption: 'A fixed expression panel.'}],
  },
}

beforeEach(() => { setApiSession('csrf', 'owner'); sessionStorage.clear() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); clearApiSession(); sessionStorage.clear() })

it('shows the limits of the model materials and points readers to the complete saved results in both languages', () => {
  setLocale('zh-CN')
  render(<ReportNarrativeView result={record.result}/>)
  try {
    expect(screen.getByText('解读依据选定的摘要事实和图件。解读中的“未提供”仅指本次解读所见材料。已保存的完整结果以所选结果表为准。')).toBeTruthy()
    act(() => setLocale('en'))
    expect(screen.getByText('This interpretation uses the selected summary facts and figures. “Not provided” refers to the materials available for this interpretation. Consult the selected results tables for the complete saved results.')).toBeTruthy()
  } finally {
    act(() => setLocale('zh-CN'))
  }
})

function mockServer({unknown = false, lookupMissing = false, waiting = false, terminalInvalid = false, enabled = true, cached = false, previewExtra}: {
  unknown?: boolean; lookupMissing?: boolean; waiting?: boolean; terminalInvalid?: boolean; enabled?: boolean; cached?: boolean; previewExtra?: Record<string, unknown>
} = {}) {
  let submissions = 0
  const failed = {...record,id:'failed-narrative',task:{...record.task,status:'failed',error_code:'model_response_invalid'},result:null,artifact_sha256:null,can_regenerate:true}
  let liveStatus = waiting ? {...record, task: {...record.task, status:'waiting_confirmation', revision:4}, result:null, artifact_sha256:null,allowed_actions:['resume']} : record
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === `${endpoint}/preview`) return Response.json({bundle_sha256: 'b'.repeat(64), binding_sha256: record.binding_sha256,
      model: 'vision-model', reserved_micro_usd: 125000, fact_count: 4, figures: [{number:1, title: 'Spatial panel'}], real_calls_enabled: enabled, cached, ...previewExtra})
    if (url === endpoint && init?.method === 'POST') {
      submissions++
      if (unknown && submissions === 1) throw new TypeError('lost response')
      if (terminalInvalid && submissions === 1) return Response.json(failed)
      return Response.json(liveStatus)
    }
    if (url.startsWith(`${endpoint}/requests/`)) return lookupMissing
      ? Response.json({detail: 'Not found'}, {status: 404}) : Response.json(record)
    if (url === `${endpoint}/${record.id}/retry` && init?.method === 'POST') { liveStatus = record; return Response.json(record) }
    if (url === `${endpoint}/${record.id}`) return Response.json(liveStatus)
    if (url === `${endpoint}/${failed.id}`) return Response.json(failed)
    if (url === `${base}/research-reports` && init?.method === 'POST') return Response.json({id: 'saved-report'})
    if (url.includes('/research-figures')) return Response.json({items: ['Spatial panel', 'Second plot'].map((title, i) => ({id: `figure${i + 1}`,config: {title},task: {status: 'succeeded'}})),total: 2,page: 1,page_size: 20})
    if (url.includes('/versions/finding')) return Response.json({id:'finding',content: {facts: [], gaps: []}})
    return Response.json({items: [], total: 0, page: 1, page_size: 20})
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

async function confirmNarrative(label = '生成详细解读') {
  fireEvent.click(screen.getByRole('button', {name: label}))
  const consent = await screen.findByRole('checkbox', {name: '我同意发送上述材料以生成详细解读'})
  const confirm = screen.getByRole('button', {name: '确认材料并生成解读'})
  expect(confirm).toHaveProperty('disabled', true)
  expect(screen.getByText(/vision-model.*0\.125/)).toBeTruthy()
  expect(screen.getByText('结果摘要包含 4 项内容，图片 1 张。')).toBeTruthy()
  fireEvent.click(consent)
  fireEvent.click(confirm)
  fireEvent.click(confirm)
}

it.each(['research-findings', 'research-figures'])('announces source verification while %s loads without blocking a report with no selected figures', async pending => {
  let resolve!: (response: Response) => void
  const response = new Promise<Response>(done => { resolve = done })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.split('?')[0].endsWith(`/${pending}`)) return response
    if (url.endsWith('/versions/finding')) return Response.json({id:'finding',content:{facts:[],gaps:[]}})
    return Response.json({items: [], total: 0, page: 1, page_size: 20})
  }))
  render(<ResearchReport {...props} onSelect={vi.fn()}/>)
  const status = await screen.findByRole('status')
  expect(status.textContent).toBe(RESEARCH_LOADING_MESSAGE)
  expect(screen.getByRole('button',{name:'下一步：确认生成'})).toHaveProperty('disabled',false)
  fireEvent.click(screen.getByRole('button',{name:'下一步：确认生成'}))
  expect(screen.getByRole('button',{name:'生成详细解读'})).toHaveProperty('disabled',false)
  fireEvent.click(screen.getByRole('button',{name:'上一步'}))
  resolve(Response.json({items: [], total: 0, page: 1, page_size: 20}))
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
})

it('shows actual model scope and only exports Word after displaying a matching interpretation', async () => {
  const fetch = mockServer(), onSelect = vi.fn()
  render(<ResearchReport {...props} onSelect={onSelect}/>)
  fireEvent.click(await screen.findByRole('checkbox', {name: /Spatial panel/}))
  fireEvent.click(screen.getByRole('button', {name: '下一步：确认生成'}))
  const exportButton = screen.getByRole('button', {name: '生成固定报告与成果包'})
  expect(exportButton).toHaveProperty('disabled', true)
  await confirmNarrative()
  expect(await screen.findByText(record.result.narrative.abstract)).toBeTruthy()
  expect(screen.getByText(record.result.figures[0].observations)).toBeTruthy()
  expect(exportButton).toHaveProperty('disabled', false)
  fireEvent.click(exportButton)
  await waitFor(() => expect(onSelect).toHaveBeenCalledWith('saved-report'))
  const posts = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(posts.map(([url]) => url)).toEqual([`${endpoint}/preview`, endpoint, `${base}/research-reports`])
  expect(JSON.parse(String(posts[1][1]?.body))).toMatchObject({confirmed_external_processing:true,bundle_sha256:'b'.repeat(64),report:{figure_version_ids:['figure1']}})
  expect(JSON.parse(String(posts[2][1]?.body))).toMatchObject({reader_narrative_id:record.id,figure_version_ids:['figure1']})
})

it('discloses the caption and bound facts of each outgoing image in report order even without main findings', async () => {
  const fetch = mockServer({previewExtra:{fact_count:0,facts:{facts:[]},figures:[
    {number:1,title:'Second plot',source_caption:'空间切片图注原文',caption_facts:[
      {locator:{kind:'field',field_path:'summary.raw_observations'},raw_value:1162,display_value:'1162',unit:'spots',observation_level:'spot',verification_status:'verified',origin:'public_reanalysis',comparison:'3 对 1',limitations:['空间点不是生物学重复'],id:'private-fact-0'},
      ...Array.from({length:16},(_,i)=>({label:`图件绑定证据 ${i+1}`,value:i+1,id:`private-fact-${i+1}`})),
    ], image_url:'data:image/png;base64,PRIVATE'},
    {number:2,title:'Spatial panel',source_caption:'空间分组图注原文',caption_facts:[]},
  ]}})
  render(<ResearchReport {...props} onSelect={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button',{name:'下一步：确认生成'}))
  fireEvent.click(screen.getByRole('button',{name:'生成详细解读'}))
  const review = await screen.findByRole('region',{name:'确认外发材料与费用'})
  expect(within(review).getByText('结果摘要包含 0 项内容，图片 2 张。')).toBeTruthy()
  expect(review.querySelector('details, summary')).toBeNull()
  expect(within(review).getByRole('button',{name:'将发送的图片与图注'}).getAttribute('aria-pressed')).toBe('true')
  const first = within(review).getByText('Second plot').closest('li')!
  const second = within(review).getByText('Spatial panel').closest('li')!
  expect(first.nextElementSibling).toBe(second)
  expect(within(first).getByText('空间切片图注原文')).toBeTruthy()
  expect(within(first).getByRole('rowheader',{name:'原始空间点数'})).toBeTruthy()
  expect(within(first).getByText('1162')).toBeTruthy()
  expect(within(first).getByText(/空间点层级/)).toBeTruthy()
  expect(within(first).getByText(/已核对.*公开数据再分析/)).toBeTruthy()
  expect(within(first).getByText(/3 对 1/)).toBeTruthy()
  expect(within(first).getByText('空间点不是生物学重复')).toBeTruthy()
  expect(within(first).getAllByText(/^图件绑定证据 /)).toHaveLength(16)
  expect(within(second).getByText('空间分组图注原文')).toBeTruthy()
  expect(review.textContent).not.toMatch(/private-fact|data:image|raw value|display value|public_reanalysis|summary\.raw_observations/)
  expect(fetch.mock.calls.filter(([url])=>url===endpoint)).toHaveLength(0)
})

it('keeps readable metric names in the main outgoing facts and their inherited findings', async () => {
  mockServer({previewExtra:{fact_count:1,facts:{facts:[{measure:{kind:'field',field_path:'summary.raw_features'},value:58735,source:'公开空间结果'}],
    inherited_findings:[{facts:[{measure:{kind:'field',field_path:'overall.mean'},value:3.2}]}]}}})
  render(<ResearchReport {...props} onSelect={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button',{name:'下一步：确认生成'}))
  fireEvent.click(screen.getByRole('button',{name:'生成详细解读'}))
  const review = await screen.findByRole('region',{name:'确认外发材料与费用'})
  expect(review.querySelector('details, summary')).toBeNull()
  fireEvent.click(within(review).getByRole('button',{name:'将发送的结果摘要'}))
  expect(screen.getByRole('rowheader',{name:'原始特征数'})).toBeTruthy()
  expect(screen.getByText('58735')).toBeTruthy()
  expect(screen.getByText('公开空间结果')).toBeTruthy()
  expect(screen.getByRole('rowheader',{name:'总体 · 均值'})).toBeTruthy()
})

it('restores unknown submission by its original key and invalidates the result after language changes', async () => {
  const fetch = mockServer({unknown:true}), onSelect = vi.fn()
  const view = render(<ResearchReport {...props} onSelect={onSelect}/>)
  fireEvent.click(await screen.findByRole('checkbox', {name: /Spatial panel/}))
  fireEvent.click(screen.getByRole('button', {name: '下一步：确认生成'}))
  await confirmNarrative()
  await screen.findByRole('button', {name: '查询原请求结果'})
  view.unmount()
  render(<ResearchReport {...props} onSelect={onSelect}/>)
  fireEvent.click(await screen.findByRole('button', {name: '查询原请求结果'}))
  expect(await screen.findByText(record.result.narrative.abstract)).toBeTruthy()
  const submit = fetch.mock.calls.find(([url]) => url === endpoint)!
  const key = new Headers(submit[1]?.headers).get('Idempotency-Key')
  expect(fetch.mock.calls.some(([url]) => url === `${endpoint}/requests/${key}`)).toBe(true)
  fireEvent.change(screen.getByLabelText('报告语言'), {target: {value: 'en'}})
  expect(screen.queryByText(record.result.narrative.abstract)).toBeNull()
  expect(screen.getByRole('button', {name: '生成固定报告与成果包'})).toHaveProperty('disabled', true)
  expect(fetch.mock.calls.filter(([url]) => url === endpoint)).toHaveLength(1)
})

it('keeps a reader-only report list free of creation controls', async () => {
  const fetch = mockServer()
  render(<ResearchReport {...props} readerView onSelect={vi.fn()}/>)
  await screen.findByRole('button', {name: '刷新报告版本'})
  expect(screen.queryByRole('button', {name: '新建研究报告'})).toBeNull()
  expect(screen.queryByRole('button', {name: '生成详细解读'})).toBeNull()
  expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})

it('discards an interpretation when the figure order changes even if the same figures remain selected',async () => {
  const fetch = mockServer()
  render(<ResearchReport {...props} onSelect={vi.fn()}/>)
  fireEvent.click(await screen.findByRole('checkbox',{name:/Spatial panel/}))
  fireEvent.click(screen.getByRole('checkbox',{name:/Second plot/}))
  fireEvent.click(screen.getByRole('button',{name:'下一步：确认生成'}))
  await confirmNarrative()
  await screen.findByText(record.result.narrative.abstract)
  fireEvent.click(screen.getByRole('button',{name:'上一步'}))
  fireEvent.click(screen.getAllByRole('button',{name:'下移'})[0])
  fireEvent.click(screen.getByRole('button',{name:'下一步：确认生成'}))
  expect(screen.queryByText(record.result.narrative.abstract)).toBeNull()
  expect(screen.getByRole('button',{name:'生成固定报告与成果包'})).toHaveProperty('disabled',true)
  expect(fetch.mock.calls.filter(([url])=>url===endpoint)).toHaveLength(1)
})

it('resends only the original fixed request after a missing submission lookup', async () => {
  const fetch = mockServer({unknown:true,lookupMissing:true})
  render(<ResearchReport {...props} onSelect={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button', {name:'下一步：确认生成'}))
  await confirmNarrative()
  fireEvent.click(await screen.findByRole('button', {name:'查询原请求结果'}))
  fireEvent.click(await screen.findByRole('button', {name:'用原键重试固定请求'}))
  expect(await screen.findByText(record.result.narrative.abstract)).toBeTruthy()
  const submits = fetch.mock.calls.filter(([url]) => url === endpoint)
  expect(submits).toHaveLength(2)
  expect(submits[0][1]?.body).toBe(submits[1][1]?.body)
  expect(new Headers(submits[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(submits[1][1]?.headers).get('Idempotency-Key'))
})

it('resumes the original task and restores its completed interpretation on reload', async () => {
  const fetch = mockServer({waiting:true})
  const view = render(<ResearchReport {...props} onSelect={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button', {name:'下一步：确认生成'}))
  await confirmNarrative()
  fireEvent.click(await screen.findByRole('button', {name:'继续查看原解读任务'}))
  expect(await screen.findByText(record.result.narrative.abstract)).toBeTruthy()
  const retry = fetch.mock.calls.find(([url]) => url === `${endpoint}/${record.id}/retry`)
  expect(JSON.parse(String(retry?.[1]?.body))).toEqual({expected_revision:4})
  view.unmount()
  render(<ResearchReport projectId="p1" active selectedId="" onSelect={vi.fn()}/>)
  expect(await screen.findByText(record.result.narrative.abstract)).toBeTruthy()
  expect(fetch.mock.calls.filter(([url]) => url === endpoint)).toHaveLength(1)
})

it('requires a fresh explicit confirmation and request key to regenerate invalid terminal output', async () => {
  const fetch = mockServer({terminalInvalid:true})
  render(<ResearchReport {...props} onSelect={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button', {name:'下一步：确认生成'}))
  await confirmNarrative()
  const label = '重新生成详细解读（会再次调用模型）'
  await screen.findByRole('button',{name:label})
  expect(fetch.mock.calls.filter(([url]) => url === endpoint)).toHaveLength(1)
  expect(screen.queryByRole('button',{name:'重试原解读任务'})).toBeNull()
  await confirmNarrative(label)
  await screen.findByText(record.result.narrative.abstract)
  const submits = fetch.mock.calls.filter(([url]) => url === endpoint)
  expect(submits).toHaveLength(2)
  expect(new Headers(submits[0][1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(submits[1][1]?.headers).get('Idempotency-Key'))
})

it.each([false,true])('disables live submissions when configured off and permits cached reuse (%s)', async cached => {
  const fetch = mockServer({enabled:false,cached})
  render(<ResearchReport {...props} onSelect={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button', {name:'下一步：确认生成'}))
  fireEvent.click(screen.getByRole('button', {name:'生成详细解读'}))
  fireEvent.click(await screen.findByRole('checkbox', {name:cached?'确认使用上述材料的已保存解读':'我同意发送上述材料以生成详细解读'}))
  expect(screen.getByRole('button', {name:'确认材料并生成解读'})).toHaveProperty('disabled', !cached)
  expect(fetch.mock.calls.filter(([url]) => url === endpoint)).toHaveLength(0)
})
