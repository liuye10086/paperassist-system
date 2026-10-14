import { expect, it } from 'vitest'
import { isTask, isWorkspace } from './taskTypes'
import { taskFixture, workspaceFixture } from './taskFixtures'
it('accepts local structure extraction without analysis artifacts', () => {
 const task = { ...taskFixture, task_type: 'extract_dataset', phase: 'parse', input_version: { kind: 'excel_structure', structure_id: 's1', source_sha256: 'a'.repeat(64), parser_version: 'openpyxl-3.1.5-structure-v1' } }
 expect(isTask(task, 'p1')).toBe(true)
 expect(isWorkspace({ ...workspaceFixture, task, source: { ...workspaceFixture.source, analysis_run_id: null }, wait: null, artifacts: { figure: null, explanation: null, report: null }, allowed_actions: ['retry'] }, 'p1', task.id)).toBe(true)
 expect(isTask({ ...task, input_version: { ...task.input_version, setup_revision: 1 } }, 'p1')).toBe(false)
})
it('rejects preparation input on analysis tasks and requires current open confirmation for preparation actions', () => {
 const source = { kind: 'dataset_version', schema_version: 1, dataset_id: 'd1', structure_id: 's1', dataset_version: 1, file_id: 'f1', source_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), dataset_size_bytes: 100, dataset_schema_version: 1, sheet_index: 0, sheet_name: 'Sheet1', parser_version: 'structure-v1' }
 const input_version = { kind: 'dataset_preparation', source, workflow_version: 'dataset_preparation_v1' }
 const task = { ...taskFixture, task_type: 'prepare_dataset', phase: 'plan', input_version }
 expect(isTask({ ...task, task_type: 'boxplot' }, 'p1')).toBe(false)
 const workspace = { ...workspaceFixture, task, source: { ...workspaceFixture.source, analysis_run_id: null, dataset_source: source }, wait: { ...workspaceFixture.wait, kind: 'dataset_preparation_confirmation', input_version }, artifacts: { figure: null, explanation: null, report: null }, allowed_actions: ['approve', 'revise'] }
 expect(isWorkspace(workspace, 'p1', task.id)).toBe(true)
 expect(isWorkspace({ ...workspace, wait: null }, 'p1', task.id)).toBe(false)
})
