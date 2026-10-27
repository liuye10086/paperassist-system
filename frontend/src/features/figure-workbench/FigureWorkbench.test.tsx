import {afterEach,expect,test,vi} from 'vitest'
import {useState} from 'react'
import userEvent from '@testing-library/user-event'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import FigureWorkbench from './FigureWorkbench'
import {correlationResult} from '../analysis/correlationFixtures'
import {setLocale} from '../../shared/i18n'
import {defaultConfig,kindLabels,type FigureKind} from './config'
import ConfigurationEditor from './ConfigurationEditor'
import {taskFixture} from '../tasks/taskFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const props={base:'/api/v1/projects/p1/files/f1',runId:correlationResult.id,source:correlationResult.source,language:'zh-CN' as const,resultType:'correlation',mode:'pair',disabled:false}
const state={configurations:[],available_kinds:['scatter','line','bar','violin'],language:'zh-CN',fields:[{column:'A',name:'Time',unit:'',type:'number'},{column:'B',name:'Weight',unit:'kg',type:'number'}]}
test('saving a draft is local and does not authorize generation',async()=>{
 const fetch=vi.fn(async()=>Response.json(state));vi.stubGlobal('fetch',fetch)
 render(<FigureWorkbench {...props}/>)
 await screen.findByRole('button',{name:'保存配置草稿'})
 expect(screen.queryByRole('button',{name:'确认外发并生成新图'})).toBeNull()
 fireEvent.change(screen.getByLabelText('图型'),{target:{value:'line'}})
 expect(screen.getByText('请选择横轴字段。')).toBeTruthy()
 expect(fetch.mock.calls).toHaveLength(1)
})
test('late reads cannot leak a prior project into a switched workspace',async()=>{
 let finish!:(r:Response)=>void
 const fetch=vi.fn((url:string)=>url.includes('/p1/')?new Promise<Response>(resolve=>{finish=resolve}):Promise.resolve(Response.json({...state,fields:[{column:'C',name:'New project field',unit:'',type:'number'}]})))
 vi.stubGlobal('fetch',fetch)
 const view=render(<FigureWorkbench {...props}/>)
 view.rerender(<FigureWorkbench {...props} base='/api/v1/projects/p2/files/f1'/>)
 await screen.findByRole('button',{name:'保存配置草稿'})
 finish(Response.json({...state,fields:[{column:'Z',name:'Private old field',unit:'',type:'number'}]}))
 await waitFor(()=>expect(document.body.textContent).not.toContain('Private old field'))
 expect(document.body.textContent).toContain('New project field')
})
test('projection approval and paid external approval remain separate requests',async()=>{
 let confirmed=false,queued=false
 const posts:string[]=[]
 const config=defaultConfig('scatter','zh-CN')
 const task={...taskFixture,task_type:'figure_workbench',status:'queued',display_status:'queued',reason_code:null,error_code:null,input_version:{kind:'dataset_analysis',source:props.source,setup_revision:2,output_language:'zh-CN'}}
 const projection={id:'projection1',config_version_id:'v1',sha256:'c'.repeat(64),result:{audit:{}}}
 const entry=()=>({id:'c1',revision:1,version:{id:'v1',configuration_id:'c1',revision:1,config,source:props.source},projection:confirmed?projection:null,figure:null,task:queued?task:null})
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST')posts.push(url.split('/').at(-1)!)
  if(url.endsWith('/check'))return Response.json({version_id:'v1',input_sha256:'a'.repeat(64),requires_confirmation:true,check:{population_n:4,valid_n:4,excluded_n:0,missing_y_n:0,excluded:[],method:{kind:'scatter'}}})
  if(url.endsWith('/confirm')){confirmed=true;expect(JSON.parse(String(init?.body))).toEqual({input_sha256:'a'.repeat(64),approved:true});return Response.json(projection)}
  if(url.endsWith('/external-preview'))return Response.json({payload_sha256:'b'.repeat(64),payload:{labels:{title:'Association'},rows:[[1,2],[2,3]]},requires_confirmation:true})
  if(url.endsWith('/generate')){queued=true;expect(JSON.parse(String(init?.body)).external_processing).toEqual({payload_sha256:'b'.repeat(64),confirmed:true});return Response.json({task})}
  return Response.json({...state,configurations:[entry()]})
 }))
 render(<FigureWorkbench {...props}/>)
 fireEvent.click(await screen.findByRole('button',{name:'检查计算与缺项'}))
 fireEvent.click(await screen.findByRole('button',{name:'独立确认并保存计算'}))
 fireEvent.click(await screen.findByRole('button',{name:'预览新图外发材料'}))
 const generate=await screen.findByRole('button',{name:'确认外发并生成新图'})
 expect((generate as HTMLButtonElement).disabled).toBe(true)
 expect(posts).toEqual(['check','confirm','external-preview'])
 fireEvent.click(screen.getByLabelText('已核对本次材料并同意外发与费用'))
 fireEvent.click(generate)
 await waitFor(()=>expect(posts).toEqual(['check','confirm','external-preview','generate']))
})
test.each(Object.keys(kindLabels) as FigureKind[])('%s configuration controls render in English',kind=>{
 setLocale('en');render(<ConfigurationEditor value={defaultConfig(kind,'en')} onChange={()=>{}} fields={state.fields} kinds={Object.keys(kindLabels) as FigureKind[]} disabled={false}/>)
 expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/)
})
test('users can type a comma-delimited order without losing separators mid-entry',async()=>{
 function Editor(){const [value,setValue]=useState(defaultConfig('boxplot','zh-CN'));return <ConfigurationEditor value={value} onChange={setValue} fields={state.fields} kinds={['boxplot']} disabled={false}/>}
 render(<Editor/>);const input=screen.getByLabelText('显示顺序（逗号分隔）')
 await userEvent.type(input,'Control, Treatment')
 expect((input as HTMLInputElement).value).toBe('Control, Treatment')
})

