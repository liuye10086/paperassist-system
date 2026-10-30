import {expect,it} from 'vitest'
import {apiError,setLocale,translate} from '../../shared/i18n'
import {emptyInput,mergeAnalysisSelection,validAnalysisSelection,validInput,type AnalysisSelection} from './manuscriptTypes'

function packet(count:number,different:boolean):AnalysisSelection{
 const runs=Array.from({length:different?count:1},(_,i)=>'run-'+i),figures=Array.from({length:count},(_,i)=>'figure-'+i)
 const sources:AnalysisSelection['sources']=figures.flatMap<AnalysisSelection['sources'][number]>((id,i)=>[...(different||i===0?[{kind:'analysis_run' as const,id:runs[different?i:0],file_id:'file',role:'computed_results' as const,label:'Run',sha256:'a'.repeat(64),download_url:null,content:{id:runs[different?i:0],setup_revision:1}}]:[]),{kind:'figure',id,file_id:'file',role:'image_observation',label:'Figure',sha256:'b'.repeat(64),download_url:null,content:{analysis_run_id:runs[different?i:0]}}])
 sources.push({kind:'collection_report',id:'report',file_id:'file',role:'user_results',label:'Report',sha256:'c'.repeat(64),download_url:null,content:{text:'Report body'}})
 const group={id:'collection-version',title:'Saved collection',analysis_run_ids:runs,figure_ids:figures}
 return {selection_kind:'collection_report',project_id:'project',project_type:'sci',file_id:'file',analysis_run_id:runs[0],analysis_run_ids:runs,setup_revision:1,report_status:'selected',collection_id:'collection',collection_version_id:'version',report_id:'report',sources,results_group:group,results_groups:[group],figure_notes:figures.map((id,i)=>({figure_id:id,caption:'Saved caption '+i,panels:[]}))} as AnalysisSelection
}
it.each([[21,false],[21,true],[30,false]] as const)('merges %i items with different runs=%s without altering manual groups or captions', (count,different)=>{
 const value=packet(count,different)
 expect(validAnalysisSelection(value,'project')).toBe(true)
 const original=emptyInput('Existing user title','en')
 original.methods.procedures='Original methods'
 original.results_groups=[{id:'manual',title:'Manual group',analysis_run_ids:['run-0'],figure_ids:[]}]
 original.sources=[{kind:'analysis_run',id:'run-0',file_id:'file',role:'computed_results'}]
 original.figure_notes=[{figure_id:'figure-0',caption:'Manual caption',panels:[]}]
 const merged=mergeAnalysisSelection(original,value),repeated=mergeAnalysisSelection(merged,value)
 expect(merged.results_groups[0]).toEqual(original.results_groups[0])
 expect(merged.results_groups[1].id).toBe('collection-version')
 expect(merged.results_groups[1].figure_ids).toEqual(value.results_group.figure_ids)
 expect(merged.figure_notes[0].caption).toBe('Manual caption')
 expect(merged.figure_notes.slice(1).map(n=>n.caption)).toEqual(value.figure_notes.slice(1).map(n=>n.caption))
 expect(merged.methods).toEqual(original.methods);expect(merged.title).toBe(original.title)
 expect(validInput(merged)).toBe(true);expect(repeated).toEqual(merged)
})
it('renders the source capacity limit clearly in both languages',()=>{
 const failure=apiError({detail:{code:'manuscript_source_limit',message:'PRIVATE'}},'请求失败，请重试。')
 setLocale('zh-CN');expect(translate(failure)).toContain('50')
 setLocale('en');expect(translate(failure)).toContain('50');expect(translate(failure)).toContain('sources')
 setLocale('zh-CN')
})
