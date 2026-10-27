import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ConfigurationDomainForms from './ConfigurationDomainForms'
import {isBundle,isCatalog,isVersion,type ConfigBundle,type ConfigCatalog} from './configurationTypes'
import {testBundle,testCatalog,testVersion} from './configurationTestFixtures'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();setLocale('zh-CN')})
function catalog(maximum=2):ConfigCatalog{return {...testCatalog,field_readonly:{...testCatalog.field_readonly,'basic.worker_concurrency':false},field_effects:{...testCatalog.field_effects,'basic.worker_concurrency':'worker_restart'},restart_required:{'basic.worker_concurrency':true},effective_ranges:{...testCatalog.effective_ranges,'basic.worker_concurrency':{minimum:1,maximum,unit:'processes'}}}}
it('decodes strict concurrency2 without rejecting configuration or catalog, and rejects all other types/values',()=>{
 const bundle={...testBundle,basic:{...testBundle.basic,worker_concurrency:2}}
 expect(isBundle(bundle)).toBe(true);expect(isVersion({...testVersion(),bundle})).toBe(true);expect(isCatalog({...catalog(),default_bundle:bundle})).toBe(true)
 for(const value of [0,3,1.5,'2',true,null])expect(isBundle({...bundle,basic:{...bundle.basic,worker_concurrency:value}})).toBe(false)
})
it('edits desired concurrency2 with ceiling and explicit restart metadata without discarding other drafts',()=>{
 const changed=vi.fn()
 function Harness(){const[bundle,setBundle]=useState<ConfigBundle>(structuredClone(testBundle));return <ConfigurationDomainForms domain="basic" bundle={bundle} catalog={catalog()} onChange={b=>{setBundle(b);changed(b)}}/>}
 render(<Harness/>);fireEvent.change(screen.getByLabelText('最大行数（行）'),{target:{value:'85000'}})
 fireEvent.change(screen.getByLabelText('Worker 期望并发数'),{target:{value:'2'}})
 expect(screen.getByLabelText('Worker 期望并发数')).toHaveProperty('value','2');expect(changed.mock.calls.at(-1)![0].basic.max_rows).toBe(85000)
 expect(screen.getByText('保存或启用仅改变期望配置；实际并发须在维护窗口显式重启后核对运行状态。')).toBeTruthy()
 expect(screen.getByText('部署并发上限：2')).toBeTruthy();expect(screen.queryByRole('button',{name:/重启/})).toBeNull()
})
it('does not authorize option2 above deployment ceiling or when catalog metadata is missing',()=>{
 const view=render(<ConfigurationDomainForms domain="basic" bundle={testBundle} catalog={catalog(1)} onChange={()=>{}}/>);
 expect(screen.getByRole('option',{name:'2'})).toHaveProperty('disabled',true)
 view.rerender(<ConfigurationDomainForms domain="basic" bundle={testBundle} catalog={{...catalog(),effective_ranges:{}}} onChange={()=>{}}/>);
 expect(screen.getByRole('option',{name:'2'})).toHaveProperty('disabled',true)
})
it('translates new desired and explicit restart text into English',()=>{
 setLocale('en');render(<ConfigurationDomainForms domain="basic" bundle={testBundle} catalog={catalog()} onChange={()=>{}}/>);
 expect(screen.getByLabelText('Desired Worker concurrency')).toBeTruthy();expect(screen.getByText('Deployment concurrency ceiling: 2')).toBeTruthy()
 expect(screen.getByText('Saving or activating changes only the desired configuration. Verify actual concurrency after an explicit restart in a maintenance window.')).toBeTruthy()
})
