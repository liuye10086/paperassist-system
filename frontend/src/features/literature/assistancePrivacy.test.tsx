import {afterEach,it,expect,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {setLocale} from '../../shared/i18n'
import LiteratureAssistance from './LiteratureAssistance'
import {literatureTask} from './fixtures'
// Synthetic saved suggestion only: no model call or real publication.
const digest='b'.repeat(64)
const task={...literatureTask,id:'assist1',task_type:'literature_assistance',phase:'plan',status:'succeeded',display_status:'succeeded',reason_code:null,error_code:null,input_version:{kind:'literature_assistance',workflow_version:'literature_assistance_v1',assistance_kind:'search_plan',input_digest:digest,output_language:'en'}}
const detail={task,kind:'search_plan',input_version:task.input_version,result:{direction:'Synthetic saved direction',terms:['Synthetic term'],synonyms:[],mesh_candidates:[],query:'synthetic[Title]',explanation:'Synthetic saved explanation'},real_calls_enabled:false}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it.each(['zh-CN','en'] as const)('shows saved suggestions with readable revision scope and no internal digest in %s',async locale=>{
 setLocale(locale);vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/tasks?')?{project_id:'p1',items:[detail],total:1,page:1,page_size:10}:detail)))
 render(<LiteratureAssistance projectId="p1" researchTopic="Synthetic topic" referenceId="" selection={null} onDenied={vi.fn()}/>)
 fireEvent.click(await screen.findByRole('button',{name:locale==='en'?'View suggestion and wait status':'查看建议与等待状态'}))
 expect(await screen.findByText('Synthetic saved direction')).toBeTruthy()
 expect(document.body.textContent).not.toContain(digest.slice(0,12))
 expect(document.body.textContent).not.toContain(digest)
 expect(screen.getByText('Suggestions are bound to the materials and claim revision at submission; historical records are retained.')).toBeTruthy()
 expect(screen.getByText('Synthetic saved explanation')).toBeTruthy()
})
