import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPlanLauncher from './AnalysisPlanLauncher'
import { reviewFixture } from './analysisPlanFixtures'
import type { PreparedDatasetAnalysisSource } from '../analysis/datasetSource'
import type { Selection } from '../analysis/AnalysisSetup'
import { research } from './batch02Fixtures'
import { RecommendationResult } from './AnalysisRecommendation'
import AnalysisRecommendation from './AnalysisRecommendation'
import { waitFor } from '@testing-library/react'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
test('manual correlation is a v3 local candidate and never sends a model call',async()=>{
 const fetch=vi.fn(async(url:string)=>Response.json(url.includes('analysis-plans?')?{items:[],total:0,page:1,page_size:5}:null));vi.stubGlobal('fetch',fetch)
 render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={reviewFixture.source as PreparedDatasetAnalysisSource} selection={reviewFixture.selection as Selection} setupRevision={0} disabled={false} onPublished={()=>{}} />)
 await userEvent.selectOptions(screen.getByLabelText('计划方法'),'pearson')
 expect(screen.getByLabelText('相关路径')).toBeTruthy()
 expect(fetch.mock.calls.some(([url])=>url.includes('analysis-recommendations'))).toBe(false)
})
test('an ambiguous recommendation submission only replays the exact confirmed body and key',async()=>{
 const preview={version:3,provider:'openai',source:reviewFixture.source,source_digest:'digest',fields:[{column:'C',name:'weight',type:'number',unit:{status:'confirmed',value:'kg'},missing_count:0,non_missing_count:4}],labels:[{key:'field:C',value:'weight'},{key:'research_summary',value:''}],allowed_methods:['descriptive','pearson','spearman','welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis','ols','logistic','roc_auc','kaplan_meier'],allowed_modes:['pair','matrix','independent','paired','multiple','regression','roc','survival'],output_language:'zh-CN',research_summary:''}
 const input={...reviewFixture.input_version,kind:'analysis_recommendation',workflow_version:'analysis_recommendation_v1'}
 input.workflow_version='analysis_recommendation_v3'
 let submissions=0
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{if(url.endsWith('/preview'))return Response.json(preview);if(init?.method==='POST'){if(++submissions===1)throw new TypeError('offline');return Response.json({...reviewFixture.task,task_type:'analysis_recommendation',status:'queued',display_status:'queued',input_version:input})}return Response.json({})});vi.stubGlobal('fetch',fetch)
 render(<AnalysisRecommendation projectId="p1" fileId="f1" source={reviewFixture.source as PreparedDatasetAnalysisSource} descriptiveSelection={reviewFixture.selection as Selection} fields={[{column:'C',name:'weight',numeric:true,unit:'kg'}]} language="zh-CN" disabled={false} onAdopt={()=>{}}/>)
 const user=userEvent.setup();await user.click(screen.getByLabelText('候选字段 C · weight'));await user.click(screen.getByRole('button',{name:'预览受限模型建议资料'}));await user.click(await screen.findByRole('button',{name:'确认外发并获取建议'}))
 await user.click(await screen.findByRole('button',{name:'确认上次建议提交'}));await waitFor(()=>expect(submissions).toBe(2))
 const posts=fetch.mock.calls.filter(([url])=>url.endsWith('/analysis-recommendations'))
 expect(posts[0][1]?.body).toBe(posts[1][1]?.body)
 expect(posts[0][1]?.headers).toEqual(posts[1][1]?.headers)
})
test('a known unknown provider submission blocks a second recommendation preview',async()=>{
 const preview={version:3,provider:'openai',source:reviewFixture.source,source_digest:'digest',fields:[{column:'C',name:'weight',type:'number',unit:{status:'confirmed',value:''},missing_count:0,non_missing_count:4}],labels:[{key:'field:C',value:'weight'},{key:'research_summary',value:''}],allowed_methods:['descriptive','pearson','spearman','welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis','ols','logistic','roc_auc','kaplan_meier'],allowed_modes:['pair','matrix','independent','paired','multiple','regression','roc','survival'],output_language:'zh-CN',research_summary:''}
 const task={...reviewFixture.task,task_type:'analysis_recommendation',reason_code:'submission_unknown',input_version:{...reviewFixture.input_version,kind:'analysis_recommendation',workflow_version:'analysis_recommendation_v3'}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/preview')?preview:url.endsWith('/analysis-recommendations')?task:{})))
 render(<AnalysisRecommendation projectId="p1" fileId="f1" source={reviewFixture.source as PreparedDatasetAnalysisSource} descriptiveSelection={reviewFixture.selection as Selection} fields={[{column:'C',name:'weight'}]} language="zh-CN" disabled={false} onAdopt={()=>{}}/>)
 const user=userEvent.setup();await user.click(screen.getByLabelText('候选字段 C · weight'));await user.click(screen.getByRole('button',{name:'预览受限模型建议资料'}));await user.click(await screen.findByRole('button',{name:'确认外发并获取建议'}))
 await waitFor(()=>expect(screen.queryByRole('button',{name:'确认外发并获取建议'})).toBeNull())
 expect((screen.getByRole('button',{name:'预览受限模型建议资料'}) as HTMLButtonElement).disabled).toBe(true)
})
test('provides a read-only saved recommendation list after refreshing the workbench',async()=>{
 const input={...reviewFixture.input_version,kind:'analysis_recommendation',workflow_version:'analysis_recommendation_v1'}
 const task={...reviewFixture.task,task_type:'analysis_recommendation',input_version:input}
 const fetch=vi.fn(async(url:string)=>Response.json(url.includes('/tasks?')?{project_id:'p1',items:[{task,source:{file_id:'f1',filename:'synthetic.xlsx',analysis_run_id:null,is_current:true,dataset_source:reviewFixture.source}}],total:1,page:1,page_size:10}:{items:[],total:0,page:1,page_size:5}));vi.stubGlobal('fetch',fetch)
 render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={reviewFixture.source as PreparedDatasetAnalysisSource} selection={reviewFixture.selection as Selection} setupRevision={0} disabled={false} onPublished={()=>{}}/>)
 await userEvent.click(screen.getByRole('button',{name:'读取已保存建议'}))
 expect(await screen.findByRole('button',{name:/建议 1/})).toBeTruthy()
})
test('restores a frozen recommendation through its workspace and retains a separate adoption action',async()=>{
 const input={...reviewFixture.input_version,kind:'analysis_recommendation',workflow_version:'analysis_recommendation_v1'}
 const task={...reviewFixture.task,task_type:'analysis_recommendation',status:'succeeded',display_status:'succeeded',input_version:input}
 const result={task,source:reviewFixture.source,input_version:input,request:{dataset_id:reviewFixture.source.dataset_id,sheet_name:'Sheet1',candidate_columns:['C','D'],output_language:'en',research_summary:'safe'},external_processing:{version:1,provider:'openai',task_type:'analysis_recommendation',source_digest:'digest',labels:{'field:C':'weight','field:D':'height',research_summary:'safe'},confirmed_by:'user',confirmed_at:task.created_at,confirmation_digest:'d'.repeat(64)},recommendation:{schema_version:1,task_id:'t1',sha256:'c'.repeat(64),method:'pearson',mode:'pair',columns:['C','D'],output_language:'en',rationale:['Synthetic rationale'],assumptions:['Check independence'],missing_information:[],model_call_id:'call1'}}
 const workspace={task,source:{file_id:'f1',filename:'synthetic.xlsx',analysis_run_id:null,is_current:true,dataset_source:reviewFixture.source},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?workspace:url.endsWith('/analysis-recommendation')?result:task)))
 const adopted=vi.fn();render(<RecommendationResult projectId="p1" taskId="t1" onAdopt={adopted}/>)
 await userEvent.click(await screen.findByRole('button',{name:'采纳为候选计划，仍需独立确认'}))
 expect(adopted).toHaveBeenCalledTimes(1)
 expect(screen.getByText('Synthetic rationale')).toBeTruthy()
 expect(document.body.textContent).not.toContain('call1')
})
test('previews selected field descriptions and edited summary before any model task',async()=>{
 const preview={version:5,source_mapping:[{code:'F1',level:'file',name:'synthetic.xlsx'},{code:'S1',level:'sheet',name:reviewFixture.source.sheet_name},{code:'D1',level:'dataset',name:'v1'}],provider:'openai',source:reviewFixture.source,source_digest:'digest',fields:[{column:'C',name:'weight',type:'number',unit:{status:'confirmed',value:'kg'},missing_count:0,non_missing_count:4}],labels:[{key:'field:C',value:'weight'},{key:'research_summary',value:'Safe summary'}],allowed_methods:['descriptive','pearson','spearman','welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis','ols','logistic','roc_auc','kaplan_meier'],allowed_modes:['pair','matrix','independent','paired','multiple','regression','roc','survival'],output_language:'zh-CN',research_summary:'Safe summary'}
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/preview')?preview:{items:[],total:0,page:1,page_size:5}));vi.stubGlobal('fetch',fetch)
 render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={reviewFixture.source as PreparedDatasetAnalysisSource} selection={reviewFixture.selection as Selection} fields={[{column:'C',name:'weight',numeric:true}]} setupRevision={0} disabled={false} onPublished={()=>{}} />)
 const user=userEvent.setup();await user.type(screen.getByLabelText('研究问题'),research.question)
 await user.type(screen.getByLabelText('本次外发研究摘要'),'Safe summary')
 await user.click(screen.getByLabelText('候选字段 C · weight'))
 await user.click(screen.getByRole('button',{name:'预览受限模型建议资料'}))
 expect(await screen.findByRole('button',{name:'确认外发并获取建议'})).toBeTruthy()
 const call=fetch.mock.calls.find(([u])=>u.endsWith('/preview'))!;expect(JSON.parse(String(call[1]?.body))).toMatchObject({candidate_columns:['C'],research_summary:'Safe summary'})
 expect(String(call[1]?.body)).not.toContain(research.question)
 await user.click(screen.getByRole('button',{name:'取消外发'}))
 expect(fetch.mock.calls.filter(([u])=>u.endsWith('/analysis-recommendations'))).toHaveLength(0)
})
