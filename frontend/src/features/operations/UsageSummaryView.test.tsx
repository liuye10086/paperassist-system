import {cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {ProvenanceView} from './UsageSummaryView'
import type {Summary,Provenance} from './operationsApi'
const summary:Summary={call_count:1,estimated_micro_usd:10,estimated_unknown_count:1,actual_micro_usd:null,actual_known_micro_usd:0,actual_unknown_count:1,reconciled_count:0,partial_count:0,pending_count:1,not_applicable_count:0,reserved_micro_usd:5,accounted_micro_usd:0,tool_call_count:2,tool_call_unknown_count:1,input_tokens:{known:1,unknown_count:1},output_tokens:{known:1,unknown_count:1},total_tokens:{known:2,unknown_count:1}}
const sources:Provenance={openai_live:summary,synthetic_fixture:{...summary,call_count:2},unknown:{...summary,call_count:3}}
afterEach(cleanup)
it('shows one source at a time while retaining unknown and synthetic disclosures',()=>{
 render(<ProvenanceView value={sources} layered/>)
 expect(screen.getByRole('region',{name:'已证实真实调用'})).toBeTruthy()
 expect(screen.queryByRole('region',{name:'合成验收样例'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'来源未知'}))
 const unknown=screen.getByRole('region',{name:'来源未知'})
 expect(within(unknown).getByText('缺少来源证据，不计为已证实真实支出。')).toBeTruthy()
 expect(within(unknown).getByText('未知（尚未完整核对）')).toBeTruthy()
 expect(within(unknown).getByText('调用次数').nextElementSibling?.textContent).toBe('3')
 expect(screen.queryByRole('region',{name:'已证实真实调用'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'合成验收样例'}))
 const fixture=screen.getByRole('region',{name:'合成验收样例'})
 expect(within(fixture).getByText('此栏为合成样例，不代表真实供应商支出。')).toBeTruthy()
 expect(within(fixture).getByText('调用次数').nextElementSibling?.textContent).toBe('2')
 fireEvent.click(screen.getByRole('button',{name:'已证实真实调用'}))
 expect(within(screen.getByRole('region',{name:'已证实真实调用'})).getByText('调用次数').nextElementSibling?.textContent).toBe('1')
})
it('retains all three source sections in the legacy layout',()=>{
 render(<ProvenanceView value={sources}/>)
 expect(screen.getAllByRole('region')).toHaveLength(3)
 expect(screen.queryByRole('navigation')).toBeNull()
})
