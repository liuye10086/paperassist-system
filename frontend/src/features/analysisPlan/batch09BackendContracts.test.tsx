import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import confirmed from './batch09ConfirmedFixture.json'
import recommendation from './batch09RecommendationFixture.json'
import missing from './batch09RecommendationMissingFixture.json'
import filter from '../datasetPreparation/batch09BackendFixture.json'
import {isRequirementReview} from './requirementsApi'
import {isConfirmedPlan,numericPlanCheck} from './analysisPlanApi'
import {isRecommendationReview} from './recommendationApi'
import {RecommendationResult} from './AnalysisRecommendation'
import ReportPreview from '../report-collections/ReportPreview'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('accepts actual backend fulfilled requirement and both v4 recommendation contracts',()=>{
 expect(isRequirementReview(confirmed,confirmed.task.project_id)).toBe(true)
 expect(isConfirmedPlan(confirmed.result,confirmed.task.project_id,confirmed.source.file_id)).toBe(true)
 expect(isRecommendationReview(recommendation,recommendation.task.project_id)).toBe(true)
 expect(isRecommendationReview(missing,missing.task.project_id)).toBe(true)
 if(isConfirmedPlan(confirmed.result,confirmed.task.project_id,confirmed.source.file_id))expect(numericPlanCheck(confirmed.result)?.selection_check?.ready).toBe(true)
})
it('shows a no-method v4 suggestion as adoptable missing input without a second model call',async()=>{
 const fetch=vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?{task:missing.task,source:{file_id:missing.source.file_id,filename:'synthetic.xlsx',analysis_run_id:null,is_current:true,dataset_source:missing.source},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}:missing));vi.stubGlobal('fetch',fetch)
 const adopt=vi.fn();render(<RecommendationResult projectId={missing.task.project_id} taskId={missing.task.id} onAdopt={adopt}/> )
 expect(await screen.findByRole('button',{name:'采纳为待补充需求'})).toBeTruthy()
 expect(screen.getByText('研究识别候选（待校对）')).toBeTruthy()
 expect(document.body.textContent).not.toContain(missing.recommendation.sha256)
 expect(fetch.mock.calls.every(([url])=>!url.includes('/preview'))).toBe(true)
})
it('renders v3 filter and ancestor processing as readable rules and counts, hiding internal manifests',()=>{
 const v=filter.published,processing={schema_version:3,operation:'population_filter',recipe:v.recipe,receipt:v.summary,base_source:v.base_source,manifest:{object_key:'secret-object-key',sha256:'a'.repeat(64),size_bytes:100,entry_count:7},ancestors:[]}
 render(<ReportPreview ready sections={[{key:'processing',title:'筛选回执',content:[processing]}]}/> )
 expect(screen.getByText('逐条件完整影响')).toBeTruthy()
 expect(document.body.textContent).not.toContain('secret-object-key')
 expect(document.body.textContent).not.toContain('a'.repeat(64))
})
