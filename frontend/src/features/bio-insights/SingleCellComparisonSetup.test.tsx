import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {useState} from 'react'
import {afterEach,expect,it,vi} from 'vitest'
import SingleCellComparisonSetup from './SingleCellComparisonSetup'
import {defaultSingleCellComposition,defaultSingleCellDE} from './singleCellComparison'
import {apiFetch} from '../../shared/api/client'
import type {Config,Contrast,Source} from './contracts'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
afterEach(cleanup)
const sources:Source[]=[{source_kind:'bio_processed_dataset_version',source_id:'p',role:'processed',sha256:'a'.repeat(64),locator:{kind:'object'}},{source_kind:'bio_annotation_version',source_id:'ann',role:'annotation',sha256:'b'.repeat(64),locator:{kind:'object'}}]
function setup(composition:boolean,singleCondition=false){
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/bio_annotation_version/')?{items:[{barcode:'a',status:'assigned',label_id:'T'},{barcode:'b',status:'assigned',label_id:'B'},{barcode:'c',status:'assigned',label_id:'T'},{barcode:'u',status:'unknown',label_id:null}],total:4,processed_dataset_version_id:'p'}:{items:[{barcode:'a',retained:true,condition:singleCondition?'healthy':'stim',donor:'d1'},{barcode:'b',retained:true,condition:singleCondition?'healthy':'stim',donor:'d2'},{barcode:'c',retained:true,condition:singleCondition?'healthy':'ctrl',donor:'d1'},{barcode:'u',retained:true,condition:singleCondition?'healthy':'ctrl',donor:null}],total:4,observation_level:'cell'}))
 let latest:Config=composition?defaultSingleCellComposition():defaultSingleCellDE()
 function Harness(){const[config,setConfig]=useState(latest);return <SingleCellComparisonSetup projectId="project" sources={sources} config={config} onChange={c=>{latest=c;setConfig(c)}}/>}
 render(<Harness/>);return()=>latest
}
it('shows all denominator categories and remains descriptive without confirmed labels',async()=>{
 const config=setup(true)
 fireEvent.change(screen.getByLabelText('固定单细胞处理版本'),{target:{value:'p'}})
 fireEvent.change(screen.getByLabelText('固定人工注释版本'),{target:{value:'ann'}})
 fireEvent.click(screen.getByRole('button',{name:'读取细胞、标签与供者'}))
 await screen.findByRole('checkbox',{name:'T'})
 fireEvent.click(screen.getByRole('checkbox',{name:'T'}))
 fireEvent.change(screen.getByLabelText('分子条件'),{target:{value:'stim'}})
 fireEvent.change(screen.getByLabelText('分母条件'),{target:{value:'ctrl'}})
 expect(screen.getByText(/分母细胞 n = 4/)).toBeTruthy()
 expect(screen.getByText(/unknown: 1/)).toBeTruthy()
 expect(config().mode).toBe('descriptive');expect(config().labels_confirmed).toBe(false)
})
it('freezes same-type DE as condition × assigned label and invalidates keys on label change',async()=>{
 const config=setup(false)
 fireEvent.change(screen.getByLabelText('固定单细胞处理版本'),{target:{value:'p'}})
 fireEvent.change(screen.getByLabelText('固定人工注释版本'),{target:{value:'ann'}})
 fireEvent.click(screen.getByRole('button',{name:'读取细胞、标签与供者'}))
 await screen.findByRole('checkbox',{name:'T'})
 fireEvent.click(screen.getByRole('checkbox',{name:'T'}))
 fireEvent.change(screen.getByLabelText('分子条件'),{target:{value:'stim'}})
 fireEvent.change(screen.getByLabelText('分母条件'),{target:{value:'ctrl'}})
 fireEvent.click(screen.getByRole('button',{name:'固定同类型条件交集'}))
 await waitFor(()=>expect((config().contrasts as Contrast[])[0].numerator.observation_keys).toEqual([{processed_version_id:'p',barcode:'a'}]))
 expect((config().contrasts as Contrast[])[0].denominator.observation_keys).toEqual([{processed_version_id:'p',barcode:'c'}])
 fireEvent.click(screen.getByRole('checkbox',{name:'研究者已确认所选标签身份'}))
 expect((config().contrasts as Contrast[])[0].numerator.observation_keys).toHaveLength(1)
 fireEvent.click(screen.getByRole('checkbox',{name:'B'}))
 expect((config().contrasts as Contrast[])[0].numerator.observation_keys).toEqual([])
})

it('allows one-condition descriptive composition and explains its absent comparison',async()=>{
 const config=setup(true,true)
 fireEvent.change(screen.getByLabelText('固定单细胞处理版本'),{target:{value:'p'}})
 fireEvent.change(screen.getByLabelText('固定人工注释版本'),{target:{value:'ann'}})
 fireEvent.click(screen.getByRole('button',{name:'读取细胞、标签与供者'}))
 await screen.findByRole('checkbox',{name:'T'})
 expect(screen.getByText('当前仅有一个条件；将分子条件与分母条件选择为同一条件即可描述其组成。')).toBeTruthy()
 fireEvent.click(screen.getByRole('checkbox',{name:'T'}))
 fireEvent.change(screen.getByLabelText('分子条件'),{target:{value:'healthy'}})
 fireEvent.change(screen.getByLabelText('分母条件'),{target:{value:'healthy'}})
 expect(screen.getByText('单条件组成描述；相同条件只计数一次，不计算组间差值、比值或 P 值。')).toBeTruthy()
 expect(screen.getByText(/分母细胞 n = 4/)).toBeTruthy()
 expect(config()).toMatchObject({mode:'descriptive',numerator:'healthy',denominator:'healthy'})
})
