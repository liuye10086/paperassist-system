import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import MicrobiomeSetup,{defaultMicrobiomeConfig} from './MicrobiomeSetup'
import type {Config} from './contracts'
import {buildPlan,planIssues} from './state'
afterEach(cleanup)
it('freezes typed microbiome source, closure and design without permitting paired unrestricted beta',()=>{
 function Editor(){const [config,onChange]=useState<Config>({...defaultMicrobiomeConfig(),beta_inference:true});return <MicrobiomeSetup config={config} onChange={onChange} sources={[{source_kind:'bio_processed_dataset_version',source_id:'micro',sha256:'a'.repeat(64),role:'processed',locator:{kind:'object'}}]}/>}
 render(<Editor/>);fireEvent.change(screen.getByLabelText('微生物组设计'),{target:{value:'paired'}})
 expect((screen.getByLabelText('alpha 检验') as HTMLSelectElement).value).toBe('paired_t')
 expect((screen.getByLabelText('执行独立可交换单因素 PERMANOVA，并同时报告 PERMDISP') as HTMLInputElement).checked).toBe(false)
 expect(screen.getByText(/Simpson=1−Σp²/)).toBeTruthy()
 const config=defaultMicrobiomeConfig();expect(planIssues(config)[0]).toContain('微生物组')
 expect(buildPlan('micro',config,[],0,'draft').config.family_contrast_ids).toEqual([])
 expect(config.taxonomy_na_values).toContain(String.fromCharCode(92)+'N')
})
