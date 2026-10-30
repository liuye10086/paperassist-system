import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {isConfiguredFigure,isBoundExplanation} from './contracts'
import {isPresentation} from './presentation'
import FigureDescription from './FigureDescription'
import FigureWorkbench from './FigureWorkbench'
import {defaultConfig} from './config'
import {correlationResult} from '../analysis/correlationFixtures'
import {taskFixture} from '../tasks/taskFixtures'
import {setLocale} from '../../shared/i18n'

afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const source=correlationResult.source
const presentation={schema_version:3,axes:{x:{label:'Time',unit:''},y:{label:'Weight (kg)',unit:'kg'}},legend:{title:'',entries:[]},color_scale:null,abbreviations:[],statistical_notes:['Frozen statistical note.']}
const figure={schema_version:5,id:'figure-b07',analysis_run_id:correlationResult.id,file_id:'f1',setup_revision:2,source,source_sha256:source.source_sha256,sha256:'d'.repeat(64),figure_kind:'scatter',figure_config_version_id:'v1',language:'zh-CN' as const,title:'Frozen figure',caption:'Author caption. Frozen statistical note.',numbering_mode:'external',figure_number:null,verification:{status:'matched'},engine:{id:'openai_figure_workbench_v4'},presentation}
const explanation={schema_version:5,id:'explanation-b07',figure_id:figure.id,figure_sha256:figure.sha256,analysis_run_id:figure.analysis_run_id,language:'zh-CN',engine:{id:'figure_explanation_v5'},verification:{status:'references_checked'},sections:['purpose','data','methods','results','interpretation','paper_text'].map(key=>({key,title:key,text:'Preserved explanation',evidence:[{key:'data.valid',label:'Valid records',value:4}]})),limitations:[]}

test('B07 presentation accepts schema 3 while rejecting unknown and malformed metadata',()=>{
 expect(isPresentation(presentation)).toBe(true)
 for(const changed of [{schema_version:4},{schema_version:'3'},{axes:{...presentation.axes,y:{label:'Y',unit:1}}},{secret_path:'C:/private'}])expect(isPresentation({...presentation,...changed})).toBe(false)
})

test.each([1,2,3,4])('renderer v%i preserves its exact historical or B07 presentation pairing',renderer=>{
 for(const schema of [undefined,1,2,3,4]){
  const value={...figure,engine:{id:`openai_figure_workbench_v${renderer}`},presentation:schema===undefined?undefined:{...presentation,schema_version:schema}}
  const valid=renderer===1?(schema===undefined||schema===1):schema===renderer-1
  expect(isConfiguredFigure(value,source,'zh-CN',figure.analysis_run_id,'v1'),`renderer ${renderer}, presentation ${schema}`).toBe(valid)
 }
 expect(isConfiguredFigure({...figure,engine:{id:'openai_figure_workbench_v99'}},source,'zh-CN')).toBe(false)
})

test.each([undefined,1,2,3,4,5])('bound explanation engine %s keeps strict image hash, language and run binding',engine=>{
 const value={...explanation,engine:engine===undefined?undefined:{id:`figure_explanation_v${engine}`}}
 expect(isBoundExplanation(value,figure)).toBe(true)
 for(const changed of [{figure_sha256:'e'.repeat(64)},{figure_id:'other'},{analysis_run_id:'other'},{language:'en'},{schema_version:6},{engine:{id:'figure_explanation_v6'}},{sections:explanation.sections.slice(1)}])expect(isBoundExplanation({...value,...changed},figure)).toBe(false)
})

test.each(['zh-CN','en'] as const)('B07 full caption renders statistical notes and units once in %s',locale=>{
 setLocale(locale)
 // Narrow through the real guard, as the workspace and collection preview do.
 if(!isPresentation(presentation))throw new Error('B07 presentation must be readable')
 render(<FigureDescription title={figure.title} caption={figure.caption} presentation={presentation} number={7}/>)
 expect(document.body.textContent?.match(/Frozen statistical note\./g)).toHaveLength(1)
 expect(screen.getByText('Weight (kg)')).toBeTruthy()
 expect(document.body.textContent).not.toContain('(kg) (kg)')
 expect(document.body.textContent).not.toMatch(/schema_version|statistical_notes/)
})

test.each([3,4])('v3 figure with historical explanation v%i upgrades only after explicit external approval',async engine=>{
 const historicalFigure={...figure,engine:{id:'openai_figure_workbench_v3'},presentation:{...presentation,schema_version:2}}
 const historicalExplanation={...explanation,engine:{id:`figure_explanation_v${engine}`}}
 const frozen=JSON.stringify({historicalFigure,historicalExplanation})
 let queued=false
 const posts:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST')posts.push(url)
  if(url.endsWith('/explanation-preview'))return Response.json({payload_sha256:'b'.repeat(64),payload:{figure_explanation_contract:5},requires_confirmation:true})
  if(url.endsWith('/explanations')){expect(JSON.parse(String(init?.body)).external_processing).toEqual({payload_sha256:'b'.repeat(64),confirmed:true});queued=true;return Response.json({task:taskFixture})}
  return Response.json({language:'zh-CN',available_kinds:['scatter'],fields:[],configurations:[{id:'c1',revision:1,version:{id:'v1',configuration_id:'c1',revision:1,config:defaultConfig('scatter','zh-CN'),source},projection:null,task:null,figure:historicalFigure,explanation:historicalExplanation,explanation_task:queued?{...taskFixture,task_type:'figure_explanation',status:'queued',display_status:'queued',input_version:{kind:'dataset_analysis',source,setup_revision:2,output_language:'zh-CN'}}:null}]})
 }))
 render(<FigureWorkbench base="/api/v1/projects/p1/files/f1" runId={figure.analysis_run_id} source={source} language="zh-CN" resultType="correlation" mode="pair" disabled={false}/>)
 fireEvent.click(await screen.findByRole('button',{name:'预览新版六节解释外发材料'}))
 const generate=await screen.findByRole('button',{name:'确认外发并生成六节解释'})
 expect((generate as HTMLButtonElement).disabled).toBe(true)
 expect(posts).toHaveLength(1)
 fireEvent.click(screen.getByLabelText('已核对本次材料并同意外发与费用'))
 fireEvent.click(generate)
 await waitFor(()=>expect(posts).toHaveLength(2))
 expect(posts.every(url=>url.includes(`/figures/${figure.id}/`))).toBe(true)
 await waitFor(()=>expect((screen.getByRole('button',{name:'预览新版六节解释外发材料'}) as HTMLButtonElement).disabled).toBe(true))
 expect(screen.getAllByText('Preserved explanation')).toHaveLength(6)
 expect(JSON.stringify({historicalFigure,historicalExplanation})).toBe(frozen)
})

test.each([3,4])('v%i figure already carrying v5 does not offer another upgrade',async renderer=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({language:'zh-CN',available_kinds:['scatter'],fields:[],configurations:[{id:'c1',revision:1,version:{id:'v1',configuration_id:'c1',revision:1,config:defaultConfig('scatter','zh-CN'),source},projection:null,task:null,figure:{...figure,engine:{id:`openai_figure_workbench_v${renderer}`},presentation:{...presentation,schema_version:renderer-1}},explanation}]})))
 render(<FigureWorkbench base="/api/v1/projects/p1/files/f1" runId={figure.analysis_run_id} source={source} language="zh-CN" disabled={false}/>)
 await screen.findByText('查看绑定此图的六节解释')
 expect(screen.queryByRole('button',{name:'预览新版六节解释外发材料'})).toBeNull()
 expect(screen.getAllByText('Preserved explanation')).toHaveLength(6)
})
