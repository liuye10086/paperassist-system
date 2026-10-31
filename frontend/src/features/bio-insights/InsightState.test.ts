import {describe,it,expect} from 'vitest'
import {defaultConfig,buildPlan,selectObservations,displayRaw,validateRecipe} from './state'
describe('bio insight fixed configuration',()=>{
 it('resolves cluster selection to exact composite observation keys',()=>{expect(selectObservations([{processed_version_id:'p1',barcode:'A',cluster:'0',retained:true},{processed_version_id:'p2',barcode:'A',cluster:'1',retained:true},{processed_version_id:'p1',barcode:'B',cluster:'0',retained:false}], 'cluster','0')).toEqual([{processed_version_id:'p1',barcode:'A'}])})
 it('preserves zero, false and explicit NA separately',()=>{expect([0,false,'NA',null].map(displayRaw)).toEqual(['0','false','NA','NA（空值）'])})
 it('builds draft donor plans without pretending missing independence was confirmed',()=>{const config=defaultConfig('comparison');config.mode='donor_unpaired';const body=buildPlan('design',config,[],0,'draft');expect(body.decision).toBe('draft');expect(body.config.independence_confirmed).toBe(false);expect(body.config.family_contrast_ids).toEqual(['contrast_1'])})
 it('rejects candidate overflow and unknown step sources',()=>{expect(validateRecipe({result_source_ids:['a'],primary_result_source_id:'a',steps:[{operation:'threshold',source_ids:['b']}]})).toContain('步骤引用了未选择的结果来源。');expect(validateRecipe({result_source_ids:Array.from({length:11},(_,i)=>String(i)),primary_result_source_id:'0',steps:Array(21).fill({operation:'union'})})).toContain('最多选择 10 个来源、20 个顺序步骤。')})
})
