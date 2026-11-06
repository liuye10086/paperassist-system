import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import SingleCellTopicSetup,{defaultSingleCellTopic} from './SingleCellTopicSetup'
import {planIssues,buildPlan} from './state'
import type {Config,Source} from './contracts'

afterEach(cleanup)
const sources:Source[]=[{source_kind:'bio_processed_dataset_version',source_id:'p',title:'PBMC',role:'processed',sha256:'a'.repeat(64),locator:{kind:'object'}}]
it('requires a root and its basis before a trajectory plan can run',()=>{
 let latest:Config=defaultSingleCellTopic('p')
 function Editor(){const[c,set]=useState(latest);return <SingleCellTopicSetup projectId="p1" config={c} sources={sources} onChange={v=>{latest=v;set(v)}}/>}
 render(<Editor/>);expect(planIssues(latest).length).toBeGreaterThan(0)
 fireEvent.change(screen.getByLabelText('根聚类 ID'),{target:{value:'0'}})
 fireEvent.change(screen.getByLabelText('根节点选择依据'),{target:{value:'工程验证根，不代表真实时间'}})
 expect(planIssues(latest)).toEqual([])
 expect(buildPlan('轨迹',latest,sources,0,'draft').config.schema_version).toBe(2)
})
it('retains explicit TF selection and two different seeds',()=>{
 const config={...defaultSingleCellTopic('p'),method:'genie3',gene_ids:['g1','g2'],tf_ids:['g1'],tf_basis:'文献清单'}
 render(<SingleCellTopicSetup projectId="p1" config={config} sources={sources} onChange={()=>{}}/>)
 expect(screen.getByLabelText('TF 基因 ID（必须包含在目标基因集合中）')).toBeTruthy()
 expect(planIssues(config)).toEqual([])
 expect(planIssues({...config,stability_seed:0}).length).toBeGreaterThan(0)
})
it('marks the LR resource as a limited literature demonstration',()=>{
 render(<SingleCellTopicSetup projectId="p1" config={{...defaultSingleCellTopic('p'),method:'cellchat'}} sources={sources} onChange={()=>{}}/>)
 expect(screen.getByText(/3 条文献 LR/)).toBeTruthy()
 expect(screen.getByText(/细胞置换 P/)).toBeTruthy()
})
it('records explicit species for old inputs without guessing it',()=>{
 let latest:Config={...defaultSingleCellTopic('p'),method:'cellchat',annotation_source_id:'a',label_ids:['T','B']}
 function Editor(){const[c,set]=useState(latest);return <SingleCellTopicSetup projectId="p1" config={c} sources={sources} onChange={v=>{latest=v;set(v)}}/>}
 render(<Editor/>);expect(latest.species_taxon_id).toBeUndefined()
 fireEvent.change(screen.getByLabelText('物种'),{target:{value:'9606'}})
 expect(latest.species_taxon_id).toBe(9606);expect(planIssues(latest).length).toBeGreaterThan(0)
 fireEvent.change(screen.getByLabelText('物种依据（补充物种时填写）'),{target:{value:'Original sample metadata: Homo sapiens'}})
 expect(planIssues(latest)).toEqual([])
 fireEvent.change(screen.getByLabelText('专题方法'),{target:{value:'slingshot'}})
 expect(latest.species_taxon_id).toBeUndefined();expect(latest.species_basis).toBeUndefined()
})
