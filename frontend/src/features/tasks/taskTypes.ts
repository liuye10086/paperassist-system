import {validAssistanceResult,type SearchPlanResult,type EvidenceReviewResult} from '../literature/assistanceContracts'
import {validStatisticsTaskResult} from '../analysis/statisticsTaskContracts'
import type {Result} from '../analysis/StatisticsResults'
import {isEvidenceVersion,type EvidenceVersion} from '../parsedEvidence/externalEvidenceApi'
import { isDatasetSource, sameSource, type DatasetAnalysisSource } from '../analysis/datasetSource'
import { isReviewSource, sameReviewSource, type ReviewInputVersion } from '../documents/ocrReviewTypes'
export const taskNames = { journal_adaptation:'期刊指南适配', journal_format_check:'期刊格式检查', journal_recommendation:'期刊建议', school_template_parse:'学校模板解析', layout_docx:'排版 DOCX 导出', manuscript_writing:'完整稿件写作', pdf_export:'PDF 导出', manuscript_draft:'稿件本地事实整理',manuscript_docx:'稿件 DOCX 导出', literature_assistance:'文献模型建议', literature_search:'文献检索', statistics_compute:'固定统计计算',figure_projection:'图表计算确认',figure_workbench:'配置图表生成',figure_explanation:'图表六节解释',collection_word_report:'集合 Word 整理',boxplot: '图表生成', explanation: 'AI 分析解释', word_report: 'Word 报告导出', parse_file: '文件解析', extract_dataset: 'Excel 结构提取', prepare_dataset: '数据整理', analysis_recommendation:'受限分析建议', analysis_plan: '分析计划', review_ocr:'文字人工核对' }
export const statusNames = { queued: '待执行', running: '运行中', waiting_input: '待补充资料',
  waiting_confirmation: '待用户确认', succeeded: '已完成', failed: '执行失败' }
export const displayNames = { queued: '待执行', parsing: '文件解析中', analyzing: 'AI 分析中', computing: '数据计算中',
  searching: '文献检索中', generating_document: '文档生成中', waiting_input: '待补充资料', waiting_confirmation: '待用户确认',
  succeeded: '已完成', failed: '执行失败' }
export const phaseNames = { parse: '解析资料', plan: '分析计划', compute: '计算与绘图', search: '检索资料',
  interpret: '分析解释', write: '生成文字', export: '导出文档', verify: '核查结果' }
export const eventNames = { created: '任务已建立', started: '开始执行', phase_changed: '处理阶段已更新', waiting: '等待处理',
  succeeded: '成果已保存', failed: '本次执行失败', requeued: '任务已重新排队', deferred: '等待后续处理' }
export type TaskType = keyof typeof taskNames
export type TaskStatus = keyof typeof statusNames
const errorCategories = ['temporary', 'authentication', 'permission', 'configuration', 'source', 'output',
  'submission_unknown', 'budget', 'interrupted', 'internal'] as const
const retryReasons = ['temporary_provider_error', 'worker_interrupted', 'manual_retry'] as const
export type ErrorCategory = typeof errorCategories[number]
export type RetryReason = typeof retryReasons[number]
export type RetryCount = 0 | 1 | 2 | 3
export type PreparationInputVersion = { kind: 'dataset_preparation'; source: DatasetAnalysisSource; workflow_version: 'dataset_preparation_v1' | 'dataset_preparation_v2' | 'dataset_preparation_v3'; setup_revision?: never; output_language?: never }
export type AnalysisPlanInputVersion = { kind: 'analysis_plan'; source: DatasetAnalysisSource | null; workflow_version: 'analysis_plan_v1' | 'analysis_plan_v2' | 'analysis_plan_v3' | 'analysis_plan_v4' | 'analysis_plan_v5'; setup_revision?: never; output_language?: never }
export type RecommendationInputVersion = { kind:'analysis_recommendation';source:DatasetAnalysisSource;workflow_version:'analysis_recommendation_v1'|'analysis_recommendation_v2'|'analysis_recommendation_v3'|'analysis_recommendation_v4'|'analysis_recommendation_v5';setup_revision?:never;output_language?:never }
export type CollectionInputVersion={kind:'report_collection';collection_version_id:string;export_revision:number;output_language:'zh-CN'|'en';workflow_version:'collection_word_report_v1';setup_revision?:never}
export type StatisticsInputVersion={kind:'statistics_compute';setup_revision:number;output_language:'zh-CN'|'en';source:DatasetAnalysisSource|null;analysis_plan_id:string|null;workflow_version:'statistics_compute_v1'}
export type LiteratureInputVersion = {kind:'literature_search';workflow_version:'literature_search_v1';search_id:string;input_digest:string;output_language:'zh-CN'|'en';setup_revision?:never}
export type AssistanceInputVersion={kind:'literature_assistance';workflow_version:'literature_assistance_v1';assistance_kind:'search_plan'|'evidence_review'|'evidence_comparison';input_digest:string;output_language:'zh-CN'|'en';setup_revision?:never}
export type ManuscriptInputVersion={kind:'manuscript';manuscript_version_id:string;output_language:'zh-CN'|'en';workflow_version:'manuscript_fact_draft_v1';setup_revision?:never}
export type PdfInputVersion={kind:'pdf_export';export_id:string;source_kind:'report'|'collection_report'|'manuscript_export'|'layout_export';source_id:string;source_sha256:string;workflow_version:'pdf_export_v1';setup_revision?:never;output_language?:never}
export type WritingInputVersion={kind:'manuscript_writing';base_version_id:string;base_revision:number;output_language:'zh-CN'|'en';workflow_version:'manuscript_writing_v1'|'manuscript_writing_v2';setup_revision?:never}
export type LayoutInputVersion={kind:'layout_docx';export_id:string;source_kind:'report'|'collection_report'|'manuscript_export';source_id:string;source_sha256:string;workflow_version:'layout_docx_v1';setup_revision?:never;output_language?:never}
export type SchoolTemplateInputVersion={kind:'school_template';template_version_id:string;parser_version:'school-template-openxml-v1';workflow_version:'school_template_v1';setup_revision?:never;output_language?:never}
export type JournalInputVersion={kind:'journal_recommendation';recommendation_id:string;workflow_version:'journal_recommendation_v1';setup_revision?:never;output_language?:never}
export type JournalFormatInputVersion={kind:'journal_format_check';check_id:string;target_id:string;guide_id:string;requirements_version:string;manuscript_version_id:string;check_version:1;workflow_version:'journal_format_check_v1';setup_revision?:never;output_language?:never}
export type JournalAdaptationInputVersion={kind:'journal_adaptation';adaptation_id:string;target_id:string;check_id:string;manuscript_version_id:string;requirements_version:string;workflow_version:'journal_adaptation_v1';setup_revision?:never;output_language?:never}
export type InputVersion = JournalAdaptationInputVersion | JournalFormatInputVersion | JournalInputVersion | SchoolTemplateInputVersion | LayoutInputVersion | WritingInputVersion | PdfInputVersion | ManuscriptInputVersion | AssistanceInputVersion | LiteratureInputVersion | StatisticsInputVersion | CollectionInputVersion | RecommendationInputVersion | ReviewInputVersion | PreparationInputVersion | AnalysisPlanInputVersion | { kind: 'dataset_analysis'; setup_revision: number; output_language: 'zh-CN' | 'en'; source: DatasetAnalysisSource } | { kind: 'excel_structure'; structure_id: string; source_sha256: string; parser_version: string; setup_revision?: never; output_language?: never } | { setup_revision: number; output_language: 'zh-CN'; kind?: never } | { kind: 'parse_file'; parse_id: string; source_sha256: string; parser_version: string; setup_revision?: never; output_language?: never }
export type TaskView = { id: string; project_id: string; task_type: TaskType; status: TaskStatus; phase: keyof typeof phaseNames;
  display_status: keyof typeof displayNames; reason_code: string | null;
  error_code: string | null; created_at: string; input_version: InputVersion;
  result_analysis_run_id?: string | null; execution_receipt?: Record<string,unknown> | null; result_figure_id?: string | null; result_explanation_id?: string | null; result_report_id?: string | null } & (
  { origin?: 'unified'; revision: number; current_attempt: number; retry_count?: RetryCount | null; updated_at: string }
  | { origin: 'legacy'; revision: null; current_attempt: null; retry_count: null; updated_at: null })
