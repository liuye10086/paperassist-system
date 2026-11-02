import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import IntegrationSetup from './IntegrationSetup'
import type {Config,Source} from './contracts'
import {defaultConfig,buildPlan,planIssues} from './state'
afterEach(cleanup)
it('keeps descriptive mode explicit and freezes matching confirmations',()=>{
 let latest:Config={...defaultConfig('integration'),processed_source_ids:['left','right']}
 const sources:Source[]=['left','right'].map(id=>({source_kind:'bio_processed_dataset_version',source_id:id,title:id,sha256:'a'.repeat(64),role:'processed',locator:{kind:'object'}}))
 function Editor(){const [value,set]=useState(latest);return <IntegrationSetup config={value} sources={sources} onChange={v=>{latest=v;set(v)}}/>}
 render(<Editor/>);expect(latest.mode).toBe('descriptive');expect(planIssues(latest).length).toBeGreaterThan(0)
 fireEvent.click(screen.getByText('添加预声明特征对'));fireEvent.change(screen.getByLabelText('1 left 原特征 ID'),{target:{value:'STAT5A'}});fireEvent.change(screen.getByLabelText('1 right 原特征 ID'),{target:{value:'STAT5-alpha'}})
 fireEvent.click(screen.getByLabelText('已核对并确认冻结样本与对象对应'))
 expect(latest.pairs).toEqual([{pair_id:'pair_1',left_source_id:'left',left_feature_id:'STAT5A',right_source_id:'right',right_feature_id:'STAT5-alpha'}])
 expect(buildPlan('integration',latest,sources,0,'draft').kind).toBe('integration');expect(latest.independence_confirmed).toBe(false)
 fireEvent.change(screen.getByLabelText('统计范围'),{target:{value:'inference'}})
 expect(screen.getByLabelText('独立性与单一时间／组织选择依据')).toBeTruthy()
})
