import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import FeatureExtractionSetup from './FeatureExtractionSetup'
import type {Config} from './contracts'
import {buildPlan,defaultConfig,planIssues} from './state'
afterEach(cleanup)
it('freezes one model and author chain, typed filters, and removes orphan selection',()=>{
 let latest:Config=defaultConfig('feature_extract')
 function Editor(){const [config,set]=useState(latest);return <FeatureExtractionSetup config={config} onChange={v=>{latest=v;set(v)}} sources={[{title:'Structure',source_kind:'bio_resource_version',source_id:'r1',sha256:'a'.repeat(64),role:'feature_input',locator:{kind:'object'}}]}/>}
 render(<Editor/>);expect(planIssues(latest)).toHaveLength(1)
 fireEvent.click(screen.getByLabelText(/Structure/));fireEvent.click(screen.getByLabelText('此资源是结构，指定 model／chain'))
 fireEvent.change(screen.getByLabelText('Model（r1）'),{target:{value:'2'}})
 fireEvent.change(screen.getByLabelText('Author chain（r1）'),{target:{value:'B'}})
 fireEvent.click(screen.getByText('添加特征筛选条件'))
 fireEvent.change(screen.getByLabelText('步骤 1 特征'),{target:{value:'ca_count'}})
 expect(latest.structure_selections).toEqual([{resource_source_id:'r1',model_id:2,chain_id:'B'}])
 expect(buildPlan('features',latest,[],0,'draft').kind).toBe('feature_extract')
 expect(latest).not.toHaveProperty('contrasts');expect(latest).not.toHaveProperty('q_threshold')
 fireEvent.click(screen.getByLabelText(/Structure/));expect(latest.structure_selections).toEqual([])
})
