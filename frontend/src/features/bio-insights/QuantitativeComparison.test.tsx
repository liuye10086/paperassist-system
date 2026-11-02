import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import ComparisonSetup from './ComparisonSetup'
import {buildPlan,planIssues} from './state'
import {defaultQuantitativeConfig,readQuantitativeSamples,type SampleContrast} from './quantitative'
import type {Config,Source} from './contracts'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const sources:Source[]=[{source_kind:'bio_processed_dataset_version',source_id:'p1',role:'processed',sha256:'a'.repeat(64),locator:{kind:'object'}}]
it('freezes exact sample IDs and leaves biological independence unconfirmed',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({items:[{sample_id:'T1',condition:'treated',retained:true},{sample_id:'T2',condition:'treated',retained:false},{sample_id:'C1',condition:'control',retained:true}],total:3,observation_level:'sample'}))
 let current:Config=defaultQuantitativeConfig();function Harness(){const[c,set]=useState(current);current=c;return <ComparisonSetup projectId="proj" config={c} sources={sources} onChange={set}/>}
 render(<Harness/>);fireEvent.click(screen.getByText('读取完整固定样本'));await screen.findByText('已读取 3 个固定样本。')
 fireEvent.change(screen.getByLabelText('样本分组值'),{target:{value:'treated'}});fireEvent.click(screen.getByText('加入当前组'))
 expect((current.contrasts as SampleContrast[])[0].groups[0].sample_keys).toEqual([{processed_version_id:'p1',sample_id:'T1'}]);expect(current.independence_confirmed).toBe(false)
 expect(screen.queryByText(/spot/)).toBeNull();expect(JSON.stringify(buildPlan('test',current,sources,0,'draft'))).not.toContain('barcode')
})
it('changes methods and group count explicitly while preserving the full family',()=>{
 let current:Config=defaultQuantitativeConfig();function Harness(){const[c,set]=useState(current);current=c;return <ComparisonSetup projectId="proj" config={c} sources={sources} onChange={set}/>}
 render(<Harness/>);fireEvent.change(screen.getByLabelText('样本比较设计'),{target:{value:'multiple'}})
 expect(current.method).toBe('welch_anova');expect((current.contrasts as SampleContrast[])[0].groups).toHaveLength(3)
 fireEvent.click(screen.getByText('添加比较（最多 10 个）'))
 expect(buildPlan('test',current,sources,0,'draft').config.family_contrast_ids).toEqual(['contrast_1','contrast_2'])
 fireEvent.change(screen.getByLabelText('定量统计路径'),{target:{value:'bulk_counts'}})
 expect(current).toMatchObject({mode:'bulk_counts',method:'deseq2_wald',analysis_layer:'raw_counts',design:'independent',inference_unit:'biological',size_factor_method:'ratio'})
 expect((current.contrasts as SampleContrast[]).every(c=>c.groups.length===2)).toBe(true)
})
it('allows unknown mixed-species identifiers without claiming a biological replicate',()=>{
 const c:Config={...defaultQuantitativeConfig(),namespace:'protein_label',reference_version:'MSstats-DDARawData',species_taxon_id:null,inference_unit:'technical'}
 expect(planIssues(c)).toEqual([]);expect(c.technical_exploration_confirmed).toBe(false)
})
it('rejects spatial rows and duplicate sample keys instead of aliasing them',async()=>{
 vi.mocked(apiFetch).mockResolvedValueOnce(Response.json({items:[{barcode:'A'}],total:1,observation_level:'spot'}))
 await expect(readQuantitativeSamples('p',sources,new AbortController().signal)).rejects.toThrow()
 vi.mocked(apiFetch).mockResolvedValueOnce(Response.json({items:[{sample_id:'A'},{sample_id:'A'}],total:2,observation_level:'sample'}))
 await expect(readQuantitativeSamples('p',sources,new AbortController().signal)).rejects.toThrow()
})
it('reads every source page and keeps repeated sample names in separate versions distinct',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('page=2')?{items:[{sample_id:'B'}],total:1001,observation_level:'sample'}:String(url).includes('/p1/')?{items:Array.from({length:1000},(_,i)=>({sample_id:`A${i}`})),total:1001,observation_level:'sample'}:{items:[{sample_id:'A0'}],total:1,observation_level:'sample'}))
 const rows=await readQuantitativeSamples('p',[...sources,{...sources[0],source_id:'p2'}],new AbortController().signal)
 expect(rows).toHaveLength(1002);expect(rows.slice(-2).map(r=>[r.processed_version_id,r.sample_id])).toEqual([['p1','B'],['p2','A0']]);expect(vi.mocked(apiFetch)).toHaveBeenCalledTimes(3)
})
