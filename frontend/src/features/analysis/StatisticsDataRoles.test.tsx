import {describe,it,expect,vi} from 'vitest'
import {render,screen,fireEvent} from '@testing-library/react'
import StatisticsDataRoles from './StatisticsDataRoles'
import {isAnalysisSelection,initialComparison} from './analysisSelection'
import ComparisonResults from './ComparisonResults'
import {resultForMethod} from './comparisonFixtures'
import type {ComparisonResult} from './comparisonResult'
import {sourceKinds,sourceLabels} from '../research-results/contracts'
describe('statistics roles and typed research entry',()=>{
 it('accepts optional metadata while preserving old selections',()=>{
  const old={task_type:'descriptive_boxplot',sheet_name:'Sheet',numeric_column:'C',group_column:null,unit:'',missing_policy:'exclude_selected_missing'}
  expect(isAnalysisSelection(old)).toBe(true)
  expect(isAnalysisSelection({...old,data_roles:{schema_version:1,individual_id:'A',endpoint:'C',group:null,pair:null,time:'B',dose:null,structure:'repeated_long',time_order:[],dictionary:[],test_family:''}})).toBe(true)
  expect(isAnalysisSelection({...old,data_roles:{individual_id:'../secret'}})).toBe(false)
 })
 it('edits explicit individual roles through the real form',()=>{
  const change=vi.fn()
  render(<StatisticsDataRoles value={undefined} onChange={change} fields={[{column:'A',name:'ID',numeric:false,unit:''},{column:'B',name:'Time',numeric:false,unit:''},{column:'C',name:'BMI',numeric:true,unit:''}]}/>)
  fireEvent.click(screen.getByLabelText('记录数据角色与字典'))
  expect(change).toHaveBeenCalledWith(expect.objectContaining({structure:'unknown',schema_version:1}))
 })
 it('offers formal statistical runs as a typed research source',()=>{
  expect(sourceKinds).toContain('analysis_run')
  expect(sourceLabels.analysis_run).toBe('常规统计固定运行')
 })
 it('accepts two explicitly ordered long-table timepoints for paired inference',()=>{
  const x=initialComparison('Sheet','paired_t')
  expect(isAnalysisSelection({...x,numeric_column:'C',pair_id_column:'A',data_roles:{schema_version:1,individual_id:'A',endpoint:'C',group:null,pair:null,time:'B',dose:null,structure:'paired_long',time_order:['t0','t1'],dictionary:[],test_family:''}})).toBe(true)
 })
})

it('counts biological pairs rather than long input rows in the result',()=>{
 const result=resultForMethod('paired_t') as unknown as ComparisonResult
 result.selection={...result.selection,numeric_column:'C',before_column:null,after_column:null,data_roles:{schema_version:1,individual_id:'A',endpoint:'C',group:null,pair:null,time:'B',dose:null,structure:'paired_long',time_order:['t0','t1'],dictionary:[],test_family:''}}
 result.check={...result.check,row_count:10,valid_count:10}
 render(<ComparisonResults result={result}/>)
 expect(screen.getByText('纳入 5 个完整对；排除 0 行。')).toBeTruthy()
})
