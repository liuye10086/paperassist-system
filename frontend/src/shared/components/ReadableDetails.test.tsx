import {render,screen} from '@testing-library/react'
import {describe,it,expect} from 'vitest'
import ReadableDetails from './ReadableDetails'
describe('customer result details',()=>{
 it('omits nested technical identities while retaining scientific values and limitations',()=>{
 const {container}=render(<ReadableDetails value={{manifest_sha256:'a'.repeat(64),source_id:'private-source',methods:{q_threshold:0.05,software_version:'1.2'},limitations:['区域富集不能代表纯细胞'],summary:{observations:0,synthetic:true},shape:{features:321},sources:[{title:'原始样本',environment_digest:'b'.repeat(64)}]}}/> )
 expect(container.textContent).not.toContain('private-source');expect(container.textContent).not.toContain('a'.repeat(64));expect(container.textContent).not.toContain('environment_digest');expect(container.querySelector('pre,code')).toBeNull()
 expect(screen.getByText('数据规模')).toBeTruthy();expect(screen.getByText('321')).toBeTruthy();expect(screen.getByText('q 阈值')).toBeTruthy();expect(screen.getByText('0.05')).toBeTruthy();expect(screen.getByText('0')).toBeTruthy();expect(screen.getByText('区域富集不能代表纯细胞')).toBeTruthy();expect(screen.getByText('原始样本')).toBeTruthy();expect(screen.getByText('1.2')).toBeTruthy()
 })
 it('does not turn an unknown status into a passed check or show encoded JSON',()=>{
 const {container}=render(<ReadableDetails value={{status:'unrecognized',notes:'{"source_id":"secret","sha256":"'+'c'.repeat(64)+'"}'}}/> )
 expect(container.textContent).not.toContain('已通过');expect(container.textContent).not.toContain('secret');expect(container.textContent).not.toContain('{');expect(screen.getByText('unrecognized（待核对）')).toBeTruthy()
 })
})

it('retains observation mapping fields, comparison roles and unfamiliar scientific columns',()=>{
 const {container}=render(<ReadableDetails value={{preview_rows:[{barcode:'AA-1',donor:'D1',section:'S1',biological_replicate:'R1',status:'known'}],numerator:{label:'处理组',n:0},denominator:{label:'对照组',n:3},novel_scientific_measurement:2.5,donor_id:'donor-7',contrast_id:'treated-control',source_id:'internal-source',file_path:'C:/private/result.tsv',pending_check:{status:'pending'},fixed_check:{status:'fixed_existing_event'}}}/>)
 for(const label of ['条码','供体','切片','生物学重复','比较组','参照组','novel scientific measurement'])expect(screen.getByText(label)).toBeTruthy()
 for(const value of ['AA-1','D1','S1','R1','处理组','对照组','2.5','已知','待处理','沿用已固定的确认记录','donor-7','treated-control'])expect(screen.getByText(value)).toBeTruthy()
 expect(container.textContent).not.toContain('internal-source');expect(container.textContent).not.toContain('C:/private');expect(container.textContent).not.toContain('其他结果说明');expect(container.textContent).not.toContain('未识别')
})

it('preserves exact scientific row and field locators without showing internal source identities',()=>{
 const {container}=render(<ReadableDetails value={{sources:[{kind:'row',row_key:{feature_id:'TP53'},column:'q',source_id:'private-source'},{kind:'field',field_path:'summary.n_spots'}],object_id:'ERBB2',disease_id:'EFO_0003767',contrast_id:'treated-v-control'}}/>)
 for(const value of ['TP53','q','summary.n_spots','ERBB2','EFO_0003767','treated-v-control'])expect(screen.getByText(value)).toBeTruthy()
 expect(container.textContent).not.toContain('private-source')
})
