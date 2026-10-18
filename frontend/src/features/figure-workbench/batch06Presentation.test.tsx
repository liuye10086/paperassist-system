import {expect,test,afterEach} from 'vitest'
import {render,screen,cleanup} from '@testing-library/react'
import {isPresentation} from './presentation'
import FigureDescription from './FigureDescription'
import {publicEntries} from '../report-collections/contracts'
import {setLocale} from '../../shared/i18n'
export const presentation={schema_version:1 as const,axes:{x:{label:'类别原文',unit:''},y:{label:'记录数',unit:'条'}},legend:{title:'组别原文',entries:[{label:'A',color:'#0072B2'}]},color_scale:{label:'相关系数',min:-1,max:1,center:0,ticks:[-1,0,1],palette:['#2166AC','#F7F7F7','#B2182B']},abbreviations:[{term:'SD',definition:'样本标准差'}],statistical_notes:['仅描述已确认记录']}
afterEach(()=>{cleanup();setLocale('zh-CN')})
test('presentation rejects unknown versions, unsafe colors, nonfinite scales and metadata additions',()=>{
 expect(isPresentation(presentation)).toBe(true)
 for(const changed of [{schema_version:3},{legend:{...presentation.legend,entries:[{label:'A',color:'url(secret)'}]}},{color_scale:{...presentation.color_scale,max:Infinity}},{internal_id:'secret'},{axes:{...presentation.axes,y:{label:'Y',unit:42}}}])expect(isPresentation({...presentation,...changed})).toBe(false)
})
test.each(['zh-CN','en'] as const)('description renders author text, number and scientific metadata in %s',locale=>{
 setLocale(locale);render(<FigureDescription title="Author title" caption="Author caption" presentation={presentation} number={7}/>);
 expect(screen.getByText(/7.*Author title/)).toBeTruthy();expect(screen.getByText('Author caption')).toBeTruthy();expect(screen.getByText(/类别原文/)).toBeTruthy();expect(screen.getByText(/SD.*样本标准差/)).toBeTruthy();expect(screen.getByText('仅描述已确认记录')).toBeTruthy();expect(document.body.textContent).not.toMatch(/schema_version|color_scale/)
})
test('collection keeps evidence labels and values while hiding reference keys',()=>{
 const result=JSON.stringify(publicEntries({evidence:[{key:'private_reference',label:'有效人数',value:8}],id:'secret',sha256:'a'.repeat(64)}));expect(result).toContain('有效人数');expect(result).toContain('8');expect(result).not.toContain('private_reference');expect(result).not.toContain('secret')
})
import {isConfiguredFigure,isBoundExplanation} from './contracts'
import {correlationResult} from '../analysis/correlationFixtures'
import ReportPreview from '../report-collections/ReportPreview'
const f={schema_version:5,id:'figure',analysis_run_id:correlationResult.id,file_id:'f1',setup_revision:2,source:correlationResult.source,source_sha256:correlationResult.source_sha256,sha256:'b'.repeat(64),figure_kind:'scatter',figure_config_version_id:'version1',language:'zh-CN' as const,title:'Title',caption:'Caption',numbering_mode:'external',figure_number:null,verification:{status:'matched'},engine:{id:'openai_figure_workbench_v2'},presentation}
test('v2 requires valid presentation while v1 remains readable without metadata',()=>{
 expect(isConfiguredFigure(f,correlationResult.source,'zh-CN')).toBe(true)
 expect(isConfiguredFigure({...f,presentation:undefined},correlationResult.source,'zh-CN')).toBe(false)
 expect(isConfiguredFigure({...f,engine:{id:'openai_figure_workbench_v3'}},correlationResult.source,'zh-CN')).toBe(false)
 expect(isConfiguredFigure({...f,presentation:undefined,engine:{id:'openai_figure_workbench_v1'}},correlationResult.source,'zh-CN')).toBe(true)
})
test('explanation validates evidence scalars and exact binding',()=>{
 const e={schema_version:5,id:'exp',figure_id:f.id,figure_sha256:f.sha256,analysis_run_id:f.analysis_run_id,language:'zh-CN',verification:{status:'references_checked'},sections:['purpose','data','methods','results','interpretation','paper_text'].map(key=>({key,title:key,text:'Fact',evidence:[{key:'valid_n',label:'有效人数',value:3}]})),limitations:['研究设计未提供']}
 expect(isBoundExplanation(e,f)).toBe(true)
 expect(isBoundExplanation({...e,sections:e.sections.map(s=>({...s,evidence:[{key:'valid_n',label:'人数',value:{id:'private'}}]}))},f)).toBe(false)
})
test('collection description preserves frozen figure number and displays readable evidence without keys',()=>{
 render(<ReportPreview ready sections={[{key:'figures',title:'带标签图表',content:[{figure_number:4,title:'Author title',caption:'Author caption',presentation}]},{key:'explanations',title:'解释',content:[{sections:[{key:'results',title:'结果',text:'原文',evidence:[{key:'private_reference',label:'有效人数',value:8}]}]}]}]}/>);
 expect(screen.getByText(/4.*Author title/)).toBeTruthy();expect(screen.getByText('有效人数')).toBeTruthy();expect(screen.getByText('8')).toBeTruthy();expect(document.body.textContent).not.toMatch(/private_reference|schema_version|color_scale/)
})
test('collection fails closed on unrecognized presentation metadata',()=>{
 render(<ReportPreview ready sections={[{key:'figures',title:'图表',content:[{figure_number:4,title:'Title',presentation:{...presentation,schema_version:99,secret_path:'C:/private'}}]}]}/>);
 expect(document.body.textContent).not.toContain('C:/private');expect(document.body.textContent).not.toContain('99')
})
test('explanation rejects unknown engines without breaking engine-less historical fixtures',()=>{
 const e={schema_version:5,id:'exp',figure_id:f.id,figure_sha256:f.sha256,analysis_run_id:f.analysis_run_id,language:'zh-CN',verification:{status:'references_checked'},sections:['purpose','data','methods','results','interpretation','paper_text'].map(key=>({key,title:key,text:'Fact'})),limitations:[]}
 expect(isBoundExplanation({...e,engine:{id:'figure_explanation_v99'}},f)).toBe(false)
})
test('axis labels already carrying their frozen unit display that unit once',()=>{
 render(<FigureDescription title="Title" caption="" number={1} presentation={{...presentation,axes:{...presentation.axes,y:{label:'Weight (kg)',unit:'kg'}}}}/>);
 expect(screen.getByText('Weight (kg)')).toBeTruthy();expect(document.body.textContent).not.toContain('(kg) (kg)')
})

test('v3 accepts only presentation v2 and preserves v2 schema binding',()=>{
 const next={...presentation,schema_version:2 as const}
 expect(isPresentation(next)).toBe(true)
 expect(isConfiguredFigure({...f,engine:{id:'openai_figure_workbench_v3'},presentation:next},correlationResult.source,'zh-CN')).toBe(true)
 expect(isConfiguredFigure({...f,presentation:next},correlationResult.source,'zh-CN')).toBe(false)
 expect(isConfiguredFigure({...f,engine:{id:'openai_figure_workbench_v1'},presentation:next},correlationResult.source,'zh-CN')).toBe(false)
})

test.each(['zh-CN','en'] as const)('v3 renders author and statistical caption once in %s',locale=>{
 setLocale(locale)
 render(<FigureDescription title="Title" number={1} caption="Author caption. 仅描述已确认记录" presentation={{...presentation,schema_version:2}}/>);
 expect(document.body.textContent?.match(/仅描述已确认记录/g)).toHaveLength(1)
 expect(document.body.textContent?.match(/Author caption/g)).toHaveLength(1)
 expect(screen.getByText(/SD.*样本标准差/)).toBeTruthy()
})
