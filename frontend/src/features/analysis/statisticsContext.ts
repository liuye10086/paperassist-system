import {isModelResult} from './modelResult'
import {isCorrelationResult} from './correlationResult'
import {isComparisonResult} from './comparisonResult'
import type {AnalysisSelection} from './analysisSelection'
import { isConfirmedPlan, type ConfirmedPlan } from '../analysisPlan/analysisPlanApi'
import { sameSource, type DatasetAnalysisSource } from './datasetSource'
import type { Selection } from './AnalysisSetup'

export type AnalysisContext = { plan: ConfirmedPlan; method: { id: 'descriptive'; parameters: Selection; observation_basis: 'rows' }; rounding: { display_significant_digits: 6; stored_values: 'full_precision' }; not_computed: { p_value: { value: null; reason: 'not_applicable_descriptive' }; effect_size: { value: null; reason: 'not_applicable_descriptive' }; confidence_interval: { value: null; reason: 'not_applicable_descriptive' } } }
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
const equalSelection = (a: unknown, b: Selection): boolean => object(a) && exactKeys(a, Object.keys(b)) && Object.entries(b).every(([key, value]) => a[key] === value)
export function validStatisticsContext(result: { schema_version?: unknown; engine?: unknown; analysis_context?: unknown; source?: DatasetAnalysisSource; setup_revision: number; selection: AnalysisSelection; result_type?:unknown; statistics?:unknown }, base: string, expectedPlan?: { plan_id: string; sha256: string }): boolean {
  if (object(result.engine) && Object.hasOwn(result.engine, 'execution_contract') && result.engine.execution_contract !== 'fixed_statistics_v2') return false
  if(['regression','roc','survival'].includes(String(result.result_type)))return isModelResult(result,base,expectedPlan)
  if(result.result_type==='correlation') return isCorrelationResult(result,base,expectedPlan)
  if(result.result_type==='group_comparison') return isComparisonResult(result,base,expectedPlan)
  if(result.result_type!==undefined) return false
  if(result.selection.task_type!=='descriptive_boxplot') return false
  if (!Object.hasOwn(result, 'schema_version') && !Object.hasOwn(result, 'analysis_context')) return true
  if ((result.schema_version !== 2 && result.schema_version!==3) || !object(result.analysis_context) || !result.source) return false
  const match = /^\/api\/v1\/projects\/([^/]+)\/files\/([^/]+)$/.exec(base)
  if (!match) return false
  const context = result.analysis_context
  if (!exactKeys(context, ['plan', 'method', 'rounding', 'not_computed']) || !isConfirmedPlan(context.plan, decodeURIComponent(match[1]), decodeURIComponent(match[2])) || (context.plan.schema_version !== result.schema_version && !([4,5].includes(context.plan.schema_version)&&result.schema_version===3)) || context.plan.setup_revision !== result.setup_revision || !sameSource(context.plan.source, result.source) || !equalSelection(context.plan.selection, result.selection)) return false
  if (expectedPlan && (context.plan.id !== expectedPlan.plan_id || context.plan.sha256 !== expectedPlan.sha256)) return false
  return object(context.method) && exactKeys(context.method, ['id', 'parameters', 'observation_basis']) && context.method.id === 'descriptive' && context.method.observation_basis === 'rows' && equalSelection(context.method.parameters, result.selection)
    && object(context.rounding) && exactKeys(context.rounding, ['display_significant_digits', 'stored_values']) && context.rounding.display_significant_digits === 6 && context.rounding.stored_values === 'full_precision'
    && object(context.not_computed) && exactKeys(context.not_computed, ['p_value', 'effect_size', 'confidence_interval']) && Object.values(context.not_computed).every(item => object(item) && exactKeys(item, ['value', 'reason']) && item.value === null && item.reason === 'not_applicable_descriptive')
}