const failedFigureTask={...taskFixture,task_type:'figure_workbench',status:'failed',display_status:'failed',reason_code:null,error_code:'provider_error',input_version:{kind:'dataset_analysis',source:props.source,setup_revision:2,output_language:'zh-CN'}}
function versionEntry(version='v1',revision=1,confirmed=true){return {id:'c1',revision,version:{id:version,configuration_id:'c1',revision,config:defaultConfig('scatter','zh-CN'),source:props.source},projection:confirmed?{id:`projection-${version}`,config_version_id:version,sha256:'c'.repeat(64),result:{audit:{}}}:null,figure:null,task:null}}
async function approveFigure(){
 fireEvent.click(await screen.findByRole('button',{name:'预览新图外发材料'}))
 fireEvent.click(await screen.findByLabelText('已核对本次材料并同意外发与费用'))
 fireEvent.click(screen.getByRole('button',{name:'确认外发并生成新图'}))
}

test.each(['zh-CN','en'] as const)('a historical explanation stays readable while an explicitly confirmed new explanation can be requested in %s',async locale=>{
 setLocale(locale)
 const figure={schema_version:5,id:'old-figure',analysis_run_id:props.runId,file_id:'f1',setup_revision:2,source:props.source,source_sha256:props.source.source_sha256,sha256:'d'.repeat(64),figure_kind:'scatter',figure_config_version_id:'v1',language:'zh-CN',title:'Historical figure',caption:'Frozen caption',numbering_mode:'external',figure_number:null,verification:{status:'matched'},engine:{id:'openai_figure_workbench_v3'},presentation:{schema_version:2,axes:{x:{label:'X',unit:''},y:{label:'Y',unit:''}},legend:{title:'',entries:[]},color_scale:null,abbreviations:[],statistical_notes:[]}}
 const explanation={schema_version:5,id:'old-explanation',figure_id:figure.id,figure_sha256:figure.sha256,analysis_run_id:props.runId,language:'zh-CN',engine:{id:'figure_explanation_v3'},verification:{status:'references_checked'},sections:['purpose','data','methods','results','interpretation','paper_text'].map(key=>({key,title:key,text:'Preserved old text'})),limitations:[]}
 let task={...failedFigureTask,task_type:'figure_explanation',status:'succeeded',display_status:'succeeded',error_code:null}
 const posts:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST')posts.push(url.split('/').at(-1)!)
  if(url.endsWith('/explanation-preview'))return Response.json({payload_sha256:'b'.repeat(64),payload:{figure_explanation_contract:4},requires_confirmation:true})
  if(url.endsWith('/explanations')){expect(JSON.parse(String(init?.body)).external_processing).toEqual({payload_sha256:'b'.repeat(64),confirmed:true});task={...task,status:'queued',display_status:'queued'};return Response.json({task})}
  return Response.json({...state,configurations:[{...versionEntry(),figure,explanation,explanation_task:task}]})
 }))
 render(<FigureWorkbench {...props}/>);
 const label=locale==='en'?'Preview materials for a new explanation':'预览新版六节解释外发材料'
 fireEvent.click(await screen.findByRole('button',{name:label}))
 const generate=await screen.findByRole('button',{name:locale==='en'?'Confirm external processing and generate explanation':'确认外发并生成六节解释'})
 expect((generate as HTMLButtonElement).disabled).toBe(true);expect(posts).toEqual(['explanation-preview'])
 fireEvent.click(screen.getByLabelText(locale==='en'?'I reviewed these materials and agree to external processing and cost':'已核对本次材料并同意外发与费用'))
 fireEvent.click(generate)
 await waitFor(()=>expect(posts).toEqual(['explanation-preview','explanations']))
 await waitFor(()=>expect((screen.getByRole('button',{name:label}) as HTMLButtonElement).disabled).toBe(true))
 expect(screen.getAllByText('Preserved old text')).toHaveLength(6)
 expect(document.body.textContent).not.toContain('figure_explanation_v4')
})
test('an acknowledged failed task can be submitted again with a fresh key',async()=>{
 const keys:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/external-preview'))return Response.json({payload_sha256:'b'.repeat(64),payload:{title:'Same materials'},requires_confirmation:true})
  if(url.endsWith('/generate')){keys.push(JSON.parse(String(init?.body)).idempotency_key);return Response.json({task:failedFigureTask})}
  return Response.json({...state,configurations:[{...versionEntry(),task:keys.length?failedFigureTask:null}]})
 }))
 render(<FigureWorkbench {...props}/>);await approveFigure()
 await waitFor(()=>expect(screen.queryByRole('button',{name:'确认外发并生成新图'})).toBeNull())
 await approveFigure();await waitFor(()=>expect(keys).toHaveLength(2))
 expect(keys[1]).not.toBe(keys[0])
})
test('an uncertain figure submission retains its key until the outcome is acknowledged',async()=>{
 const keys:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/external-preview'))return Response.json({payload_sha256:'b'.repeat(64),payload:{title:'Same materials'},requires_confirmation:true})
  if(url.endsWith('/generate')){keys.push(JSON.parse(String(init?.body)).idempotency_key);if(keys.length===1)throw new TypeError('offline');return Response.json({task:failedFigureTask})}
  return Response.json({...state,configurations:[versionEntry()]})
 }))
 render(<FigureWorkbench {...props}/>);await approveFigure()
 await screen.findByRole('alert')
 fireEvent.click(screen.getByRole('button',{name:'确认外发并生成新图'}))
 await waitFor(()=>expect(keys).toHaveLength(2));expect(keys[1]).toBe(keys[0])
})
test('a selected historical configuration can be checked, confirmed, generated and explained without substituting latest',async()=>{
 let confirmed=false,generated=false,explained=false
 const posts:string[]=[]
 const figure={schema_version:5,id:'old-figure',analysis_run_id:props.runId,file_id:'f1',setup_revision:2,source:props.source,source_sha256:props.source.source_sha256,sha256:'d'.repeat(64),figure_kind:'scatter',figure_config_version_id:'v1',language:'zh-CN',title:'Historical figure',caption:'Frozen caption',numbering_mode:'external',figure_number:null,verification:{status:'matched'},engine:{id:'openai_figure_workbench_v1'}}
 const explanation={schema_version:5,id:'old-explanation',figure_id:figure.id,figure_sha256:figure.sha256,analysis_run_id:props.runId,language:'zh-CN',verification:{status:'references_checked'},sections:['purpose','data','methods','results','interpretation','paper_text'].map(key=>({key,title:key,text:'Historical explanation'})),limitations:[]}
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST')posts.push(url)
  if(url.endsWith('/check'))return Response.json({version_id:'v1',input_sha256:'a'.repeat(64),requires_confirmation:true,check:{population_n:4,valid_n:4,excluded_n:0,missing_y_n:0,excluded:[],method:{kind:'scatter'}}})
  if(url.endsWith('/confirm')){confirmed=true;return Response.json(versionEntry().projection)}
  if(url.endsWith('/external-preview')||url.endsWith('/explanation-preview'))return Response.json({payload_sha256:'b'.repeat(64),payload:{title:'Historical materials'},requires_confirmation:true})
  if(url.endsWith('/generate')){generated=true;return Response.json({task:failedFigureTask})}
  if(url.endsWith('/explanations')){explained=true;return Response.json({task:{...failedFigureTask,task_type:'figure_explanation'}})}
  const old={...versionEntry('v1',1,confirmed),figure:generated?figure:null,explanation:explained?explanation:null}
  const latest=versionEntry('v2',2)
  return Response.json({...state,configurations:[{...latest,versions:[latest,old]}]})
 }))
 render(<FigureWorkbench {...props}/>)
 fireEvent.change(await screen.findByLabelText('查看配置版本'),{target:{value:'v1'}})
 expect(screen.getByText('当前操作绑定所选历史版本，不会更换报告集合已冻结的引用。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'检查计算与缺项'}))
 fireEvent.click(await screen.findByRole('button',{name:'独立确认并保存计算'}))
 await approveFigure()
 fireEvent.click(await screen.findByRole('button',{name:'预览六节解释外发材料'}))
 fireEvent.click(await screen.findByLabelText('已核对本次材料并同意外发与费用'))
 fireEvent.click(screen.getByRole('button',{name:'确认外发并生成六节解释'}))
 await screen.findByText('查看绑定此图的六节解释')
 expect(posts).toHaveLength(6)
 expect(posts.every(url=>url.includes('/versions/v1/')||url.includes('/figures/old-figure/'))).toBe(true)
 expect((screen.getByLabelText('查看配置版本') as HTMLSelectElement).value).toBe('v1')
})

