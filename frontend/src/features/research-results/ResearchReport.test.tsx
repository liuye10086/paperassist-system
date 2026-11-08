import {act, cleanup, fireEvent, render, screen} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import {clearApiSession, setApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import ResearchReport from './ResearchReport'
import type {Report} from './contracts'

beforeEach(()=>{setApiSession('csrf','owner');setLocale('zh-CN')})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession();setLocale('zh-CN')})

it('shows complete method parameters directly while preserving large fixed inputs and locale labels',async()=>{
 const observations=Array.from({length:1162},(_,index)=>({processed_version_id:'018e1234-1111-5555-8888-0123456789ab',barcode:`AAACAACGAATAGTTC-${String(index).padStart(4,'0')}`}))
 const groups=[{label:'numerator',observation_keys:observations.slice(0,580)},{label:'denominator',observation_keys:observations.slice(580)}]
 const parameters={plan_config:{groups},executed_config:{groups},primary_q:0,data_driven_grouping:false,missing:null,empty_text:'',empty_list:[],empty_object:{}}
 const raw=JSON.stringify(parameters)
 expect(raw.length).toBeGreaterThan(200000)
 const methods=[{id:'large-method',title:'Fixed comparison',description:'Complete executed method description.',parameters,software:{},executed:true},
  {id:'second-method',title:'Independent method',description:'A separate summary stays readable.',parameters:{zero:0,flag:false,missing:null},software:{},executed:true}]
 const report:Report={id:'report',root_id:'report',revision:1,parent_id:null,content:{title:'Frozen report',language:'zh-CN',finding:{id:'finding',set_id:'set',revision:1,parent_id:null,sha256:'a'.repeat(64),content:{title:'Fixed findings',sources:[],facts:[],methods,claims:[],conflicts:[],reviews:[],limitations:[],gaps:[],warnings:[],notes:''}},figures:[],tables:[]},task_id:'report-task',task:{id:'report-task',status:'succeeded'},members:[],manifest:null}
 const frozen=JSON.stringify(report)
 const fetch=vi.fn(async(url:string)=>Response.json(url.endsWith('/progress')?{project_id:'p1',task_id:'report-task',task_type:'research_report',status:'succeeded',progress:null}:url.endsWith('/research-reports/report')?report:{items:[report],total:1,page:1,page_size:20}))
 vi.stubGlobal('fetch',fetch)
 render(<ResearchReport projectId="p1" active selectedId="report" onSelect={vi.fn()}/>)
 await screen.findByRole('heading',{name:'Frozen report'})
 for(const method of methods){
  const description=screen.getByText(`${method.title} · ${method.description}`,{exact:false})
  expect(description.closest('details')).toBeNull()
 }
 fireEvent.click(screen.getByRole('button',{name:'来源与方法'}))
 const headings=screen.getAllByRole('heading',{name:'完整方法参数与追溯信息'})
 expect(headings).toHaveLength(2)
 const sections=headings.map(heading=>heading.parentElement!)
 expect(document.querySelector('details')).toBeNull()
 const complete=sections[0].querySelector('dl')!.textContent!
 expect(sections[0].querySelector('pre,code')).toBeNull();expect(complete).not.toContain('sha256')
 expect(complete).toContain(observations[0].barcode)
 expect(complete).toContain(observations[1161].barcode)
 expect(JSON.stringify(report)).toBe(frozen)
 const reportReads=()=>fetch.mock.calls.filter(([url])=>url.includes('/research-reports')).length
 const callsBeforeLocale=reportReads()
 act(()=>setLocale('en'))
 expect(screen.getAllByRole('heading',{name:'Complete method parameters and provenance'})).toHaveLength(2)
 expect(sections[0].querySelector('dl')!.textContent).toBe(complete)
 expect(reportReads()).toBe(callsBeforeLocale)
 expect(sections[1].querySelector('pre,code')).toBeNull();expect(sections[1].textContent).toContain('0');expect(sections[1].textContent).toContain('否');expect(sections[1].textContent).toContain('未提供')
})

it('offers the selected successful report as a fixed writing source without creating a task',async()=>{
 const report={id:'report-old',root_id:'r',revision:2,content:{title:'Fixed report',finding:{revision:1,content:{facts:[],methods:[],gaps:[],limitations:[],claims:[]}},tables:[],included_pdf:false},task:{id:'task',status:'succeeded'},members:[]}
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/research-reports/report-old')?report:{items:[],total:0,page:1,page_size:20}));vi.stubGlobal('fetch',fetch)
 const onWriting=vi.fn();render(<ResearchReport projectId="p1" active selectedId="report-old" onSelect={vi.fn()} onWriting={onWriting}/>);await screen.findByRole('heading',{name:'Fixed report'});screen.getByRole('button',{name:'用于写作'}).click();expect(onWriting).toHaveBeenCalledWith({kind:'research_report_version',id:'report-old'});expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})

