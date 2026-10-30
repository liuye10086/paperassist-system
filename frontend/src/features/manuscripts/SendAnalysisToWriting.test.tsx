import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import SendAnalysisToWriting from './SendAnalysisToWriting'
import ProjectManuscripts from './ProjectManuscripts'
import {AnalysisWritingProvider} from './AnalysisWritingContext'
import {candidatesFixture} from './manuscriptFixtures'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it.each(['sci','thesis'] as const)('sends explicitly selected historical A to %s via server-verified packet without latest/model/save request',async projectType=>{
 const source={kind:'analysis_run',id:'runA',file_id:'file1',role:'computed_results',label:'Historical A',sha256:'a'.repeat(64),download_url:null,content:{id:'runA',setup_revision:1}}
 const packet={project_id:'p1',project_type:projectType,file_id:'file1',analysis_run_id:'runA',setup_revision:1,report_status:'not_selected',sources:[source],results_group:{id:'analysis-runA',title:'Historical A',analysis_run_ids:['runA'],figure_ids:[]},figure_notes:[]}
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.includes('/analysis-options')?{figures:[],reports:[]}:url.endsWith('/analysis-selection')?packet:url.endsWith('/candidates')?{...candidatesFixture,project_type:projectType,...(projectType==='thesis'?{thesis:{ready:false,template_source_file_ids:[],profile:null,confirmation_id:null,chapters:[],reasons:[]}}:{})}:{items:[]}));vi.stubGlobal('fetch',fetcher)
 const open=vi.fn()
 render(<AnalysisWritingProvider projectId="p1" projectType={projectType} onOpenWriting={open}><SendAnalysisToWriting fileId="file1" runId="runA"/><ProjectManuscripts projectType={projectType} projectId="p1" researchTopic="Original" outputLanguage="en" active/></AnalysisWritingProvider>)
 fireEvent.click(screen.getByRole('button',{name:'选择写作资料'}))
 fireEvent.click(await screen.findByRole('button',{name:projectType==='sci'?'送入SCI写作':'送入毕业论文写作'}))
 await waitFor(()=>expect(open).toHaveBeenCalledTimes(1))
 expect(await screen.findByText(/已合并固定分析资料/)).toBeTruthy()
 const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST')
 expect(posts).toHaveLength(1);expect(posts[0][0]).toMatch(/analysis-selection$/)
 expect(JSON.parse(String(posts[0][1]?.body))).toEqual({file_id:'file1',analysis_run_id:'runA'})
 expect(fetcher.mock.calls.some(([u])=>u.includes('latest')||u.includes('authorizations')||u.includes('writing-requests'))).toBe(false)
})