test('a missing selected configuration never falls back to the latest version on reload',async()=>{
 let missing=false
 const latest=versionEntry('v2',2),old=versionEntry()
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...state,configurations:[{...latest,versions:missing?[latest]:[latest,old]}]})))
 render(<FigureWorkbench {...props}/>);fireEvent.change(await screen.findByLabelText('查看配置版本'),{target:{value:'v1'}})
 missing=true;fireEvent.click(screen.getByRole('button',{name:'重新读取图表版本'}))
 await screen.findByText('所选配置版本当前不可用，请重新读取；不会自动替换为最新版本。')
 expect(screen.queryByRole('button',{name:'预览新图外发材料'})).toBeNull()
})

test('queued local projection survives a refresh and never exposes confirmation before a worker candidate',async()=>{
 let queued=false
 const task={...taskFixture,task_type:'figure_projection',status:'queued',display_status:'queued',reason_code:null,error_code:null,input_version:{kind:'dataset_analysis',source:props.source,setup_revision:2,output_language:'zh-CN'}}
 const fetch=vi.fn(async(url:string)=>{
  if(url.endsWith('/check')){queued=true;return Response.json({version_id:'v1',status:'queued',input_sha256:null,requires_confirmation:false,check:null,diagnostics:[],task})}
  return Response.json({...state,configurations:[{...versionEntry('v1',1,false),projection_task:queued?task:null,projection_check:null}]})
 });vi.stubGlobal('fetch',fetch)
 render(<FigureWorkbench {...props}/>)
 fireEvent.click(await screen.findByRole('button',{name:'检查计算与缺项'}))
 await screen.findByText('本地投影任务：待执行')
 expect(screen.queryByRole('button',{name:'独立确认并保存计算'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'重新读取图表版本'}))
 expect(await screen.findByText('本地投影任务：待执行')).toBeTruthy()
 expect(fetch.mock.calls.filter(([url])=>url.endsWith('/check'))).toHaveLength(1)
})

