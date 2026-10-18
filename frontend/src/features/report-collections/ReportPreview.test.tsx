import {afterEach,expect,test} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import ReportPreview from './ReportPreview'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();setLocale('zh-CN')})

test('English preview translates scientific enums, preserves author values and identifies unmapped facts honestly',()=>{
 setLocale('en')
 render(<ReportPreview ready sections={[{key:'quality',title:'Data quality',content:{record_count:5,missing_count:1,fields:[{name:'confirmed',unit:{status:'confirmed',value:'confirmed'}}],method:'pearson_beta_two_sided',warnings:['correlation_not_causation'],future_metric:42,rules_version:'excel_profile_v1'}}]}/>)
 expect(screen.getByText('Records')).toBeTruthy();expect(screen.getByText('Missing count')).toBeTruthy()
 expect(screen.getByText('Pearson two-sided beta test')).toBeTruthy()
 expect(screen.getByText('Correlation does not establish causation')).toBeTruthy()
 expect(screen.getByText('Confirmed')).toBeTruthy();expect(screen.getAllByText('confirmed')).toHaveLength(2)
 expect(screen.getByText('Unrecognized field: future_metric')).toBeTruthy()
 expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|excel_profile_v1|pearson_beta_two_sided/)
})

test.each([
 ['样本量较小，结果可能不稳定。','The sample is small and results may be unstable.'],
 ['缺失行按共同完整记录规则排除，原数据保留。','Records with missing selected values are excluded using common complete cases; original data are retained.'],
 ['相关不代表因果；前提由用户声明，不是程序证明。','Correlation does not establish causation; assumptions are declared by the user, not proven by the software.'],
 ['共同完整记录，不填补、不去重、不自动剔除异常值。','Common complete cases are used, without imputation, deduplication or automatic outlier removal.'],
 ['双侧推断；小样本结果可能不稳定。','Inference is two-sided; small-sample results may be unstable.'],
])('translates known system message while preserving identical author fields: %s',(message,english)=>{
 setLocale('en')
 render(<ReportPreview ready sections={[{key:'methods',title:'Methods',content:{message,research_request:{question:message},name:message,value:message,text:message}}]}/>)
 expect(screen.getByText(english)).toBeTruthy()
 expect(screen.getAllByText(message)).toHaveLength(4)
})
