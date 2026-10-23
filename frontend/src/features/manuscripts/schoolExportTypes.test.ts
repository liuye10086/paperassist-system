import {expect,it} from 'vitest'
import {validSchoolExportPlan,validSchoolExportReport} from './schoolExportTypes'
it('rejects inconsistent quality verdicts and malformed rule decisions instead of rendering unsafe preview data',()=>{
 const report={rules_version:'school-export-v1',issues:[{id:'r',kind:'format',severity:'error',location:'toc',message:'error',source_evidence:[]}],can_export:true,scientifically_verified:false}
 expect(validSchoolExportReport(report)).toBe(false)
 expect(validSchoolExportReport({...report,can_export:false})).toBe(true)
 expect(validSchoolExportPlan({schema_version:1,rule_decisions:{}})).toBe(false)
})
