import { expect, test } from 'vitest'
import { isAnalysisSelection } from '../analysis/analysisSelection'
import { resultForMethod, comparisonSelection, comparisonPlan, comparisonResult } from '../analysis/comparisonFixtures'
import { isConfirmedPlan } from './analysisPlanApi'
import { validStatisticsContext } from '../analysis/statisticsContext'
import { comparisonStatisticsFixtures } from '../analysis/comparisonStatisticsFixtures'
import {type ComparisonMethod} from '../analysis/analysisSelection'
import {comparisonBackendFixture} from '../analysis/comparisonBackendFixture'

test('comparison selection fences six methods, role separation, typed groups and declaration fields',()=>{
 expect(isAnalysisSelection(comparisonSelection)).toBe(true)
 for(const patch of [{method:'student_t'},{design:'paired'},{groups:[comparisonSelection.groups[0],comparisonSelection.groups[0]]},{before_column:'A'},{posthoc:'all_pairs_holm'},{assumptions:{...comparisonSelection.assumptions,extra:true}},{extra:true}]) expect(isAnalysisSelection({...comparisonSelection,...patch})).toBe(false)
 const paired={...comparisonSelection,design:'paired',method:'paired_t',numeric_column:null,group_column:null,groups:[],pair_id_column:'A',before_column:'C',after_column:'D',missing_policy:'complete_pairs'}
 expect(isAnalysisSelection(paired)).toBe(true)
 expect(isAnalysisSelection({...paired,after_column:'C'})).toBe(false)
 expect(isAnalysisSelection({...paired,pair_id_column:'C'})).toBe(false)
 expect(isAnalysisSelection({...comparisonSelection,groups:[{kind:'number',value:'1'},{kind:'number',value:'1.00'}]})).toBe(false)
})
test('comparison confirmation requires declared design, distribution and independent approval',()=>{
 expect(isConfirmedPlan(comparisonPlan,'p1','f1')).toBe(true)
 expect(isConfirmedPlan({...comparisonPlan,selection:{...comparisonSelection,assumptions:{...comparisonSelection.assumptions,inference_confirmed:false}}},'p1','f1')).toBe(false)
 expect(isConfirmedPlan({...comparisonPlan,research_request:{...comparisonPlan.research_request,observation_structure:'paired'}},'p1','f1')).toBe(false)
 expect(isConfirmedPlan({...comparisonPlan,selection:{...comparisonSelection,assumptions:{...comparisonSelection.assumptions,distribution:'rank'}}},'p1','f1')).toBe(false)
})
test('schema4 comparison keeps v3 plan and checks exact facts and row membership',()=>{
 const base='/api/v1/projects/p1/files/f1'
 expect(validStatisticsContext(comparisonResult as never,base)).toBe(true)
 for(const patch of [{schema_version:3},{result_type:'unknown'},{statistics:{...comparisonResult.statistics,p_value:{value:NaN,method:'welch_t_two_sided'}}},{row_audit:{...comparisonResult.row_audit,group_rows:[[2,3,4],[4,6,7]]}},{statistics:{...comparisonResult.statistics,family:{policy:'none',size:1,alpha:0.05}}}]) expect(validStatisticsContext({...comparisonResult,...patch} as never,base)).toBe(false)
})
test.each(Object.keys(comparisonStatisticsFixtures) as ComparisonMethod[])('reads actual frozen %s numerical shape and rejects algorithm/role drift',method=>{
 const value=resultForMethod(method),base='/api/v1/projects/p1/files/f1'
 expect(validStatisticsContext(value as never,base)).toBe(true)
 expect(validStatisticsContext({...value,statistics:{...value.statistics,p_value:{value:0.5,method:'auto'}}} as never,base)).toBe(false)
 expect(validStatisticsContext({...value,statistics:{...value.statistics,confidence_interval:{...value.statistics.confidence_interval,simultaneous:true}}} as never,base)).toBe(false)
})
test('strict result rejects unknown fields and drift from confirmed row check',()=>{
 const base='/api/v1/projects/p1/files/f1'
 expect(validStatisticsContext({...comparisonResult,pair_ids:['private']} as never,base)).toBe(false)
 expect(validStatisticsContext({...comparisonResult,analysis_context:{...comparisonResult.analysis_context,plan:{...comparisonPlan,check:{...comparisonPlan.check,selection_check:{...comparisonResult.check,valid_count:5}}}}} as never,base)).toBe(false)
})
test('comparison reader rejects impossible ranks, zero-pair counts and negative summary spread',()=>{
 const base='/api/v1/projects/p1/files/f1',rank=resultForMethod('wilcoxon')
 expect(validStatisticsContext({...rank,statistics:{...rank.statistics,inference:{...rank.statistics.inference,zero_count:6}}} as never,base)).toBe(false)
 expect(validStatisticsContext({...rank,statistics:{...rank.statistics,statistic:{...rank.statistics.statistic,value:-1}}} as never,base)).toBe(false)
 expect(validStatisticsContext({...comparisonResult,groups:comparisonResult.groups.map(g=>({...g,statistics:{...g.statistics,std:-1}}))} as never,base)).toBe(false)
 const multi=resultForMethod('welch_anova')
 expect(validStatisticsContext({...multi,statistics:{...multi.statistics,statistic:{...multi.statistics.statistic,df_numerator:4}}} as never,base)).toBe(false)
})
test('real PlanReference includes complete resolutions bound to the frozen confirmed plan',()=>{
 const base='/api/v1/projects/p1/files/f1'
 const issue={id:'group_not_selected:all',code:'group_not_selected',severity:'warning',field:null,count:1,coordinates:['D8'],message:'excluded group',allowed_resolutions:['retain']}
 const resolutions={'group_not_selected:all':'retain'}
 const plan={...comparisonPlan,resolutions,check:{...comparisonPlan.check,issues:[issue]}}
 const value={...comparisonResult,analysis_plan:{...comparisonResult.analysis_plan,resolutions},analysis_context:{...comparisonResult.analysis_context,plan}}
 expect(validStatisticsContext(value as never,base)).toBe(true)
 for(const invalid of [{},{'group_not_selected:all':'exclude_selected_missing'},{...resolutions,unknown:'retain'},{'group_not_selected:all':true}])expect(validStatisticsContext({...value,analysis_plan:{...value.analysis_plan,resolutions:invalid}} as never,base)).toBe(false)
 const {resolutions:_omitted,...withoutResolutions}=value.analysis_plan
 expect(validStatisticsContext({...value,analysis_plan:withoutResolutions} as never,base)).toBe(false)
 expect(validStatisticsContext({...value,analysis_context:{...value.analysis_context,plan:{...plan,resolutions:{}}}} as never,base)).toBe(false)
})
test('backend public serialization reads unchanged and group identities obey the frozen 500-character bound',()=>{
 expect(validStatisticsContext(comparisonBackendFixture as never,'/api/v1/projects/p1/files/f1')).toBe(true)
 expect(isAnalysisSelection({...comparisonSelection,groups:[{kind:'text',value:'A'.repeat(501)},{kind:'text',value:'Control'}]})).toBe(false)
})
