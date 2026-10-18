import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {isRecommendationPreview,isRecommendationReview} from './recommendationApi'
import {reviewFixture} from './analysisPlanFixtures'
import AnalysisPlanLauncher from './AnalysisPlanLauncher'
import {groupOptions} from '../analysis/comparisonFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const input={...reviewFixture.input_version,kind:'analysis_recommendation',workflow_version:'analysis_recommendation_v2'}
const task={...reviewFixture.task,task_type:'analysis_recommendation',status:'succeeded',display_status:'succeeded',input_version:input}
const request={schema_version:2,dataset_id:reviewFixture.source.dataset_id,sheet_name:reviewFixture.source.sheet_name,candidate_columns:['C','D'],output_language:'en',research_summary:'Approved only'}
const recommendation={schema_version:2,task_id:task.id,sha256:'c'.repeat(64),method:'welch_t',mode:'independent',columns:['C','D'],roles:{numeric_column:'C',group_column:'D',pair_id_column:null,before_column:null,after_column:null},output_language:'en',rationale:['Prespecified independent comparison'],assumptions:['Check group independence and normal outcomes'],missing_information:[],model_call_id:'private-call'}
const review={task,source:reviewFixture.source,input_version:input,request,external_processing:{version:1,provider:'openai',task_type:'analysis_recommendation',source_digest:'digest',labels:{'field:C':'Outcome','field:D':'Group',research_summary:'Approved only'},confirmed_by:'user',confirmed_at:task.created_at,confirmation_digest:'d'.repeat(64)},recommendation}
test('v2 recommendations enforce white-listed methods, role coherence and nonempty rationale/assumptions',()=>{
 expect(isRecommendationReview(review,'p1','t1')).toBe(true)
 for(const r of [{...recommendation,method:'regression'},{...recommendation,rationale:[]},{...recommendation,assumptions:[' ']},{...recommendation,roles:{...recommendation.roles,pair_id_column:'C'}},{...recommendation,mode:'paired'},{...recommendation,columns:['C','F']}])expect(isRecommendationReview({...review,recommendation:r},'p1','t1')).toBe(false)
 const preview={version:2,provider:'openai',source:reviewFixture.source,source_digest:'digest',fields:['C','D'].map(c=>({column:c,name:c,type:'number',unit:{status:'confirmed',value:'kg'},missing_count:0,non_missing_count:3})),labels:[{key:'field:C',value:'Outcome'},{key:'field:D',value:'Group'},{key:'research_summary',value:'Approved only'}],allowed_methods:['descriptive','pearson','spearman','welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis'],allowed_modes:['pair','matrix','independent','paired','multiple'],output_language:'en',research_summary:'Approved only'}
 expect(isRecommendationPreview(preview,reviewFixture.source as never,request as never)).toBe(true)
 expect(isRecommendationPreview({...preview,allowed_methods:[...preview.allowed_methods,'dunn']},reviewFixture.source as never,request as never)).toBe(false)
 expect(isRecommendationPreview({...preview,raw_ids:['private']},reviewFixture.source as never,request as never)).toBe(false)
 expect(isRecommendationPreview({...preview,fields:preview.fields.map(f=>({...f,values:[1,2,3]}))},reviewFixture.source as never,request as never)).toBe(false)
})
test('adopting comparison recommendation maps local roles but requires group choice and a separate plan action',async()=>{
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.includes('/analysis-plans?')?{items:[],total:0,page:1,page_size:5}:url.includes('/tasks?')?{project_id:'p1',items:[{task,source:{file_id:'f1',filename:'synthetic.xlsx',analysis_run_id:null,is_current:true,dataset_source:reviewFixture.source}}],total:1,page:1,page_size:10}:url.endsWith('/workspace')?{task,source:{file_id:'f1',filename:'synthetic.xlsx',analysis_run_id:null,is_current:true,dataset_source:reviewFixture.source},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}:url.endsWith('/analysis-recommendation')?review:url.includes('comparison-group-options')?groupOptions:init?.method==='POST'?task:null));vi.stubGlobal('fetch',fetch)
 render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={reviewFixture.source as never} selection={reviewFixture.selection as never} fields={[{column:'C',name:'Outcome',unit:'kg'},{column:'D',name:'Group'}]} setupRevision={2} disabled={false} onPublished={()=>{}}/>)
 const user=userEvent.setup();await user.click(screen.getByRole('button',{name:'读取已保存建议'}));await user.click(await screen.findByRole('button',{name:/建议 1/}));await user.click(await screen.findByRole('button',{name:'采纳为候选计划，仍需独立确认'}))
 await waitFor(()=>expect((screen.getByLabelText('计划方法') as HTMLSelectElement).value).toBe('welch_t'))
 expect((screen.getByLabelText('结局数值列') as HTMLSelectElement).value).toBe('C')
 expect((screen.getByRole('button',{name:'生成分析计划'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByLabelText('我已核对研究设计与所选比较方法的前提') as HTMLInputElement).checked).toBe(false)
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
 expect(document.body.textContent).not.toContain('private-call')
})
