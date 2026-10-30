import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ModelConfigurationForm from './ModelConfigurationForm'
import {configurationFieldNames,isBundle,type ConfigBundle,type ConfigCatalog} from './configurationTypes'
import {testBundle,testCatalog} from './configurationTestFixtures'
import {apiError,setLocale,translate} from '../../shared/i18n'

afterEach(()=>{cleanup();setLocale('zh-CN')})
const writableCatalog={...testCatalog,field_readonly:{...testCatalog.field_readonly,'models.real_calls_enabled':false}} as ConfigCatalog
function Harness({changed}:{changed:(bundle:ConfigBundle)=>void}){
 const[bundle,setBundle]=useState(structuredClone(testBundle))
 return <ModelConfigurationForm bundle={bundle} catalog={writableCatalog} onChange={next=>{setBundle(next);changed(next)}}/>
}
it('parses new explicit true and historical false bundles, rejecting nonbooleans',()=>{
 expect(isBundle(testBundle)).toBe(true)
 expect(isBundle({...testBundle,models:{...testBundle.models,real_calls_enabled:true}})).toBe(true)
 for(const value of [0,1,'true','false',null])expect(isBundle({...testBundle,models:{...testBundle.models,real_calls_enabled:value}})).toBe(false)
})
it('requires an explicit checkbox edit and preserves independent policies, prompts and gates',()=>{
 const changed=vi.fn();render(<Harness changed={changed}/>)
 const toggle=screen.getByRole('checkbox',{name:'允许真实模型调用'}) as HTMLInputElement
 expect(toggle.checked).toBe(false);expect(changed).not.toHaveBeenCalled()
 fireEvent.click(toggle)
 const next=changed.mock.calls.at(-1)![0] as ConfigBundle
 expect(next.models.real_calls_enabled).toBe(true)
 expect({...next.models,real_calls_enabled:false}).toEqual(testBundle.models)
 expect(next.prompts).toEqual(testBundle.prompts);expect(next.ncbi.enabled).toBe(false)
 expect(screen.getByText('对新任务生效')).toBeTruthy()
 expect(screen.getByText('启用后仍须单独确认外发，并满足部署凭据、预算与任务授权要求。')).toBeTruthy()
 fireEvent.click(toggle);expect(changed.mock.calls.at(-1)![0].models.real_calls_enabled).toBe(false)
})
it('does not make the setting editable when the server catalog marks it readonly',()=>{
 render(<ModelConfigurationForm bundle={testBundle} catalog={{...testCatalog,field_readonly:{'models.real_calls_enabled':true}}} onChange={()=>{throw Error('Readonly')}}/>)
 expect((screen.getByRole('checkbox',{name:'允许真实模型调用'}) as HTMLInputElement).disabled).toBe(true)
})
it('renders opt-in scope and independent requirements in English',()=>{
 setLocale('en');render(<Harness changed={()=>{}}/>)
 expect(screen.getByRole('checkbox',{name:'Allow real model calls'})).toBeTruthy()
 expect(screen.getByText('Applies to new tasks')).toBeTruthy()
 expect(screen.getByText('Outbound confirmation, deployment credentials, budgets and task authorization are still required.')).toBeTruthy()
})
it('retains a safe configuration error identifier with actionable translations',()=>{
 const error=apiError({detail:{code:'model_configuration_disabled',message:'PRIVATE TRACE'}},'fallback')
 expect(error).toContain('model_configuration_disabled');expect(error).not.toContain('PRIVATE TRACE')
 expect(translate(error)).toContain('新任务')
 setLocale('en');expect(translate(error)).toContain('new task');expect(translate(error)).not.toContain('PRIVATE TRACE')
})
it('names the live flag explicitly in the reviewed version diff',()=>{
 expect(configurationFieldNames.real_calls_enabled).toBe('允许真实模型调用')
})