export type TaskSource = { material_versions?:EvidenceVersion[];continuation_task_id?:string;file_id: string | null; filename: string; analysis_run_id: string | null; is_current: boolean; dataset_source?: DatasetAnalysisSource }
export type TaskItem = { task: TaskView; source: TaskSource }
export type TaskPage = { project_id: string; items: TaskItem[]; total: number; page: number; page_size: number }
export type TaskOperation = 'resume' | 'retry' | 'approve' | 'revise'
export type TaskWait = { id: string; kind: 'literature_model_authorization' | 'literature_configuration' | 'figure_projection_confirmation' | 'ocr_review_confirmation' | 'dataset_preparation_confirmation' | 'analysis_plan_confirmation' | 'analysis_plan_input' | 'budget_confirmation' | 'remote_observation' | 'submission_unknown' | 'unsupported_input' | 'unsupported_confirmation';
  status: 'open' | 'resolved' | 'superseded'; task_revision: number; input_version: InputVersion;
  reason_code: string | null; error_code: string | null; created_at: string; resolved_at: string | null }
export type VerificationFailure = {schema_version:1;status:'mismatched';recorded_at:string;differences:{path:string;expected:string|number|boolean|null;actual:string|number|boolean|null;reason:string|null}[];manifest:Record<string,unknown>;provenance:Record<string,unknown>}
export type TaskWorkspace = TaskItem & {verification_failure?:VerificationFailure; wait: TaskWait | null; allowed_actions: TaskOperation[]; artifacts: {
  manuscript?:{id:string;version_id:string;revision:number;download_url:null}|null;literature_assistance?:{kind:'search_plan'|'evidence_review'|'evidence_comparison';result:SearchPlanResult|EvidenceReviewResult|null;real_calls_enabled:false}|null;literature?: {search_id:string;retrieved_count:number;matched_count:number|null}|null; analysis?: Result | null; figure: { title: string; caption: string; download_url: string } | null;
  explanation: { sections: { key: string; title: string; text: string }[]; limitations: string[] } | null;
  report: { filename: string; download_url: string } | null; dataset?: { filename: string; download_url: string } } }
export type TaskEvent = { seq: number; task_revision: number; event_type: keyof typeof eventNames; status: TaskStatus;
  phase: keyof typeof phaseNames; reason_code: string | null; created_at: string;
  error_code?: string | null; error_category?: ErrorCategory | null; retry_reason?: RetryReason | null;
  retry_count?: RetryCount | null; retry_delay_seconds?: 10 | 30 | 90 | null }
