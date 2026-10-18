import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import AnalysisPlanLauncher from './AnalysisPlanLauncher'
import filter from '../datasetPreparation/batch09BackendFixture.json'
import rec from './batch09RecommendationFixture.json'
import confirmed from './batch09ConfirmedFixture.json'
import type {PreparedDatasetAnalysisSource} from '../analysis/datasetSource'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('retains an explicitly selected upstream suggestion as provenance and creates an independent v5 plan with no active recommendation',async()=>{
 const source=filter.published.source as PreparedDatasetAnalysisSource,base=filter.published.base_source,project='p1'
 const old={...rec,task:{...rec.task,id:'old-rec',project_id:project,input_version:{...rec.input_version,source:base}},source:base,input_version:{...rec.input_version,source:base},request:{...rec.request,dataset_id:base.dataset_id,sheet_name:base.sheet_name},recommendation:{...rec.recommendation,task_id:'old-rec'}}
 const task={...confirmed.task,id:'new-plan',project_id:project,status:'queued',display_status:'queued',input_version:{kind:'analysis_plan',workflow_version:'analysis_plan_v5',source}}
 const selection={task_type:'descriptive_boxplot' as const,sheet_name:source.sheet_name,numeric_column:'A',group_column:null,unit:'',missing_policy:'exclude_selected_missing' as const}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.includes('/analysis-plans?'))return Response.json({items:[],total:0,page:1,page_size:5})
  if(url.includes('/prepared-dataset-versions/'))return Response.json(filter.published)
  if(url.includes('/tasks?'))return Response.json({project_id:project,items:[{task:old.task,source:{file_id:source.file_id,filename:'synthetic.xlsx',analysis_run_id:null,is_current:true,dataset_source:base}}],total:1,page:1,page_size:10})
  if(url.endsWith('/analysis-recommendation'))return Response.json(old)
  if(init?.method==='POST')return Response.json(task)
  return Response.json({...confirmed,task,source,input_version:task.input_version,input_kind:'data',selection,result:null,check:null,recommendation_ref:null,origin_recommendation_ref:{task_id:'old-rec',sha256:old.recommendation.sha256}})
 });vi.stubGlobal('fetch',fetch)
 render(<AnalysisPlanLauncher projectId={project} fileId={source.file_id} source={source} selection={selection} setupRevision={0} disabled={false} onPublished={()=>{}}/> )
 fireEvent.change(screen.getByLabelText('研究问题'),{target:{value:'Describe adults'}})
 fireEvent.click(screen.getByRole('button',{name:'读取上游历史建议'}))
 fireEvent.click(await screen.findByRole('button',{name:/来源整理版本 v1/}))
 fireEvent.click(await screen.findByRole('button',{name:'仅关联为起源证据，仍须重新检查计划'}))
 expect(screen.getByText('已绑定起源证据；当前有效建议为空。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'生成分析计划'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([u,i])=>u.endsWith('/analysis-plans')&&i?.method==='POST')).toBe(true))
 const call=fetch.mock.calls.find(([u,i])=>u.endsWith('/analysis-plans')&&i?.method==='POST')!
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({schema_version:5,input_kind:'data',dataset_id:source.dataset_id,recommendation_ref:null,origin_recommendation_ref:{task_id:'old-rec',sha256:old.recommendation.sha256}})
 expect(fetch.mock.calls.some(([u,i])=>u.includes('analysis-recommendations')&&i?.method==='POST')).toBe(false)
})
