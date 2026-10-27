import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ConfigurationDomainForms from './ConfigurationDomainForms'
import {configurationDomains,domainNames,type ConfigBundle,type ConfigCatalog,type ConfigDomain} from './configurationTypes'
import {testBundle,testCatalog} from './configurationTestFixtures'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();setLocale('zh-CN')})
function Harness({changed}:{changed:(b:ConfigBundle)=>void}){const[bundle,setBundle]=useState(structuredClone(testBundle) as ConfigBundle),[domain,setDomain]=useState<ConfigDomain>('models');return <><nav>{configurationDomains.map(d=><button key={d} onClick={()=>setDomain(d)}>{domainNames[d]}</button>)}</nav><ConfigurationDomainForms domain={domain} bundle={bundle} catalog={testCatalog as ConfigCatalog} onChange={b=>{setBundle(b);changed(b)}}/></>}
it('edits actual controls in all seven domains without resetting the other domains or fixed gates',()=>{
 const changed=vi.fn();render(<Harness changed={changed}/>);
 fireEvent.change(screen.getByLabelText('输入价格（微美元/百万 Token）'),{target:{value:'25'}})
 fireEvent.click(screen.getByRole('button',{name:'有限说明与工作流'}));fireEvent.change(screen.getByRole('textbox',{name:/有限说明段/}),{target:{value:'Bounded synthetic preference'}})
 fireEvent.click(screen.getByRole('button',{name:'NCBI'}));fireEvent.change(screen.getByLabelText('缓存有效期（秒）'),{target:{value:'0'}})
 fireEvent.click(screen.getByRole('button',{name:'基础参数'}));fireEvent.change(screen.getByLabelText('最大行数（行）'),{target:{value:'90000'}})
 fireEvent.click(screen.getByRole('button',{name:'期刊规则'}));fireEvent.change(screen.getByLabelText('默认建议数量'),{target:{value:'2'}})
 fireEvent.click(screen.getByRole('button',{name:'学校模板规则'}));fireEvent.click(screen.getByRole('button',{name:'新增标题映射'}));fireEvent.change(screen.getByLabelText('映射文字 1'),{target:{value:'Synthetic heading'}})
 fireEvent.click(screen.getByRole('button',{name:'审稿与评审规则'}));fireEvent.change(screen.getByLabelText('默认文档语言'),{target:{value:'en'}});fireEvent.click(screen.getByRole('button',{name:'下移 实验'}))
 const final=changed.mock.calls.at(-1)![0] as ConfigBundle
 expect(final.models.writing.execution.policy.price.input_micro_usd_per_million).toBe(25);expect(final.prompts.writing_instruction).toBe('Bounded synthetic preference');expect(final.ncbi.cache_ttl_seconds).toBe(0);expect(final.basic.max_rows).toBe(90000);expect(final.journals.default_count).toBe(2);expect(final.schools.heading_aliases).toEqual([{text:'Synthetic heading',role:'heading1'}]);expect(final.review.category_order[1]).toBe('experiment');expect(final.review.default_language).toBe('en');expect(final.models.real_calls_enabled).toBe(false);expect(final.review.require_confirmation).toBe(true)
})
it('renders installed school support and fixed policy restrictions in English',()=>{
 setLocale('en');const b=structuredClone(testBundle) as ConfigBundle;b.models.literature=structuredClone(b.models.writing)
 const view=render(<ConfigurationDomainForms domain="schools" bundle={b} catalog={testCatalog as ConfigCatalog} onChange={()=>{}}/>);expect(screen.getByText('No supported school has passed real-material acceptance.')).toBeTruthy();expect(screen.getAllByText('Conflicts require manual confirmation').length).toBeGreaterThan(0)
 view.rerender(<ConfigurationDomainForms domain="models" bundle={b} catalog={testCatalog as ConfigCatalog} onChange={()=>{}}/>);fireEvent.change(screen.getByLabelText('Configured operation'),{target:{value:'literature'}});expect(screen.getByLabelText('Input price (micro-USD/million tokens)').closest('fieldset')?.disabled).toBe(true);expect(screen.queryByLabelText(/API key|endpoint|password/i)).toBeNull()
})
