import { taskFixture } from '../tasks/taskFixtures'
// Synthetic task: no real NCBI data or external calls.
export const literatureTask = { ...taskFixture, id: 'search1', task_type: 'literature_search', phase: 'search', reason_code: 'ncbi_not_configured', error_code: null,
 input_version: { kind: 'literature_search', workflow_version: 'literature_search_v1', search_id: 'search1', input_digest: 'a'.repeat(64), output_language: 'zh-CN' } }
export const literatureWorkspace = { task: literatureTask, source: { file_id: null, filename: 'Synthetic topic', analysis_run_id: null, is_current: true },
 wait: { id: 'w1', kind: 'literature_configuration', status: 'open', task_revision: 3, input_version: literatureTask.input_version, reason_code: 'ncbi_not_configured', error_code: null, created_at: literatureTask.updated_at, resolved_at: null },
 allowed_actions: [], artifacts: { figure: null, explanation: null, report: null, literature: { search_id: 'search1', retrieved_count: 0, matched_count: null } } }
