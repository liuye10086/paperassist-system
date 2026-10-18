import {test,expect} from 'vitest'
import {isRecommendationPreview} from './recommendationApi'
import {reviewFixture} from './analysisPlanFixtures'
import type {PreparedDatasetAnalysisSource} from '../analysis/datasetSource'
const source=reviewFixture.source as PreparedDatasetAnalysisSource
const methods=['descriptive','pearson','spearman','welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis','ols','logistic','roc_auc','kaplan_meier']
test('recommendation v3 previews approved methods and no extra roles',()=>{const request={schema_version:3,dataset_id:source.dataset_id,sheet_name:source.sheet_name,candidate_columns:['A'],output_language:'en',research_summary:''} as const;const v={version:3,provider:'openai',source,source_digest:'x',fields:[{column:'A',name:'x',type:'number',unit:{status:'confirmed',value:''},missing_count:0,non_missing_count:5}],labels:[{key:'field:A',value:'x'},{key:'research_summary',value:''}],allowed_methods:methods,allowed_modes:['pair','matrix','independent','paired','multiple','regression','roc','survival'],output_language:'en',research_summary:''};expect(isRecommendationPreview(v,source,request as never)).toBe(true)})