export type EventPage = { task_id: string; items: TaskEvent[]; next_cursor: number; has_more: boolean }

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const text = (value: unknown): value is string => typeof value === 'string'
const id = (value: unknown): value is string => text(value) && value.length > 0 && value.length <= 64 && !/\s/.test(value)
const integer = (value: unknown, min = 0): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min
const retryCount = (value: unknown) => value == null || (integer(value) && value <= 3)
const date = (value: unknown) => text(value) && Number.isFinite(Date.parse(value))
const nullableText = (value: unknown) => value === null || text(value)
const own = (map: object, value: unknown) => text(value) && Object.hasOwn(map, value)
function legacyTaskId(value: string): boolean {
  const match = /^legacy-(plot|explanation):([A-Za-z0-9_-]+)$/.exec(value)
  if (!match) return false
  try {
    const encoded = match[2]
    const bytes = atob(encoded.replace(/-/g, '+').replace(/_/g, '/'))
    if (btoa(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') !== encoded) return false
    // Historical IDs are canonical base64url of a nonempty UTF-8 string.
    new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bytes, char => char.charCodeAt(0)))
    return true
  } catch { return false }
}
export function isTaskId(value: unknown): value is string {
  return text(value) && (value.startsWith('legacy-') ? legacyTaskId(value) : id(value))
}
function version(value: unknown, parse: boolean | string = false): value is InputVersion {
  if(parse==='journal_adaptation')return record(value)&&Object.keys(value).length===7&&value.kind==='journal_adaptation'&&['adaptation_id','target_id','check_id','manuscript_version_id'].every(k=>id(value[k]))&&text(value.requirements_version)&&/^[a-f0-9]{64}$/.test(value.requirements_version)&&value.workflow_version==='journal_adaptation_v1'
  if(parse==='journal_format_check')return record(value)&&Object.keys(value).length===8&&value.kind==='journal_format_check'&&['check_id','target_id','guide_id','manuscript_version_id'].every(k=>id(value[k]))&&text(value.requirements_version)&&/^[a-f0-9]{64}$/.test(value.requirements_version)&&value.check_version===1&&value.workflow_version==='journal_format_check_v1'
  if(parse==='journal_recommendation')return record(value)&&Object.keys(value).length===3&&value.kind==='journal_recommendation'&&id(value.recommendation_id)&&value.workflow_version==='journal_recommendation_v1'
  if(parse==='manuscript_writing')return record(value)&&Object.keys(value).length===5&&value.kind==='manuscript_writing'&&id(value.base_version_id)&&integer(value.base_revision,1)&&['zh-CN','en'].includes(String(value.output_language))&&['manuscript_writing_v1','manuscript_writing_v2'].includes(String(value.workflow_version))
  if(parse==='layout_docx')return record(value)&&Object.keys(value).length===6&&value.kind==='layout_docx'&&id(value.export_id)&&['report','collection_report','manuscript_export'].includes(String(value.source_kind))&&id(value.source_id)&&text(value.source_sha256)&&/^[a-f0-9]{64}$/.test(value.source_sha256)&&value.workflow_version==='layout_docx_v1'
  if(parse==='pdf_export')return record(value)&&Object.keys(value).length===6&&value.kind==='pdf_export'&&id(value.export_id)&&['report','collection_report','manuscript_export','layout_export'].includes(String(value.source_kind))&&id(value.source_id)&&text(value.source_sha256)&&/^[a-f0-9]{64}$/.test(value.source_sha256)&&value.workflow_version==='pdf_export_v1'
  if(parse==='manuscript_draft'||parse==='manuscript_docx')return record(value)&&Object.keys(value).length===4&&value.kind==='manuscript'&&id(value.manuscript_version_id)&&['zh-CN','en'].includes(String(value.output_language))&&value.workflow_version==='manuscript_fact_draft_v1'
  if(parse==='literature_assistance')return record(value)&&Object.keys(value).length===5&&value.kind==='literature_assistance'&&value.workflow_version==='literature_assistance_v1'&&['search_plan','evidence_review','evidence_comparison'].includes(String(value.assistance_kind))&&text(value.input_digest)&&/^[a-f0-9]{64}$/.test(value.input_digest)&&['zh-CN','en'].includes(String(value.output_language))
  if(parse==='literature_search')return record(value)&&Object.keys(value).length===5&&value.kind==='literature_search'&&value.workflow_version==='literature_search_v1'&&id(value.search_id)&&text(value.input_digest)&&/^[a-f0-9]{64}$/.test(value.input_digest)&&['zh-CN','en'].includes(String(value.output_language))
  if(parse==='school_template_parse')return record(value)&&Object.keys(value).length===4&&value.kind==='school_template'&&id(value.template_version_id)&&value.parser_version==='school-template-openxml-v1'&&value.workflow_version==='school_template_v1'
  if(parse==='statistics_compute')return record(value)&&Object.keys(value).length===6&&value.kind==='statistics_compute'&&integer(value.setup_revision,1)&&['zh-CN','en'].includes(String(value.output_language))&&(value.source===null||isDatasetSource(value.source))&&(value.analysis_plan_id===null||id(value.analysis_plan_id))&&value.workflow_version==='statistics_compute_v1'
  if(parse==='collection_word_report')return record(value)&&Object.keys(value).length===5&&value.kind==='report_collection'&&id(value.collection_version_id)&&integer(value.export_revision,1)&&['zh-CN','en'].includes(String(value.output_language))&&value.workflow_version==='collection_word_report_v1'
  if(typeof parse==='string'&&['figure_projection','figure_workbench','figure_explanation'].includes(parse))return record(value)&&isDatasetSource(value.source)&&value.source.kind==='prepared_dataset_version'&&value.kind==='dataset_analysis'&&version(value,false)
  if (parse === 'review_ocr') return record(value) && value.kind === 'ocr_review' && value.workflow_version === 'ocr_review_v1' && isReviewSource(value.source) && !('setup_revision' in value) && !('output_language' in value)
  if (parse === 'prepare_dataset') return record(value) && value.kind === 'dataset_preparation' && isDatasetSource(value.source) && (value.workflow_version === 'dataset_preparation_v1' && value.source.kind === 'dataset_version' || ['dataset_preparation_v2','dataset_preparation_v3'].includes(String(value.workflow_version)) && value.source.kind === 'prepared_dataset_version') && Object.keys(value).length === 3
  if (parse === 'analysis_recommendation') return record(value) && Object.keys(value).length===3 && value.kind==='analysis_recommendation' && ['analysis_recommendation_v1','analysis_recommendation_v2','analysis_recommendation_v3','analysis_recommendation_v4','analysis_recommendation_v5'].includes(String(value.workflow_version)) && isDatasetSource(value.source) && value.source.kind==='prepared_dataset_version'
  if (parse === 'analysis_plan') return record(value) && Object.keys(value).length === 3 && value.kind === 'analysis_plan' && ['analysis_plan_v1', 'analysis_plan_v2','analysis_plan_v3','analysis_plan_v4','analysis_plan_v5'].includes(String(value.workflow_version)) && (['analysis_plan_v4','analysis_plan_v5'].includes(String(value.workflow_version)) && value.source === null || isDatasetSource(value.source) && value.source.kind === 'prepared_dataset_version')
  if (parse === 'extract_dataset') return record(value) && value.kind === 'excel_structure' && id(value.structure_id) && text(value.source_sha256) && /^[a-f0-9]{64}$/.test(value.source_sha256) && text(value.parser_version) && value.parser_version.length > 0 && !('setup_revision' in value) && !('output_language' in value)
  if (parse) return record(value) && value.kind === 'parse_file' && id(value.parse_id) && text(value.source_sha256) && /^[a-f0-9]{64}$/.test(value.source_sha256) && text(value.parser_version) && value.parser_version.length > 0 && !('setup_revision' in value) && !('output_language' in value)
  if (record(value) && value.kind === 'dataset_analysis') return Object.keys(value).length === 4 && integer(value.setup_revision, 1) && ['zh-CN','en'].includes(String(value.output_language)) && isDatasetSource(value.source)
  return record(value) && !('kind' in value) && !('source' in value) && integer(value.setup_revision, 1) && value.output_language === 'zh-CN'
}
export function sameInputVersion(a: InputVersion, b: InputVersion): boolean {
  if(a.kind==='journal_adaptation'||b.kind==='journal_adaptation')return a.kind==='journal_adaptation'&&b.kind==='journal_adaptation'&&['adaptation_id','target_id','check_id','requirements_version','manuscript_version_id','workflow_version'].every(k=>a[k as keyof JournalAdaptationInputVersion]===b[k as keyof JournalAdaptationInputVersion])
  if(a.kind==='journal_format_check'||b.kind==='journal_format_check')return a.kind==='journal_format_check'&&b.kind==='journal_format_check'&&['check_id','target_id','guide_id','requirements_version','manuscript_version_id','check_version','workflow_version'].every(k=>a[k as keyof JournalFormatInputVersion]===b[k as keyof JournalFormatInputVersion])
  if(a.kind==='journal_recommendation'||b.kind==='journal_recommendation')return a.kind==='journal_recommendation'&&b.kind==='journal_recommendation'&&a.recommendation_id===b.recommendation_id&&a.workflow_version===b.workflow_version
  if(a.kind==='school_template'||b.kind==='school_template')return a.kind==='school_template'&&b.kind==='school_template'&&a.template_version_id===b.template_version_id&&a.parser_version===b.parser_version&&a.workflow_version===b.workflow_version
  if(a.kind==='manuscript_writing'||b.kind==='manuscript_writing')return a.kind==='manuscript_writing'&&b.kind==='manuscript_writing'&&a.base_version_id===b.base_version_id&&a.base_revision===b.base_revision&&a.output_language===b.output_language&&a.workflow_version===b.workflow_version
  if(a.kind==='layout_docx'||b.kind==='layout_docx')return a.kind==='layout_docx'&&b.kind==='layout_docx'&&a.export_id===b.export_id&&a.source_kind===b.source_kind&&a.source_id===b.source_id&&a.source_sha256===b.source_sha256&&a.workflow_version===b.workflow_version
  if(a.kind==='pdf_export'||b.kind==='pdf_export')return a.kind==='pdf_export'&&b.kind==='pdf_export'&&a.export_id===b.export_id&&a.source_kind===b.source_kind&&a.source_id===b.source_id&&a.source_sha256===b.source_sha256&&a.workflow_version===b.workflow_version
  if(a.kind==='manuscript'||b.kind==='manuscript')return a.kind==='manuscript'&&b.kind==='manuscript'&&a.manuscript_version_id===b.manuscript_version_id&&a.output_language===b.output_language&&a.workflow_version===b.workflow_version
  if(a.kind==='literature_assistance'||b.kind==='literature_assistance')return a.kind==='literature_assistance'&&b.kind==='literature_assistance'&&a.assistance_kind===b.assistance_kind&&a.input_digest===b.input_digest&&a.workflow_version===b.workflow_version&&a.output_language===b.output_language
  if(a.kind==='literature_search'||b.kind==='literature_search')return a.kind==='literature_search'&&b.kind==='literature_search'&&a.search_id===b.search_id&&a.input_digest===b.input_digest&&a.workflow_version===b.workflow_version&&a.output_language===b.output_language
  if(a.kind==='statistics_compute'||b.kind==='statistics_compute')return a.kind==='statistics_compute'&&b.kind==='statistics_compute'&&a.setup_revision===b.setup_revision&&a.output_language===b.output_language&&a.analysis_plan_id===b.analysis_plan_id&&a.workflow_version===b.workflow_version&&sameSource(a.source,b.source)
  if(a.kind==='report_collection'||b.kind==='report_collection')return a.kind==='report_collection'&&b.kind==='report_collection'&&a.collection_version_id===b.collection_version_id&&a.export_revision===b.export_revision&&a.output_language===b.output_language&&a.workflow_version===b.workflow_version
  if (a.kind === 'ocr_review' || b.kind === 'ocr_review') return a.kind === 'ocr_review' && b.kind === 'ocr_review' && a.workflow_version === b.workflow_version && sameReviewSource(a.source,b.source)
  if (a.kind === 'dataset_preparation' || b.kind === 'dataset_preparation') return a.kind === 'dataset_preparation' && b.kind === 'dataset_preparation' && a.workflow_version === b.workflow_version && sameSource(a.source, b.source)
  if (a.kind==='analysis_recommendation'||b.kind==='analysis_recommendation') return a.kind==='analysis_recommendation' && b.kind==='analysis_recommendation' && a.workflow_version===b.workflow_version && sameSource(a.source,b.source)
  if (a.kind === 'analysis_plan' || b.kind === 'analysis_plan') return a.kind === 'analysis_plan' && b.kind === 'analysis_plan' && a.workflow_version === b.workflow_version && (a.source === null && b.source === null || sameSource(a.source, b.source))
  if (a.kind === 'dataset_analysis' || b.kind === 'dataset_analysis') return a.kind === 'dataset_analysis' && b.kind === 'dataset_analysis' && a.setup_revision === b.setup_revision && a.output_language === b.output_language && sameSource(a.source, b.source)
  if (a.kind === 'excel_structure' && b.kind === 'excel_structure') return a.structure_id === b.structure_id && a.source_sha256 === b.source_sha256 && a.parser_version === b.parser_version
  if (a.kind === 'parse_file' && b.kind === 'parse_file') return a.parse_id === b.parse_id && a.source_sha256 === b.source_sha256 && a.parser_version === b.parser_version
  return a.kind === undefined && b.kind === undefined && a.setup_revision === b.setup_revision && a.output_language === b.output_language
}
export function isTask(value: unknown, projectId: string, taskId?: string): value is TaskView {
  if (!record(value) || !isTaskId(value.id) || (taskId !== undefined && value.id !== taskId) || value.project_id !== projectId
    || !own(taskNames, value.task_type) || !own(statusNames, value.status) || !own(phaseNames, value.phase)
    || !own(displayNames, value.display_status)
    || !nullableText(value.reason_code) || !nullableText(value.error_code) || !date(value.created_at)
    || !version(value.input_version, ['journal_adaptation','journal_format_check','journal_recommendation','school_template_parse','layout_docx','manuscript_writing','pdf_export','manuscript_draft','manuscript_docx','literature_assistance','literature_search','statistics_compute','figure_projection','figure_workbench','figure_explanation','collection_word_report','extract_dataset','prepare_dataset','analysis_plan','analysis_recommendation','review_ocr'].includes(String(value.task_type)) ? String(value.task_type) : value.task_type === 'parse_file')) return false
  if(value.task_type==='journal_adaptation'&&(value.origin==='legacy'||value.phase!=='verify'||!['queued','running','succeeded','failed'].includes(String(value.status))||['result_figure_id','result_explanation_id','result_report_id','result_analysis_run_id'].some(k=>value[k]!=null)))return false
  if(value.task_type==='journal_format_check'&&(value.origin==='legacy'||value.phase!=='verify'||!['queued','running','succeeded','failed'].includes(String(value.status))||['result_figure_id','result_explanation_id','result_report_id','result_analysis_run_id'].some(k=>value[k]!=null)))return false
  if(value.task_type==='journal_recommendation'&&(value.origin==='legacy'||value.phase!=='plan'||!['queued','running','succeeded','failed'].includes(String(value.status))||['result_figure_id','result_explanation_id','result_report_id'].some(k=>value[k]!=null)))return false
  if(value.task_type==='school_template_parse'&&(value.origin==='legacy'||value.phase!=='parse'||!['queued','running','succeeded','failed'].includes(String(value.status))||['result_figure_id','result_explanation_id','result_report_id'].some(k=>value[k]!=null)))return false
  if(value.task_type==='manuscript_writing'&&(value.input_version.kind!=='manuscript_writing'||value.origin==='legacy'||value.phase!=='write'||['result_figure_id','result_explanation_id','result_report_id'].some(k=>value[k]!=null)))return false
  if(['manuscript_draft','manuscript_docx'].includes(String(value.task_type))&&(value.input_version.kind!=='manuscript'||value.origin==='legacy'||value.phase!==(value.task_type==='manuscript_draft'?'write':'export')||!['queued','running','succeeded','failed'].includes(String(value.status))))return false
  if(value.task_type==='layout_docx'&&(value.origin==='legacy'||value.input_version.kind!=='layout_docx'||value.phase!=='export'||!['queued','running','succeeded','failed'].includes(String(value.status))||['result_figure_id','result_explanation_id','result_report_id'].some(k=>value[k]!=null)))return false
  if(value.task_type==='pdf_export'&&(value.origin==='legacy'||value.input_version.kind!=='pdf_export'||value.phase!=='export'||!['queued','running','succeeded','failed'].includes(String(value.status))||['result_figure_id','result_explanation_id','result_report_id'].some(k=>value[k]!=null)))return false
  if(value.task_type==='literature_assistance'&&(value.origin==='legacy'||value.input_version.kind!=='literature_assistance'||value.phase!==(value.input_version.assistance_kind==='search_plan'?'plan':'verify')||['result_figure_id','result_explanation_id','result_report_id'].some(k=>value[k]!=null)))return false
  if(value.task_type==='literature_search'&&(value.origin==='legacy'||value.phase!=='search'||value.input_version.kind!=='literature_search'||value.input_version.search_id!==value.id||['result_figure_id','result_explanation_id','result_report_id'].some(k=>value[k]!=null)))return false
  if(value.task_type==='statistics_compute'&&(value.input_version.kind!=='statistics_compute'||value.origin==='legacy'||value.phase!=='compute'||!['queued','running','succeeded','failed'].includes(String(value.status))||value.result_analysis_run_id!==null&&!id(value.result_analysis_run_id)||value.execution_receipt!==null&&!record(value.execution_receipt)||['result_figure_id','result_explanation_id','result_report_id'].some(k=>value[k]!=null)||value.status==='succeeded'&&(!id(value.result_analysis_run_id)||!record(value.execution_receipt))))return false
  if(value.task_type!=='statistics_compute'&&record(value.input_version)&&value.input_version.kind==='statistics_compute')return false
  if (['parse_file', 'extract_dataset'].includes(String(value.task_type)) && (value.phase !== 'parse' || ['result_figure_id', 'result_explanation_id', 'result_report_id'].some(key => value[key] != null))) return false
  if (value.origin === 'legacy') {
    if (value.input_version.kind === 'dataset_analysis' || !legacyTaskId(value.id) || value.revision !== null || value.current_attempt !== null
      || value.retry_count !== null || value.updated_at !== null
      || value.task_type !== (value.id.startsWith('legacy-plot:') ? 'boxplot' : 'explanation')) return false
  } else if ((value.origin !== undefined && value.origin !== 'unified') || value.id.startsWith('legacy-')
    || !integer(value.revision, 1) || !integer(value.current_attempt) || !date(value.updated_at)
    || !retryCount(value.retry_count)) return false
  return ['result_figure_id', 'result_explanation_id', 'result_report_id'].every(key => value[key] == null || id(value[key]))
}
function sourceMatchesTask(task: TaskView, projection: TaskSource) {
  if(task.input_version.kind==='journal_adaptation'||task.input_version.kind==='journal_format_check'||task.input_version.kind==='journal_recommendation')return projection.file_id===null&&projection.analysis_run_id===null&&projection.dataset_source===undefined
  if(task.input_version.kind==='school_template')return id(projection.file_id)&&projection.analysis_run_id===null&&projection.dataset_source===undefined
  if(task.input_version.kind==='layout_docx'||task.input_version.kind==='pdf_export')return projection.file_id===null&&projection.analysis_run_id===null&&projection.dataset_source===undefined
  if(task.input_version.kind==='manuscript_writing')return projection.file_id===null&&projection.analysis_run_id===null&&projection.dataset_source===undefined
  if(task.input_version.kind==='manuscript')return projection.file_id===null&&projection.analysis_run_id===null&&projection.dataset_source===undefined
  if(task.input_version.kind==='literature_assistance')return projection.file_id===null&&projection.analysis_run_id===null&&projection.dataset_source===undefined
  if(task.input_version.kind==='literature_search')return projection.file_id===null&&projection.analysis_run_id===null&&projection.is_current&&projection.dataset_source===undefined
  if(task.input_version.kind==='statistics_compute')return projection.analysis_run_id===null&&sameSource(task.input_version.source,projection.dataset_source)&&(task.input_version.source===null||task.input_version.source.file_id===projection.file_id)
  if(projection.material_versions?.some(v=>v.project_id!==task.project_id))return false
  if(task.input_version.kind==='report_collection')return projection.analysis_run_id===null&&isDatasetSource(projection.dataset_source)&&projection.dataset_source.kind==='prepared_dataset_version'&&projection.dataset_source.file_id===projection.file_id
  if(task.input_version.kind==='analysis_plan'&&task.input_version.source===null)return ['analysis_plan_v4','analysis_plan_v5'].includes(task.input_version.workflow_version)&&projection.file_id===null&&projection.analysis_run_id===null&&projection.dataset_source===undefined&&!!projection.material_versions?.length
  if (task.input_version.kind === 'ocr_review') return task.input_version.source.file_id === projection.file_id && projection.dataset_source === undefined
  return (task.input_version.kind === 'dataset_analysis' || task.input_version.kind === 'dataset_preparation' || task.input_version.kind === 'analysis_plan' || task.input_version.kind === 'analysis_recommendation') ? sameSource(task.input_version.source, projection.dataset_source) : projection.dataset_source === undefined
}
function source(value: unknown, parse = false, literature = false): value is TaskSource {
  return record(value) && (id(value.file_id)||literature&&value.file_id===null||parse&&value.file_id===null&&Array.isArray(value.material_versions)&&value.material_versions.length>0) && (!Object.hasOwn(value,'material_versions')||Array.isArray(value.material_versions)&&value.material_versions.every(v=>record(v)&&typeof v.project_id==='string'&&isEvidenceVersion(v,v.project_id))) && text(value.filename) && (parse ? value.analysis_run_id === null : id(value.analysis_run_id)) && typeof value.is_current === 'boolean' && (!('dataset_source' in value) || isDatasetSource(value.dataset_source) && value.dataset_source.file_id === value.file_id)
}
export function isTaskPage(value: unknown, projectId: string, page: number): value is TaskPage {
  return record(value) && value.project_id === projectId && value.page === page && value.page_size === 10
    && integer(value.total) && Array.isArray(value.items) && value.items.length <= 10 && value.items.length <= value.total
    && value.items.every(item => record(item) && isTask(item.task, projectId) && source(item.source, ['school_template_parse','statistics_compute','collection_word_report','parse_file', 'extract_dataset', 'prepare_dataset', 'analysis_plan', 'analysis_recommendation', 'review_ocr'].includes(item.task.task_type)||['journal_adaptation','journal_format_check','journal_recommendation','layout_docx','manuscript_writing','pdf_export','manuscript_draft','manuscript_docx','literature_search','literature_assistance'].includes(item.task.task_type),['journal_adaptation','journal_format_check','journal_recommendation','layout_docx','manuscript_writing','pdf_export','manuscript_draft','manuscript_docx','literature_search','literature_assistance'].includes(item.task.task_type)) && sourceMatchesTask(item.task, item.source))
    && new Set(value.items.map(item => item.task.id)).size === value.items.length
}
export function isTaskWait(value: unknown): value is TaskWait {
  return record(value) && id(value.id) && ['literature_model_authorization','literature_configuration','figure_projection_confirmation','ocr_review_confirmation', 'dataset_preparation_confirmation', 'analysis_plan_confirmation', 'analysis_plan_input', 'budget_confirmation', 'remote_observation', 'submission_unknown', 'unsupported_input', 'unsupported_confirmation'].includes(String(value.kind))
    && ['open', 'resolved', 'superseded'].includes(String(value.status)) && integer(value.task_revision, 1)
    && (record(value.input_version) && value.input_version.kind==='manuscript_writing' ? version(value.input_version,'manuscript_writing') : record(value.input_version) && value.input_version.kind==='literature_assistance' ? version(value.input_version,'literature_assistance') : record(value.input_version) && value.input_version.kind==='analysis_recommendation' ? version(value.input_version,'analysis_recommendation') : version(value.input_version, record(value.input_version)&&value.input_version.kind==='literature_search' ? 'literature_search' : value.kind === 'ocr_review_confirmation' ? 'review_ocr' : value.kind === 'dataset_preparation_confirmation' ? 'prepare_dataset' : (value.kind === 'analysis_plan_confirmation' || value.kind === 'analysis_plan_input') ? 'analysis_plan' : false)) && nullableText(value.reason_code) && nullableText(value.error_code)
    && date(value.created_at) && (value.resolved_at === null || date(value.resolved_at))
}
export function isWorkspace(value: unknown, projectId: string, taskId: string): value is TaskWorkspace {
  if (!record(value) || !isTask(value.task, projectId, taskId) || !source(value.source, ['school_template_parse','statistics_compute','collection_word_report','parse_file', 'extract_dataset', 'prepare_dataset', 'analysis_plan', 'analysis_recommendation', 'review_ocr'].includes(value.task.task_type)||['journal_adaptation','journal_format_check','journal_recommendation','layout_docx','manuscript_writing','pdf_export','manuscript_draft','manuscript_docx','literature_search','literature_assistance'].includes(value.task.task_type),['journal_adaptation','journal_format_check','journal_recommendation','layout_docx','manuscript_writing','pdf_export','manuscript_draft','manuscript_docx','literature_search','literature_assistance'].includes(value.task.task_type)) || !record(value.artifacts)
    || (value.wait !== null && !isTaskWait(value.wait)) || !Array.isArray(value.allowed_actions)
    || !value.allowed_actions.every(action => action === 'resume' || action === 'retry' || action === 'approve' || action === 'revise')
    || new Set(value.allowed_actions).size !== value.allowed_actions.length) return false
  if(value.verification_failure!==undefined){const failure=value.verification_failure;if(!record(failure)||failure.schema_version!==1||failure.status!=='mismatched'||!date(failure.recorded_at)||!Array.isArray(failure.differences)||failure.differences.length>100||!failure.differences.every(d=>record(d)&&text(d.path)&&d.path.length<=200&&['expected','actual','reason'].every(k=>d[k]===null||typeof d[k]==='boolean'||typeof d[k]==='number'&&Number.isFinite(d[k])||text(d[k])&&d[k].length<=500)))return false}
  if (value.task.origin === 'legacy' && (value.wait !== null || value.allowed_actions.length !== 0)) return false
  if (!sourceMatchesTask(value.task, value.source)) return false
  if (value.wait && !sameInputVersion(value.wait.input_version, value.task.input_version)) return false
  const { figure, explanation, report } = value.artifacts
  if(value.task.task_type==='journal_adaptation'||value.task.task_type==='journal_format_check'||value.task.task_type==='journal_recommendation')return value.wait===null&&figure===null&&explanation===null&&report===null&&value.artifacts.analysis==null&&value.artifacts.dataset==null&&value.allowed_actions.every(a=>a==='retry')&&(value.allowed_actions.length===0||value.task.status==='failed'&&value.source.is_current)
  if(value.task.task_type==='school_template_parse')return value.wait===null&&figure===null&&explanation===null&&report===null&&value.artifacts.analysis==null&&value.artifacts.dataset==null&&value.allowed_actions.every(a=>a==='retry')&&(value.allowed_actions.length===0||value.task.status==='failed'&&value.source.is_current)
  if(value.task.task_type==='manuscript_writing')return figure===null&&explanation===null&&report===null&&value.artifacts.analysis==null&&value.artifacts.dataset==null&&value.allowed_actions.every(a=>a==='retry'||a==='resume'&&record(value.wait)&&value.wait.kind==='budget_confirmation')&&(!value.wait||['budget_confirmation','unsupported_confirmation','remote_observation','submission_unknown'].includes(value.wait.kind))
  if(value.task.task_type==='layout_docx'){const input=value.task.input_version;return input.kind==='layout_docx'&&value.wait===null&&value.allowed_actions.length===0&&figure===null&&explanation===null&&value.artifacts.analysis==null&&value.artifacts.dataset==null&&(report===null||value.task.status==='succeeded'&&record(report)&&text(report.filename)&&report.download_url===`/api/v1/projects/${encodeURIComponent(projectId)}/layout-exports/${encodeURIComponent(input.export_id)}/download`)}
  if(value.task.task_type==='pdf_export'){const input=value.task.input_version;return input.kind==='pdf_export'&&value.wait===null&&value.allowed_actions.length===0&&figure===null&&explanation===null&&value.artifacts.analysis==null&&value.artifacts.dataset==null&&(report===null||value.task.status==='succeeded'&&record(report)&&text(report.filename)&&report.download_url===`/api/v1/projects/${encodeURIComponent(projectId)}/pdf-exports/${encodeURIComponent(input.export_id)}/download`)}
  if(value.task.task_type==='manuscript_draft'||value.task.task_type==='manuscript_docx'){
    const artifact=value.artifacts.manuscript,input=value.task.input_version
    if(input.kind!=='manuscript'||figure!==null||explanation!==null||value.wait!==null||!value.allowed_actions.every(a=>a==='retry')||value.artifacts.analysis!=null||value.artifacts.dataset!=null)return false
    if(artifact!=null&&(!record(artifact)||!id(artifact.id)||artifact.version_id!==input.manuscript_version_id||!integer(artifact.revision,1)||artifact.download_url!==null))return false
    if(value.task.task_type==='manuscript_draft')return report===null
    return report===null||record(report)&&text(report.filename)&&text(report.download_url)&&new RegExp(`^/api/v1/projects/${encodeURIComponent(projectId)}/manuscripts/[A-Za-z0-9_-]+/exports/[A-Za-z0-9_-]+/download$`).test(report.download_url)
  }
  if(value.task.task_type==='literature_assistance'){const advice=value.artifacts.literature_assistance;return (advice==null||record(advice)&&advice.kind===(value.task.input_version.kind==='literature_assistance'?value.task.input_version.assistance_kind:null)&&advice.real_calls_enabled===false&&(advice.result===null||value.task.status==='succeeded'&&validAssistanceResult(String(advice.kind),advice.result)))&&figure===null&&explanation===null&&report===null&&value.artifacts.analysis==null&&value.artifacts.dataset==null&&value.allowed_actions.every(a=>a==='retry'||a==='resume')&&(!value.wait||['literature_model_authorization','budget_confirmation','remote_observation','submission_unknown'].includes(value.wait.kind))&&(!value.wait||value.wait.kind!=='literature_model_authorization'||value.allowed_actions.length===0)}
  if(value.task.task_type==='literature_search'){const artifact=value.artifacts.literature;return figure===null&&explanation===null&&report===null&&value.artifacts.analysis==null&&value.artifacts.dataset==null&&value.allowed_actions.every(a=>a==='retry'||a==='resume')&&(!value.wait||value.wait.kind==='literature_configuration')&&(artifact==null||record(artifact)&&artifact.search_id===value.task.id&&integer(artifact.retrieved_count)&&artifact.retrieved_count<=100&&(artifact.matched_count===null||integer(artifact.matched_count)))}
  if(value.task.task_type==='statistics_compute'){
    const input=value.task.input_version
    if(input.kind!=='statistics_compute'||figure!==null||explanation!==null||report!==null||value.wait!==null||!value.allowed_actions.every(a=>a==='retry'))return false
    const analysis=value.artifacts.analysis
    if(analysis==null)return value.task.result_analysis_run_id==null
    const base=`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(value.source.file_id??'')}`
    return value.task.status==='succeeded'&&validStatisticsTaskResult(analysis,{base,revision:input.setup_revision,source:input.source??undefined,language:input.output_language},value.task.result_analysis_run_id??undefined)&&(analysis.analysis_context?.plan.id??null)===input.analysis_plan_id
  }
  if(value.task.task_type==='collection_word_report')return figure===null&&explanation===null&&value.allowed_actions.every(a=>a==='retry'||a==='resume')&&(report===null||record(report)&&text(report.filename)&&text(report.download_url)&&new RegExp(`^/api/v1/projects/${encodeURIComponent(projectId)}/report-collections/[A-Za-z0-9_-]+/reports/[A-Za-z0-9_-]+/download$`).test(report.download_url))
  if(value.task.task_type==='figure_projection')return figure===null&&explanation===null&&report===null&&(!value.wait||value.wait.kind==='figure_projection_confirmation')
  if (value.task.task_type === 'review_ocr') return figure === null && explanation === null && report === null && value.task.input_version.kind === 'ocr_review' && value.task.input_version.source.file_id === value.source.file_id && value.allowed_actions.every(action=>['retry','approve','revise'].includes(action)) && (!value.allowed_actions.some(a=>a==='approve'||a==='revise') || value.task.status==='waiting_confirmation' && value.wait?.status==='open' && value.wait.kind==='ocr_review_confirmation' && value.wait.task_revision===value.task.revision)
  if (value.task.task_type === 'prepare_dataset') return (!value.allowed_actions.some(a => a === 'approve' || a === 'revise') || value.task.status === 'waiting_confirmation' && value.wait?.status === 'open' && value.wait.kind === 'dataset_preparation_confirmation' && value.wait.task_revision === value.task.revision) && figure === null && explanation === null && report === null && value.allowed_actions.every(action => action === 'retry' || action === 'approve' || action === 'revise')
  if (value.task.task_type==='analysis_recommendation') return value.task.phase==='plan' && figure===null && explanation===null && report===null && value.allowed_actions.every(a=>a==='resume'||a==='retry')
  if (value.task.task_type === 'analysis_plan') {
    const inputWait = value.task.status === 'waiting_input' && value.task.input_version.kind === 'analysis_plan' && value.task.input_version.workflow_version !== 'analysis_plan_v1' && value.wait?.status === 'open' && value.wait.kind === 'analysis_plan_input' && value.wait.task_revision === value.task.revision
    const confirmationWait = value.task.status === 'waiting_confirmation' && value.wait?.status === 'open' && value.wait.kind === 'analysis_plan_confirmation' && value.wait.task_revision === value.task.revision
    return value.task.phase === 'plan' && figure === null && explanation === null && report === null
      && value.allowed_actions.every(action => action === 'retry' || action === 'approve' && confirmationWait || action === 'revise' && (inputWait || confirmationWait))
      && (value.wait?.kind !== 'analysis_plan_input' || inputWait && value.allowed_actions.every(action => action === 'revise'))
  }
  if (['parse_file', 'extract_dataset'].includes(value.task.task_type)) return value.wait === null && value.allowed_actions.every(action => action === 'retry') && figure === null && explanation === null && report === null
  if (value.task.origin === 'legacy' && (report !== null
    || (value.task.task_type === 'boxplot' ? explanation !== null : figure !== null))) return false
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(value.source.file_id??'')}/analysis-runs/${encodeURIComponent(value.source.analysis_run_id ?? '')}`
  return (figure === null || (record(figure) && text(figure.title) && text(figure.caption) && id(value.task.result_figure_id)
    && figure.download_url === (value.task.task_type==='figure_workbench'?`${base}/figure-workbench/figures/${encodeURIComponent(value.task.result_figure_id)}/package`:`${base}/figures/${encodeURIComponent(value.task.result_figure_id)}/download`)))
    && (report === null || (record(report) && text(report.filename) && id(value.task.result_report_id)
      && report.download_url === `${base}/report/${encodeURIComponent(value.task.result_report_id)}/download`))
    && (explanation === null || (record(explanation) && Array.isArray(explanation.sections)
      && explanation.sections.every(section => record(section) && text(section.key) && text(section.title) && text(section.text))
      && Array.isArray(explanation.limitations) && explanation.limitations.every(text)))
}
export function isEventPage(value: unknown, taskId: string, after: number): value is EventPage {
  if (!record(value) || value.task_id !== taskId || !Array.isArray(value.items) || value.items.length > 50
    || !integer(value.next_cursor, after) || typeof value.has_more !== 'boolean') return false
  let previous = after
  for (const event of value.items) {
    if (!record(event) || !integer(event.seq, previous + 1) || !integer(event.task_revision, 1)
      || !own(eventNames, event.event_type) || !own(statusNames, event.status) || !own(phaseNames, event.phase)
      || !nullableText(event.reason_code) || !date(event.created_at)
      || (event.error_code != null && !text(event.error_code))
      || (event.error_category != null && !errorCategories.some(category => category === event.error_category))
      || (event.retry_reason != null && !retryReasons.some(reason => reason === event.retry_reason))
      || !retryCount(event.retry_count)
      || (event.retry_delay_seconds != null && ![10, 30, 90].includes(event.retry_delay_seconds as number))) return false
    previous = event.seq
  }
  return value.next_cursor === previous && (!value.has_more || value.items.length > 0)
}
export function taskDisplayName(task: TaskView) {
  if(task.task_type==='journal_adaptation'&&task.status==='running')return '指南适配中'
  if(task.task_type==='journal_format_check'&&task.status==='running')return '格式检查中'
  // Waiting and terminal lifecycle states always take priority over a retained phase.
  return task.status === 'running' ? displayNames[task.display_status] : statusNames[task.status]
}
export function taskPhaseName(task: TaskView) {
  if(task.task_type==='journal_adaptation')return '期刊指南适配'
  if(task.task_type==='journal_format_check')return '期刊格式检查'
  if(task.task_type==='journal_recommendation')return '期刊建议'
  if(task.task_type==='literature_assistance')return '文献模型建议'
  if(task.task_type==='literature_search')return '检索资料'
  if(task.task_type==='statistics_compute')return '固定统计计算'
  if (task.task_type === 'review_ocr') return task.phase === 'verify' ? '生成核对版本' : '逐条核对'
  return task.task_type === 'prepare_dataset' && task.phase === 'plan' ? '整理预览' : phaseNames[task.phase]
}