test('a persisted worker candidate can be independently approved after refresh without paid consent',async()=>{
 let approved=false
 const task={...taskFixture,task_type:'figure_projection',status:'waiting_confirmation',display_status:'waiting_confirmation',reason_code:'confirmation_required',input_version:{kind:'dataset_analysis',source:props.source,setup_revision:2,output_language:'zh-CN'}}
 const check={version_id:'v1',input_sha256:'a'.repeat(64),requires_confirmation:true,status:'waiting_confirmation',task,diagnostics:[],check:{population_n:4,valid_n:4,excluded_n:0,missing_y_n:0,excluded:[],method:{kind:'line'}}}
 const fetch=vi.fn(async(url:string)=>{
  if(url.endsWith('/confirm')){approved=true;return Response.json({task:{...task,status:'queued',display_status:'queued',reason_code:'confirmation_received',revision:task.revision!+1}})}
  return Response.json({...state,configurations:[{...versionEntry('v1',1,false),projection_task:approved?{...task,status:'queued',display_status:'queued',reason_code:'confirmation_received'}:task,projection_check:check}]})
 });vi.stubGlobal('fetch',fetch)
 render(<FigureWorkbench {...props}/>)
 fireEvent.click(await screen.findByRole('button',{name:'独立确认并保存计算'}))
 await screen.findByText('本地投影任务：待执行')
 expect(screen.queryByRole('button',{name:'预览新图外发材料'})).toBeNull()
 expect(fetch.mock.calls.filter(([url])=>url.endsWith('/confirm'))).toHaveLength(1)
 expect(fetch.mock.calls.some(([url])=>url.endsWith('/generate'))).toBe(false)
})

