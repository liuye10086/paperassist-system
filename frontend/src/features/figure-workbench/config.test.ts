import {expect,test} from 'vitest'
import {defaultConfig,configurationIssues,compatibleKinds} from './config'
test('line requires explicit x/y and ordered levels, without forcing descriptive boxplots',()=>{
 const c=defaultConfig('line','en')
 expect(configurationIssues(c)).toContain('请选择横轴字段。')
 c.projection={...c.projection!,x_column:'A',y_column:'B',x_type:'ordered'}
 expect(configurationIssues(c)).toContain('请明确有序类别顺序。')
 c.projection.x_order=['baseline','followup']
 expect(configurationIssues(c)).toEqual([])
 expect(configurationIssues(defaultConfig('boxplot','zh-CN'))).toEqual([])
})
test('bar mean requires a numeric outcome but count does not',()=>{
 const c=defaultConfig('bar','zh-CN');c.projection!.category_column='A'
 expect(configurationIssues(c)).toEqual([])
 c.projection!.bar_stat='mean'
 expect(configurationIssues(c)).toContain('请选择数值字段。')
})
test('recommendations respect the frozen result method and server availability',()=>{
 expect(compatibleKinds('correlation','pair',['scatter','line','bar','violin'])).toEqual(['scatter','line','bar','violin'])
 expect(compatibleKinds('regression',undefined,['forest','line'])).toEqual(['forest','line'])
})
