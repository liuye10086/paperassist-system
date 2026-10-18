import type {ResearchRequest} from './researchRequest'
import type {CorrelationSelection} from '../analysis/analysisSelection'
import { reviewFixture } from './analysisPlanFixtures'
export const correlationSelection:CorrelationSelection = { task_type: 'correlation', sheet_name: reviewFixture.source.sheet_name, method: 'pearson', mode: 'pair', columns: ['C', 'D'], units: { C: 'kg', D: 'cm' }, missing_policy: 'complete_cases', assumptions: { independent_observations: true, relationship_form: 'linear', inference_assumptions_confirmed: true } }
export const research:ResearchRequest = { question: 'private original question', output_language: 'en', population: 'Synthetic participants', study_design: 'Cross-sectional', observation_unit: 'One row per participant', observation_structure: 'independent', relationship_description: '', output_requirements: '' }
export const input = { ...reviewFixture.input_version, workflow_version: 'analysis_plan_v3' }
export const v3Review = { ...reviewFixture, selection: correlationSelection, input_version: input, research_request: research, recommendation_ref: null, task: { ...reviewFixture.task, input_version: input }, check: { ...reviewFixture.check, rules_version: 'analysis_plan_rules_v3', research_missing: [] } }
export const v3Plan = { schema_version: 3, workflow_version: 'analysis_plan_v3', rules_version: 'analysis_plan_rules_v3', ...v3Review, id: 'plan3', task_id: 't1', decision_id: 'decision3', project_id: 'p1', file_id: 'f1', setup_revision: 2, created_at: reviewFixture.task.created_at, sha256: 'c'.repeat(64) }
