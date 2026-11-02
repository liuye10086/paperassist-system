import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import QpcrSetup,{defaultQpcrConfig} from './QpcrSetup'
import {buildPlan,planIssues} from './state'
import type {Source,Config} from './contracts'
afterEach(cleanup)
const source:Source={source_kind:'original_file',source_id:'file1',sha256:'a'.repeat(64),role:'table',locator:{kind:'object',parse_version_id:'parse1'}}
it('selects raw long table and its parse identity without inventing matrix sample keys',()=>{
 const change=vi.fn(),config=defaultQpcrConfig();render(<QpcrSetup config={config} onChange={change} sources={[source]}/>);
 fireEvent.click(screen.getByLabelText(/已选原始表/));expect(change).toHaveBeenCalledWith(expect.objectContaining({file_source_id:'file1',parse_version_id:'parse1'}));
 expect(screen.getByText(/技术孔不增加生物学 n/)).toBeTruthy();
 expect(planIssues(config).some(i=>i.includes('qPCR'))).toBe(true)
})
it('freezes the entire contrast family and switches method explicitly',()=>{
 function Editor(){const [config,setConfig]=useState<Config>({...defaultQpcrConfig(),file_source_id:'file1',parse_version_id:'parse1'});return <QpcrSetup config={config} onChange={setConfig} sources={[source]}/>}
 render(<Editor/>);fireEvent.change(screen.getByLabelText('qPCR 设计'),{target:{value:'paired'}});
 expect((screen.getByLabelText('qPCR 检验') as HTMLSelectElement).value).toBe('paired_t');
 expect(screen.getByLabelText('同板配对推断')).toBeTruthy();
 const cfg=defaultQpcrConfig();cfg.family_contrast_ids=[];const body=buildPlan('qPCR',cfg,[source],0,'draft');expect(body.config.family_contrast_ids).toEqual(['treated_control']);expect(body.sources[0].sha256).toBe(source.sha256)
})
it('shows efficiency above two as a review warning while retaining entered values',()=>{
 const config={...defaultQpcrConfig(),quantification:'efficiency',efficiencies:{target:{value:2.05,representation:'amplification_factor',source:'measured'}}};render(<QpcrSetup config={config} onChange={vi.fn()} sources={[source]}/>);
 expect(screen.getByText(/大于 2.*合理性提示/)).toBeTruthy();expect((screen.getByLabelText('target 效率数值') as HTMLInputElement).value).toBe('2.05')
})