it.each(['succeeded','running','failed'])('keeps %s report content separate from processing history',async status=>{
 const report={id:'report-old',root_id:'r',revision:2,content:{title:'Fixed report',finding:{revision:1,content:{facts:[],methods:[],gaps:[],limitations:[],claims:[]}},tables:[{key:'source-table',expected_rows:8}],included_pdf:false},task:{id:'task',status},members:[{id:'docx',key:'analysis',format:'docx',size_bytes:100,download_url:'/api/v1/projects/p1/research-reports/report-old/members/docx/download',properties:{tables:'Source table metadata'}}]}
 const stamp='2026-11-05T09:58:05.167769+08:00'
 const progress={project_id:'p1',task_id:'task',task_type:'research_report',status,progress:{stage:'published',stage_started_at:stamp,stage_ended_at:stamp,stage_elapsed_seconds:0,observed_at:stamp,stages:[{stage:'source_verification',started_at:stamp,ended_at:stamp,elapsed_seconds:1.4}]}}
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/progress')?progress:url.endsWith('/research-reports/report-old')?report:{items:[],total:0,page:1,page_size:20}));vi.stubGlobal('fetch',fetch)
 render(<ResearchReport projectId="p1" active selectedId="report-old" onSelect={vi.fn()}/>);
 await screen.findByRole('heading',{name:'Fixed report'})
 expect(screen.queryByRole('heading',{name:'已记录阶段与耗时'})).toBeNull()
 expect(fetch.mock.calls.some(([url])=>url.endsWith('/progress'))).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'下载文件'}))
 expect(screen.getByRole('link',{name:'下载 analysis.docx'})).toBeTruthy()
 expect(screen.getByText('Source table metadata').closest('[hidden]')).toBeTruthy()
 expect(screen.queryByRole('heading',{name:'原始结果表与行数'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'处理记录'}))
 expect(await screen.findByRole('heading',{name:'已记录阶段与耗时'})).toBeTruthy()
 expect(screen.queryByRole('link',{name:'下载 analysis.docx'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'来源与方法'}))
 expect(screen.queryByRole('heading',{name:'已记录阶段与耗时'})).toBeNull()
 expect(screen.getByRole('heading',{name:'原始结果表与行数'})).toBeTruthy()
 expect(screen.getByText('Source table metadata')).toBeTruthy()
 expect(document.querySelector('details')).toBeNull()
 expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})

it.each(['queued','running','failed'])('does not offer a %s report for writing',async status=>{
 const report={id:'report-old',root_id:'r',revision:2,content:{title:'Fixed report',finding:{revision:1,content:{facts:[],methods:[],gaps:[],limitations:[],claims:[]}},tables:[],included_pdf:false},task:{id:'task',status},members:[]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/research-reports/report-old')?report:{items:[],total:0,page:1,page_size:20})))
 render(<ResearchReport projectId="p1" active selectedId="report-old" onSelect={vi.fn()} onWriting={vi.fn()}/>);await screen.findByRole('heading',{name:'Fixed report'});expect(screen.queryByRole('button',{name:'用于写作'})).toBeNull()
})

it('keeps saved report Word and tables without PDF history or a ZIP containing PDF',async()=>{
 const member=(format:string)=>({id:format,key:format==='docx'?'report':'saved',format,sha256:'a'.repeat(64),size_bytes:100,download_url:`/api/v1/projects/p1/research-reports/report-old/members/${format}/download`})
 const report={id:'report-old',root_id:'r',revision:2,content:{title:'Fixed report',finding:{revision:1,content:{facts:[],methods:[],gaps:[],limitations:[],claims:[]}},tables:[],included_pdf:true},task:{id:'task',status:'succeeded'},members:[member('docx'),member('pdf'),member('xlsx'),member('zip')]}
 const fetch=vi.fn(async(url:string)=>Response.json(url.endsWith('/research-reports/report-old')?report:{items:[],total:0,page:1,page_size:20}));vi.stubGlobal('fetch',fetch)
 render(<ResearchReport projectId="p1" active selectedId="report-old" onSelect={vi.fn()}/>)
 fireEvent.click(await screen.findByRole('button',{name:'下载文件'}));expect(await screen.findByRole('link',{name:'下载 report.docx'})).toBeTruthy();expect(screen.getByRole('link',{name:'下载 saved.xlsx'})).toBeTruthy()
 expect(screen.queryByRole('link',{name:'下载 saved.pdf'})).toBeNull();expect(screen.queryByRole('link',{name:'下载 saved.zip'})).toBeNull()
 expect(screen.queryByRole('region',{name:/PDF/})).toBeNull();expect(fetch.mock.calls.some(([url])=>url.includes('/pdf-exports'))).toBe(false)
})

it('hides a legacy report ZIP whose package manifest includes figure PDF even without an included PDF export',async()=>{
 const member=(format:string)=>({id:format,key:'saved',format,sha256:'a'.repeat(64),size_bytes:100,download_url:`/api/v1/projects/p1/research-reports/report-old/members/${format}/download`})
 const report={id:'report-old',root_id:'r',revision:2,content:{title:'Fixed report',finding:{revision:1,content:{facts:[],methods:[],gaps:[],limitations:[],claims:[]}},tables:[],included_pdf:null},task:{id:'task',status:'succeeded'},members:[member('docx'),member('zip')],manifest:{package_manifest:{members:[{name:'report.docx'},{name:'figures/figure_01/plot.pdf'}]}}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/research-reports/report-old')?report:{items:[],total:0,page:1,page_size:20})))
 render(<ResearchReport projectId="p1" active selectedId="report-old" onSelect={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:'下载文件'}));expect(await screen.findByRole('link',{name:'下载 saved.docx'})).toBeTruthy();expect(screen.queryByRole('link',{name:'下载 saved.zip'})).toBeNull()
})