test('task views keep an unsaved figure draft while moving between list and explanation without creating work',async()=>{
 const fetcher=vi.fn(async()=>Response.json({...state,configurations:[versionEntry()]}));vi.stubGlobal('fetch',fetcher)
 const view=render(<FigureWorkbench {...props} view="figure"/>)
 fireEvent.click(await screen.findByRole('button',{name:'新建独立图表'}))
 fireEvent.change(screen.getByLabelText('图标题'),{target:{value:'Unsaved local title'}})
 fireEvent.click(screen.getByRole('button',{name:'返回图表列表'}))
 expect(screen.queryByRole('textbox',{name:'图标题'})).toBeNull()
 view.rerender(<FigureWorkbench {...props} view="explanation"/>)
 expect(await screen.findByRole('button',{name:'打开图表 散点图'})).toBeTruthy()
 expect(screen.queryByRole('button',{name:'新建独立图表'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'打开图表 散点图'}))
 expect(screen.getByText('请先在图表任务中生成所选版本的图表。')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'检查计算与缺项'})).toBeNull()
 view.rerender(<FigureWorkbench {...props} view="figure"/>)
 fireEvent.click(screen.getByRole('button',{name:'继续编辑图表草稿'}))
 expect((screen.getByLabelText('图标题') as HTMLInputElement).value).toBe('Unsaved local title')
 expect(fetcher.mock.calls).toHaveLength(1)
})

