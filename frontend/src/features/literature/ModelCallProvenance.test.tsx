import {afterEach,expect,it} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import {setLocale} from '../../shared/i18n'
import ModelCallHistory from './ModelCallHistory'
import {validSavedModelCall,type SavedModelCall} from './assistanceApi'

const call:SavedModelCall={model:'test-model',status:'completed',provider_status:'completed',error_code:null,provenance:'not_recorded',usage_status:'pending',usage:null,estimated_cost_micro_usd:null,created_at:'2026-10-27T00:00:00Z'}
afterEach(()=>{cleanup();setLocale('zh-CN')})
it.each(['openai_live','synthetic_fixture','not_recorded'] as const)('accepts only saved source enum %s',provenance=>{
 expect(validSavedModelCall({...call,provenance})).toBe(true)
 expect(validSavedModelCall({...call,provenance:'real_by_model_name'})).toBe(false)
})
it.each(['zh-CN','en'] as const)('shows mixed live, fixture and unknown calls without turning unknown costs into zero in %s',locale=>{
 setLocale(locale)
 render(<ModelCallHistory calls={(['openai_live','synthetic_fixture','not_recorded'] as const).map(provenance=>({...call,provenance}))}/>)
 for(const text of locale==='en'?['OpenAI live call','Synthetic fixture','Historical record: provenance not recorded']:['OpenAI真实调用','合成调用替身','历史记录：来源未标注'])expect(screen.getByText(text)).toBeTruthy()
 expect(screen.getAllByText(locale==='en'?'Cost unknown; reconciliation pending':'费用未知，待核对')).toHaveLength(3)
 expect(document.body.textContent).not.toContain('0.000000')
})
