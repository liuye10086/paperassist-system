import {expect,test} from 'vitest'
import {isConfiguredFigure,isBoundExplanation} from './contracts'
import {correlationResult} from '../analysis/correlationFixtures'
const figure={schema_version:5,id:'new-figure',analysis_run_id:correlationResult.id,file_id:'f1',setup_revision:2,source:correlationResult.source,source_sha256:correlationResult.source_sha256,sha256:'b'.repeat(64),figure_kind:'scatter',figure_config_version_id:'version1',language:'zh-CN' as const,title:'Relation',caption:'',numbering_mode:'external',figure_number:null,verification:{status:'matched'},engine:{id:'openai_figure_workbench_v1'}}
test('new figure rejects legacy schema and crossed configuration, source or language',()=>{
 expect(isConfiguredFigure(figure,correlationResult.source,'zh-CN',correlationResult.id,'version1')).toBe(true)
 for(const changed of [{schema_version:2},{figure_config_version_id:null},{language:'en'},{analysis_run_id:'other'},{source_sha256:'c'.repeat(64)},{verification:{status:'mismatched'}}])expect(isConfiguredFigure({...figure,...changed},correlationResult.source,'zh-CN',correlationResult.id,'version1')).toBe(false)
})
test('six-section explanations require exact new image binding',()=>{
 const explanation={schema_version:5,id:'exp',figure_id:figure.id,figure_sha256:figure.sha256,analysis_run_id:figure.analysis_run_id,language:'zh-CN',verification:{status:'references_checked'},sections:['purpose','data','methods','results','interpretation','paper_text'].map(key=>({key,title:key,text:'Checked text'})),limitations:[]}
 expect(isBoundExplanation(explanation,figure)).toBe(true)
 expect(isBoundExplanation({...explanation,engine:{id:'figure_explanation_v3'}},figure)).toBe(true)
 expect(isBoundExplanation({...explanation,engine:{id:'figure_explanation_v4'}},figure)).toBe(true)
 expect(isBoundExplanation({...explanation,engine:{id:'figure_explanation_v999'}},figure)).toBe(false)
 expect(isBoundExplanation({...explanation,figure_id:'old'},figure)).toBe(false)
 expect(isBoundExplanation({...explanation,sections:explanation.sections.slice(1)},figure)).toBe(false)
 expect(isBoundExplanation({...explanation,schema_version:2},figure)).toBe(false)
})
