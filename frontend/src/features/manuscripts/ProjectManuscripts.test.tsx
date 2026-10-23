import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectManuscripts from './ProjectManuscripts'
import { setLocale } from '../../shared/i18n'
import { manuscriptFixture, candidatesFixture, snapshotFixture } from './manuscriptFixtures'
const base = '/api/v1/projects/p1/manuscripts'
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); setLocale('zh-CN') })
function server(history: unknown[] = []) {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === `${base}/candidates`) return Response.json(candidatesFixture)
    if (url === base && !init?.method) return Response.json({ items: history })
    if (url.endsWith('/preview')) return Response.json(snapshotFixture)
    if (url.endsWith('/exports') && !init?.method) return Response.json({items:[],pdf_status:'not_requested'})
    return Response.json(manuscriptFixture)
  }); vi.stubGlobal('fetch', fetcher); return fetcher
}
const props={projectId:'p1',researchTopic:'示例研究',outputLanguage:'en' as const,active:true}
it('keeps reviewed v2 scientific content out of ordinary edit and review publishing',async()=>{
 const snapshot={...snapshotFixture,writing_provenance:{schema_version:2,provider_provenance:'synthetic_fixture',verification_status:'scientific_and_language_reviewed'}}
 server([{...manuscriptFixture,versions:[{...manuscriptFixture.versions[0],snapshot}]}]);render(<ProjectManuscripts {...props}/>);const edit=await screen.findByRole('button',{name:'以此版本编辑新稿'});expect(edit.hasAttribute('disabled')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'查看版本 1'}));expect(await screen.findByText('v2 审核稿仅可查看公共检查；普通修改与发布入口关闭。')).toBeTruthy();expect(screen.getByRole('button',{name:'重新检查并保存候选'}).hasAttribute('disabled')).toBe(true)
})
it('collects editable inputs, true source roles and ordered Results groups while output language is independent', async () => {
  const fetcher=server(); render(<ProjectManuscripts {...props}/>)
  fireEvent.click(await screen.findByRole('checkbox',{name:'固定统计结果'}))
  fireEvent.click(screen.getByRole('checkbox',{name:'参考论文'}))
  expect(within(screen.getByRole('group',{name:'参考论文'})).queryByRole('option',{name:'固定统计结果'})).toBeNull()
  fireEvent.change(screen.getByLabelText('研究问题'),{target:{value:'What differs?'}})
  fireEvent.change(screen.getByLabelText('研究目的'),{target:{value:'Compare groups'}})
  fireEvent.change(screen.getByLabelText('研究假设'),{target:{value:'Group A differs'}})
  fireEvent.click(screen.getByRole('button',{name:'添加 Results 分组'}))
  const group=screen.getByRole('group',{name:'Results 分组 1'})
  fireEvent.change(within(group).getByLabelText('分组标题'),{target:{value:'Primary finding'}})
  fireEvent.click(within(group).getByRole('checkbox',{name:'固定统计结果'}))
  fireEvent.click(screen.getByRole('button',{name:'预览事实稿'}))
  await screen.findByText('Local deterministic draft')
  const request=fetcher.mock.calls.find(([url])=>url.endsWith('/preview'))!
  const body=JSON.parse(String(request[1]?.body))
  expect(body.output_language).toBe('en'); expect(body.methods.purpose).toBe('Compare groups')
  expect(body.sources.map((s:{role:string})=>s.role)).toEqual(['computed_results','literature'])
  expect(body.results_groups[0].analysis_run_ids).toEqual(['run1'])
  expect(screen.getByRole('region',{name:'事实稿预览'}).getAttribute('lang')).toBe('en')
  act(()=>setLocale('en'))
  expect(screen.getByLabelText('Draft output language')).toHaveProperty('value','en')
  expect(screen.getByText('Local deterministic draft')).toBeTruthy()
})
it('keeps group identity while reordering, invalidates old preview and reuses a failed submission key',async()=>{
  const fetcher=server(); render(<ProjectManuscripts {...props}/>)
  await screen.findByRole('checkbox',{name:'固定统计结果'})
  fireEvent.click(screen.getByRole('button',{name:'添加 Results 分组'})); fireEvent.click(screen.getByRole('button',{name:'添加 Results 分组'}))
  const first=screen.getByRole('group',{name:'Results 分组 1'}),second=screen.getByRole('group',{name:'Results 分组 2'})
  fireEvent.change(within(first).getByLabelText('分组标题'),{target:{value:'First'}})
  fireEvent.change(within(second).getByLabelText('分组标题'),{target:{value:'Second'}})
  fireEvent.click(screen.getByRole('button',{name:'预览事实稿'})); await screen.findByText('Local deterministic draft')
  const original=JSON.parse(String(fetcher.mock.calls.find(([url])=>url.endsWith('/preview'))![1]?.body))
  fireEvent.click(within(second).getByRole('button',{name:'上移分组'}))
  expect(screen.queryByRole('region',{name:'事实稿预览'})).toBeNull()
  fetcher.mockImplementation(async(url:string,init?:RequestInit)=>{
    if(url===base&&init?.method==='POST') throw new TypeError('network')
    return Response.json({items:[]})
  })
  fireEvent.click(screen.getByRole('button',{name:'保存并创建事实稿'})); await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button',{name:'保存并创建事实稿'})); await waitFor(()=>expect(fetcher.mock.calls.filter(([u,i])=>u===base&&i?.method==='POST')).toHaveLength(2))
  const calls=fetcher.mock.calls.filter(([u,i])=>u===base&&i?.method==='POST')
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
  const body=JSON.parse(String(calls[0][1]?.body));expect(body.results_groups.map((g:{id:string})=>g.id)).toEqual(original.results_groups.map((g:{id:string})=>g.id).reverse())
})
it('preserves historical snapshots, clones exact frozen input into a new version and exposes separate DOCX status',async()=>{
  const fetcher=server([manuscriptFixture]); render(<ProjectManuscripts {...props}/>)
  fireEvent.click(await screen.findByRole('button',{name:'查看版本 1'}))
  expect(await screen.findByText('Local deterministic draft')).toBeTruthy()
  expect(screen.getByRole('link',{name:'下载 DOCX'}).getAttribute('href')).toBe(`${base}/m1/exports/export1/download`)
  expect(screen.getByText('Pending verification')).toBeTruthy(); expect(screen.getByText('Missing ethics')).toBeTruthy()
  expect(screen.getByRole('link',{name:'核查引用与证据'})).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'以此版本编辑新稿'}))
  expect(screen.getByLabelText('研究问题')).toHaveProperty('value','Frozen question')
  fireEvent.change(screen.getByLabelText('研究问题'),{target:{value:'Edited question'}})
  fireEvent.click(screen.getByRole('button',{name:'保存为新版本'}))
  await waitFor(()=>expect(fetcher.mock.calls.some(([u,i])=>u===`${base}/m1/versions`&&i?.method==='POST')).toBe(true))
  const call=fetcher.mock.calls.find(([u,i])=>u===`${base}/m1/versions`&&i?.method==='POST')!
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({expected_revision:1,methods:{research_question:'Edited question'}})
  expect(manuscriptFixture.versions[0].snapshot.methods[0].text).toBe('Frozen methods')
})
it('does not load or submit while inactive and aborts a late preview on project change',async()=>{
  const fetcher=server(); const view=render(<ProjectManuscripts {...props} active={false}/>)
  expect(fetcher).not.toHaveBeenCalled();view.rerender(<ProjectManuscripts {...props}/>)
  await screen.findByRole('checkbox',{name:'固定统计结果'})
  let finish!:(r:Response)=>void;let signal!:AbortSignal
  fetcher.mockImplementation((url:string,init?:RequestInit)=>url.endsWith('/preview')?new Promise(r=>{finish=r;signal=init?.signal as AbortSignal}):Promise.resolve(Response.json(url.endsWith('/candidates')?candidatesFixture:{items:[]})))
  fireEvent.click(screen.getByRole('button',{name:'预览事实稿'}))
  view.rerender(<ProjectManuscripts {...props} projectId="p2"/>);expect(signal.aborted).toBe(true)
  await act(async()=>finish(Response.json(snapshotFixture)))
  expect(screen.queryByText('Local deterministic draft')).toBeNull()
})

