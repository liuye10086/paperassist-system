import {expect,it} from 'vitest'
import {isRecommendationReview} from './recommendationApi'
import fixture from './batch09RecommendationFixture.json'
it('accepts v5 exact source references and rejects fabricated aliases',()=>{
 const v=structuredClone(fixture) as any
 v.task.input_version.workflow_version='analysis_recommendation_v5';v.input_version.workflow_version='analysis_recommendation_v5';v.request.schema_version=5;v.recommendation.schema_version=5
 v.external_processing.labels.research_summary='F1/S1/D1'
 v.recommendation.intent.evidence=[{start:0,end:8,quote:'F1/S1/D1'}]
 v.recommendation.source_reference={status:'matched',references:[{code:'F1',level:'file'}],evidence:[{start:0,end:2,quote:'F1'}]}
 expect(isRecommendationReview(v,v.task.project_id)).toBe(true)
 v.recommendation.source_reference.references[0].code='F2'
 expect(isRecommendationReview(v,v.task.project_id)).toBe(false)
})
