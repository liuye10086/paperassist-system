import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {setLocale,translate} from '../../shared/i18n'
import AnalysisExplanation from './AnalysisExplanation'

afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it.each(['zh-CN','en'] as const)('requires fresh outbound confirmation for a disabled bound configuration in %s',async locale=>{
 setLocale(locale)
 const task={id:'old-false-task',status:'failed',revision:3,reason_code:'execution_failed',error_code:'model_configuration_disabled'}
 const state={current_revision:1,is_current:true,figure_id:'figure',explanation:null,job:null,task}
 const disclosure={version:1,provider:'openai',task_type:'explanation',source_digest:'source',has_saved_result:false,
  summary:{valid_count:3,excluded_count:0,group_count:1},labels:[{key:'numeric_name',value:'Synthetic value'},{key:'unit',value:''},{key:'figure_title',value:'Synthetic figure'}]}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/disclosure')?disclosure:
  url==='/api/v1/ai/explanation-config'?{configured:true,model:'configured-model'}:
  init?.method==='POST'?{...state,task:{...task,id:'new-true-task',revision:1,status:'queued',error_code:null}}:state))
 vi.stubGlobal('fetch',fetch)
 render(<AnalysisExplanation base="/file" runId="run" revision={1} figureId="figure" canGenerate disabled={false} onBusyChange={()=>{}}/>)
 const retry=await screen.findByRole('button',{name:translate('重试生成解释（再次调用 API）')})
 await waitFor(()=>expect((retry as HTMLButtonElement).disabled).toBe(false))
 expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
 expect(screen.queryByRole('button',{name:translate('继续解释任务')})).toBeNull()
 fireEvent.click(retry)
 const confirm=await screen.findByRole('button',{name:translate('确认发送并生成')})
 expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
 fireEvent.click(confirm)
 await waitFor(()=>expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1))
 const post=fetch.mock.calls.find(([,init])=>init?.method==='POST')!
 expect(post[0]).toBe('/file/analysis-runs/run/explanation')
 expect(JSON.parse(String(post[1]?.body))).toMatchObject({retry:true,expected_predecessor_id:'old-false-task',expected_predecessor_revision:3,external_processing:{confirmed:true}})
 expect(new Headers(post[1]?.headers).get('Idempotency-Key')).toBeTruthy()
 expect(task.status).toBe('failed');expect(task.revision).toBe(3)
})
