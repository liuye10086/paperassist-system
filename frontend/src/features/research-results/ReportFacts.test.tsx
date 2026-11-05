import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import ReportFacts from './ReportFacts'
import type {Fact} from './contracts'
afterEach(cleanup)
it('labels saved statistical values without exposing field paths or recalculating them',()=>{
 const facts=[{id:'mean',source_kind:'analysis_run',locator:{field_path:'overall.mean'},raw_value:4.5,display_value:'4.500',unit:'a.u.'},{id:'ready',source_kind:'analysis_run',locator:{field_path:'check.ready'},raw_value:true,display_value:'True',unit:''},{id:'custom',source_kind:'external_result',locator:{field_path:'private_field'},raw_value:0,display_value:'0',unit:''}] as unknown as Fact[]
 const saved=JSON.stringify(facts);render(<ReportFacts facts={facts}/>);
 expect(screen.getByRole('rowheader',{name:'总体 · 均值'})).toBeTruthy()
 expect(screen.getByText('4.500')).toBeTruthy();expect(screen.getByText('是')).toBeTruthy()
 expect(screen.getByRole('rowheader',{name:'private field'})).toBeTruthy()
 expect(document.body.textContent).not.toMatch(/overall.mean|private_field|unknown/)
 expect(JSON.stringify(facts)).toBe(saved)
})
it('retains scientific row identities, comparisons and distinct interval endpoints',()=>{
 const facts=[{id:'low',source_kind:'analysis_run',locator:{field_path:'statistics.confidence_interval.low'},display_value:'1.25'}, {id:'high',source_kind:'analysis_run',locator:{field_path:'statistics.confidence_interval.high'},display_value:'3.5'}, {id:'gene',source_kind:'bio_analysis_artifact',locator:{kind:'row',row_key:{feature_id:'TP53',cluster:'3'},column:'p_val_adj'},display_value:'0.003',observation_level:'cell',comparison:'A versus B'}] as unknown as Fact[]
 render(<ReportFacts facts={facts}/>);expect(screen.getByRole('rowheader',{name:'置信区间 · 下限'})).toBeTruthy();expect(screen.getByRole('rowheader',{name:'置信区间 · 上限'})).toBeTruthy();expect(screen.getByRole('rowheader',{name:/特征 TP53 · 细胞群 3 · 调整后 P 值.*细胞层级 · A versus B/})).toBeTruthy();expect(screen.getByText('0.003')).toBeTruthy()
})
