import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPlanLauncher from './AnalysisPlanLauncher'
import { reviewFixture } from './analysisPlanFixtures'
import { type PreparedDatasetAnalysisSource } from '../analysis/datasetSource'
import { type Selection } from '../analysis/AnalysisSetup'
import { setLocale } from '../../shared/i18n'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })

test.each(['zh-CN','en'] as const)('list uses failed and queued status labels in %s',async(locale)=>{
 setLocale(locale)
 const items=['failed','queued'].map((status,index)=>({...reviewFixture,task:{...reviewFixture.task,id:'t'+index,status,display_status:status}}))
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/analysis-plans?')?{items,total:2,page:1,page_size:5}:items[0])))
 render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={reviewFixture.source as PreparedDatasetAnalysisSource} selection={reviewFixture.selection as Selection} setupRevision={0} disabled={false} onPublished={()=>{}}/>)
 expect(await screen.findByRole('button',{name:new RegExp(locale==='en'?'Execution failed':'执行失败')})).toBeTruthy()
 expect(screen.getByRole('button',{name:new RegExp(locale==='en'?'Queued':'待执行')})).toBeTruthy()
})

test('selects only matching prepared sources and ignores a late previous-source review',async()=>{
 const otherSource={...reviewFixture.source,dataset_id:'prepared2',dataset_version:2} as PreparedDatasetAnalysisSource
 const other={...reviewFixture,source:otherSource,input_version:{...reviewFixture.input_version,source:otherSource},task:{...reviewFixture.task,id:'t2',input_version:{...reviewFixture.input_version,source:otherSource}}}
 let resolve:(response:Response)=>void=()=>{}
 const fetch=vi.fn((url:string)=>url.includes('/analysis-plans?')?Promise.resolve(Response.json({items:[reviewFixture,other],total:2,page:1,page_size:5})):url.includes('/t1/')?new Promise<Response>(r=>{resolve=r}):Promise.resolve(Response.json(other)))
 vi.stubGlobal('fetch',fetch)
 const props={projectId:'p1',fileId:'f1',selection:reviewFixture.selection as Selection,setupRevision:0,disabled:false,onPublished:()=>{}}
 const view=render(<AnalysisPlanLauncher {...props} source={reviewFixture.source as PreparedDatasetAnalysisSource}/>)
 await waitFor(()=>expect(fetch.mock.calls.some(([u])=>u.includes('/t1/'))).toBe(true))
 view.rerender(<AnalysisPlanLauncher {...props} source={otherSource}/>)
 await screen.findByText('分析计划审核')
 expect(fetch.mock.calls.filter(([u])=>u.includes('/t2/'))).toHaveLength(1)
 await act(async()=>{resolve(Response.json(reviewFixture))})
 expect(fetch.mock.calls.filter(([u])=>u.includes('/t1/'))).toHaveLength(1)
})

test('creates a plan for the selected prepared version and recovers it from a bounded list', async () => {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/analysis-plans?page=')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url.endsWith('/analysis-plans') && init?.method === 'POST') return Response.json(reviewFixture.task, { status: 202 })
    if (url.endsWith('/analysis-plan')) return Response.json(reviewFixture)
    throw new Error(url)
  })
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={reviewFixture.source as PreparedDatasetAnalysisSource} selection={reviewFixture.selection as Selection} setupRevision={0} disabled={false} onPublished={() => {}} />)
  await screen.findByRole('button', { name: '生成分析计划' })
  await user.click(screen.getByRole('button', { name: '生成分析计划' }))
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/analysis-plans'))).toBe(true))
  const body = JSON.parse(fetch.mock.calls.find(([url]) => url.endsWith('/analysis-plans'))![1]?.body as string)
  expect(body).toEqual({ dataset_id: 'prepared1', expected_setup_revision: 0, selection: reviewFixture.selection })
  expect(await screen.findByText('分析计划审核')).toBeTruthy()
  expect(fetch.mock.calls.filter(([url]) => url.includes('/analysis-plans?page=')).length).toBe(2)
})