test('task detail keeps the chosen configuration version after a newer configuration arrives',async()=>{
 let updated=false
 const old=versionEntry(),latest=versionEntry('v2',2)
 const fetcher=vi.fn(async()=>Response.json({...state,configurations:[updated?{...latest,versions:[latest,old]}:old]}));vi.stubGlobal('fetch',fetcher)
 render(<FigureWorkbench {...props} view="figure"/>)
 fireEvent.click(await screen.findByRole('button',{name:'打开图表 散点图'}))
 updated=true;fireEvent.click(screen.getByRole('button',{name:'重新读取图表版本'}))
 await screen.findByText('当前操作绑定所选历史版本，不会更换报告集合已冻结的引用。')
 expect((screen.getByLabelText('查看配置版本') as HTMLSelectElement).value).toBe('v1')
 fireEvent.click(screen.getByRole('button',{name:'返回图表列表'}))
 fireEvent.click(screen.getByRole('button',{name:'打开图表 散点图'}))
 expect((screen.getByLabelText('查看配置版本') as HTMLSelectElement).value).toBe('v1')
})

test('draft guard cancels replacement of an unsaved figure configuration',async()=>{
 const guardSet=new Set<()=>boolean>()
 const register=(guard:()=>boolean)=>{guardSet.add(guard);return()=>guardSet.delete(guard)}
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...state,configurations:[versionEntry()]})))
 render(<FigureWorkbench {...props} view="figure" registerLeaveGuard={register}/>)
 fireEvent.click(await screen.findByRole('button',{name:'新建独立图表'}))
 fireEvent.change(screen.getByLabelText('图标题'),{target:{value:'Unpublished draft'}})
 expect([...guardSet][0]()).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'新建独立图表'}))
 expect((screen.getByLabelText('图标题') as HTMLInputElement).value).toBe('Unpublished draft')
 confirm.mockRestore()
})

test('reopening the same figure editor resumes its unsaved configuration instead of replacing it',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...state,configurations:[versionEntry()]})))
 render(<FigureWorkbench {...props} view="figure"/>)
 fireEvent.click(await screen.findByRole('button',{name:'打开图表 散点图'}))
 fireEvent.click(screen.getByRole('button',{name:'编辑为新配置版本'}))
 fireEvent.change(screen.getByLabelText('图标题'),{target:{value:'Keep my figure title'}})
 fireEvent.click(screen.getByRole('button',{name:'返回图表列表'}))
 fireEvent.click(screen.getByRole('button',{name:'打开图表 散点图'}))
 fireEvent.click(screen.getByRole('button',{name:'编辑为新配置版本'}))
 expect((screen.getByLabelText('图标题') as HTMLInputElement).value).toBe('Keep my figure title')
})

test('an uncertain figure request allows explicitly confirmed navigation and keeps its retry identity',async()=>{
 let guard=()=>true
 const register=(next:()=>boolean)=>{guard=next;return()=>{}}
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(true),alert=vi.spyOn(window,'alert').mockImplementation(()=>{})
 const keys:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/external-preview'))return Response.json({payload_sha256:'b'.repeat(64),payload:{title:'Same materials'},requires_confirmation:true})
  if(url.endsWith('/generate')){keys.push(JSON.parse(String(init?.body)).idempotency_key);throw new TypeError('offline')}
  return Response.json({...state,configurations:[versionEntry()]})
 }))
 render(<FigureWorkbench {...props} registerLeaveGuard={register}/>);await approveFigure();await screen.findByRole('alert')
 expect(guard()).toBe(true);expect(confirm).toHaveBeenCalledTimes(1);expect(alert).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'确认外发并生成新图'}))
 await waitFor(()=>expect(keys).toHaveLength(2));expect(keys[1]).toBe(keys[0])
 confirm.mockRestore();alert.mockRestore()
})
