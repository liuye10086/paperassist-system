import {describe,it,expect} from 'vitest'
import {isAnalysisSelection} from './analysisSelection'
const draft=(method:string)=>({task_type:'regression',method,sheet_name:'Sheet1',outcome_column:null,covariates:[],outcome_unit:'',positive:null,negative:null,id_column:null,missing_policy:'complete_cases',assumptions:{independent_units:false,inference_confirmed:false}})
describe('batch04 model selections',()=>{
 it.each(['ols','logistic'])('accepts exact %s draft but rejects future fields',method=>{const v=draft(method);expect(isAnalysisSelection(v)).toBe(true);expect(isAnalysisSelection({...v,auto_select:true})).toBe(false)})
 it('rejects invalid categorical encoding',()=>expect(isAnalysisSelection({...draft('ols'),covariates:[{column:'B',type:'categorical',unit:'',levels:[{kind:'nonsense',value:'a'}],reference:null}]})).toBe(false))
})
it('does not permit OLS binary encoding or duplicate binary identities',()=>{const positive={kind:'number',value:'1'};expect(isAnalysisSelection({...draft('ols'),positive})).toBe(false);expect(isAnalysisSelection({...draft('logistic'),positive,negative:positive})).toBe(false)})
