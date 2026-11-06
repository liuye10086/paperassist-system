import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import SingleCellRobustness from './SingleCellRobustness'
import type {BioProcessed} from './contracts'
import {bioRequest} from './api'
vi.mock('./api',()=>({bioRequest:vi.fn(),projectBase:(p:string)=>'/'+p}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const result={id:'base',source:{raw_source:{dataset_version_id:'raw'}},manifest:{assay:'single_cell',params:{seed:42,min_genes:200}}} as unknown as BioProcessed
it('reuses baseline parameters and only changes selected seed',async()=>{
 vi.mocked(bioRequest).mockImplementation(async url=>url.endsWith('repeat-context')?{params:{seed:42,min_genes:200},observation_map_version_id:'m1',design_version_id:'d1',repeat_allowed:true}:{items:[],total:0})
 const repeat=vi.fn();render(<SingleCellRobustness projectId="p" result={result} onRepeat={repeat}/> )
 fireEvent.change(await screen.findByLabelText('重复计算随机种子'),{target:{value:'43'}})
 fireEvent.click(screen.getByText('用此参数打开分析方案'))
 expect(repeat).toHaveBeenCalledWith({params:{seed:43,min_genes:200},observation_map_version_id:'m1',design_version_id:'d1',repeat_allowed:true})
 await waitFor(()=>expect(bioRequest).toHaveBeenCalled())
})
it('shows source and donor caveat even before selecting comparison',async()=>{
 vi.mocked(bioRequest).mockImplementation(async url=>url.endsWith('repeat-context')?{params:{seed:42,min_genes:200},observation_map_version_id:'m1',design_version_id:'d1',repeat_allowed:true}:{items:[],total:0})
 render(<SingleCellRobustness projectId="p" result={result}/> )
 expect(screen.getByText(/同供者拆分不能作为独立队列/)).toBeTruthy()
 await waitFor(()=>expect(screen.getByText('尚无其他已完成结果。')).toBeTruthy())
})
it('does not offer full-matrix rerun for a saved subset',async()=>{
 vi.mocked(bioRequest).mockImplementation(async url=>url.endsWith('repeat-context')?{params:{seed:42},repeat_allowed:false}:{items:[],total:0})
 render(<SingleCellRobustness projectId="p" result={result} onRepeat={vi.fn()}/> )
 expect(await screen.findByText(/亚群结果请返回原亚群流程重跑/)).toBeTruthy()
 expect(screen.queryByText('用此参数打开分析方案')).toBeNull()
})
it('compares only successful distinct saved results and displays actual metrics',async()=>{
 vi.mocked(bioRequest).mockImplementation(async url=>{
  if(url.endsWith('repeat-context'))return {params:{seed:42},repeat_allowed:true}
  if(url.includes('/robustness?'))return {baseline:{task_id:'t1'},comparison:{task_id:'t2'},parameter_changes:{seed:{baseline:42,comparison:43}},cells:{baseline:4,comparison:3,common:3,jaccard:0.75},clusters:{adjusted_rand_index:0.5,common_labelled_cells:3},markers:{jaccard:0.2},independence:{status:'same_source'}}
  return {items:[{id:'good',task:{status:'succeeded'},raw_source:{dataset_version_id:'raw'},result_source:{processed_dataset_version_id:'other'}},{id:'cancelled',task:{status:'cancelled'},result_source:{processed_dataset_version_id:'cancelled'}}],total:2}
 })
 render(<SingleCellRobustness projectId="p" result={result}/> )
 fireEvent.change(await screen.findByLabelText('对照结果'),{target:{value:'other'}})
 expect(await screen.findByText(/0.7500/)).toBeTruthy()
 expect(screen.getByText(/同一来源（含亚群\/参数对照）/)).toBeTruthy()
 expect(screen.queryByRole('option',{name:/cancelled/})).toBeNull()
})

it('resets source state and ignores a late comparison response from the previous source',async()=>{
 let resolveOld:(value:unknown)=>void=()=>{}
 let oldSignal:AbortSignal|null|undefined
 vi.mocked(bioRequest).mockImplementation(async (url,init)=>{
  if(url.endsWith('repeat-context'))return {params:{seed:url.includes('/next/')?90:42},repeat_allowed:true}
  if(url.includes('/robustness?')){oldSignal=init?.signal;return new Promise(resolve=>{resolveOld=resolve})}
  return {items:[{id:'good',task:{status:'succeeded'},raw_source:{dataset_version_id:'raw'},result_source:{processed_dataset_version_id:'other'}}],total:1}
 })
 const repeat=vi.fn()
 const view=render(<SingleCellRobustness projectId="p" result={result} onRepeat={repeat}/> )
 fireEvent.change(await screen.findByLabelText('对照结果'),{target:{value:'other'}})
 await waitFor(()=>expect(oldSignal).toBeTruthy())
 view.rerender(<SingleCellRobustness projectId="p" result={{...result,id:'next'}} onRepeat={repeat}/> )
 expect(oldSignal?.aborted).toBe(true)
 await waitFor(()=>expect((screen.getByLabelText('重复计算随机种子') as HTMLInputElement).value).toBe('91'))
 await act(async()=>resolveOld({baseline:{},comparison:{},parameter_changes:{},cells:{baseline:999,comparison:999,common:999,jaccard:1},clusters:{adjusted_rand_index:1,common_labelled_cells:999},markers:{jaccard:1},independence:{status:'same_source'}}))
 expect(screen.queryByText(/999/)).toBeNull()
 expect((screen.getByLabelText('对照结果') as HTMLSelectElement).value).toBe('')
})
