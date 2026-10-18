import {afterEach,expect,test} from 'vitest'
import {setLocale,translate} from './index'
afterEach(()=>setLocale('zh-CN'))
test('analysis entry instruction includes all three available analysis families in English',()=>{
 setLocale('en')
 expect(translate('描述统计、相关分析或组间比较：在所选整理版本的分析计划中选择方法与图型。')).toBe('Descriptive, correlation or group comparison analysis: choose the method and chart in the analysis plan for the selected prepared version.')
})