it('keeps unsaved materials when visiting citation review and pauses background reads while inactive',async()=>{
 const fetcher=server();const view=render(<ProjectManuscripts {...props}/>)
 await screen.findByRole('checkbox',{name:'固定统计结果'})
 fireEvent.change(screen.getByLabelText('研究问题'),{target:{value:'Keep this question'}})
 view.rerender(<ProjectManuscripts {...props} active={false}/>)
 const reads=fetcher.mock.calls.length
 view.rerender(<ProjectManuscripts {...props}/>)
 expect(screen.getByLabelText('研究问题')).toHaveProperty('value','Keep this question')
 expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(reads)
})
it.each(['zh-CN','en'] as const)('describes candidate writing, explicit publishing and offline verification accurately in %s',async locale=>{
 setLocale(locale);server();render(<ProjectManuscripts {...props}/>);await screen.findByRole('checkbox',{name:'固定统计结果'})
 expect(screen.getByText(locale==='en'?'Organize sources into fact drafts and complete seven-section candidates, rewrite a section, then publish explicitly as a new version.':'整理来源与事实稿，生成完整七部分候选或重写指定章节，经审核后显式发布新版本。')).toBeTruthy()
 expect(screen.getByText(locale==='en'?'The factual draft is generated locally. Controlled model writing requires separate explicit authorization. Researchers must verify the scientific content, sources, values, citations and outstanding issues.':'事实稿由本地生成；受控模型写作须另行明确授权。科研内容、来源、数值、引用及待办仍须研究人员核实。')).toBeTruthy()
})
