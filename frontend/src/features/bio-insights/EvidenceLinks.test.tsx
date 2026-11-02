import {useState} from 'react'
import {fireEvent,render,screen} from '@testing-library/react'
import {expect,it} from 'vitest'
import EvidenceLinks,{defaultEvidenceMatrix} from './EvidenceLinks'
import {buildPlan,planIssues} from './state'
it('keeps fixed candidate identity, unknown references and evidence separate from comparison recipes',()=>{
 let latest=defaultEvidenceMatrix()
 function Editor(){const [config,set]=useState(latest);return <EvidenceLinks projectId="p" config={config} sources={[]} onChange={v=>{latest=v;set(v)}}/>}
 render(<Editor/>);fireEvent.click(screen.getByRole('button',{name:'添加固定候选对象'}));fireEvent.change(screen.getByLabelText('候选 1 对象 ID'),{target:{value:'ERBB2'}});fireEvent.change(screen.getByLabelText('候选 1 原特征 ID'),{target:{value:'HER2'}})
 expect(latest.candidates).toEqual([expect.objectContaining({object_id:'ERBB2',feature_id:'HER2',reference_version:'unknown'})])
 expect(screen.getByText(/不同依赖组不证明独立/)).toBeTruthy()
 const advanced=screen.getByText('更多关联设置').closest('details')!;expect(advanced.open).toBe(false);fireEvent.click(screen.getByText('更多关联设置'));expect(advanced.open).toBe(true);fireEvent.change(screen.getByLabelText('独立支持请求 JSON'),{target:{value:'[{"evidence_source_id":"fixed-e","result_source_id":"fixed-result"}]'}});fireEvent.click(screen.getByRole('button',{name:'采用独立支持准入请求'}));expect(latest.independent_support_requests).toEqual([{evidence_source_id:'fixed-e',result_source_id:'fixed-result'}])
 const body=buildPlan('evidence',latest,[],0,'draft');expect(body.config).not.toHaveProperty('source_contrasts');expect(body.config).not.toHaveProperty('weights')
 expect(planIssues({...latest,candidates:[{object_id:'STAT5A'}],evidence_source_ids:['e']})).toEqual([])
})
