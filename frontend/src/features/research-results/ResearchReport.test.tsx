import {act, cleanup, render, screen} from '@testing-library/react'
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
 const fetch=vi.fn(async(url:string)=>Response.json(url.endsWith('/research-reports/report')?report:{items:[report],total:1,page:1,page_size:20}))
 vi.stubGlobal('fetch',fetch)
 render(<ResearchReport projectId="p1" active selectedId="report" onSelect={vi.fn()}/>)
 await screen.findByRole('heading',{name:'Frozen report · v1'})
 for(const method of methods){
  const description=screen.getByText(`${method.title} · ${method.description}`,{exact:false})
  expect(description.closest('details')).toBeNull()
 }
 const headings=screen.getAllByRole('heading',{name:'完整方法参数与追溯信息'})
 expect(headings).toHaveLength(2)
 const sections=headings.map(heading=>heading.parentElement!)
 expect(document.querySelector('details')).toBeNull()
 const complete=sections[0].querySelector('dl')!.textContent!
 expect(sections[0].querySelector('pre,code')).toBeNull();expect(complete).not.toContain('sha256')
 expect(complete).toContain(observations[0].barcode)
 expect(complete).toContain(observations[1161].barcode)
 expect(JSON.stringify(report)).toBe(frozen)
 const callsBeforeLocale=fetch.mock.calls.length
 act(()=>setLocale('en'))
 expect(screen.getAllByRole('heading',{name:'Complete method parameters and provenance'})).toHaveLength(2)
 expect(sections[0].querySelector('dl')!.textContent).toBe(complete)
 expect(fetch).toHaveBeenCalledTimes(callsBeforeLocale)
 expect(sections[1].querySelector('pre,code')).toBeNull();expect(sections[1].textContent).toContain('0');expect(sections[1].textContent).toContain('否');expect(sections[1].textContent).toContain('未提供')
})
