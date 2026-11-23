import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { taskFixture } from '../tasks/taskFixtures'
import ReviewsWorkspace from '../reviews/ReviewsWorkspace'
const projectId = 'paper-review'
const base = '/api/v1/projects/' + projectId
const reviews = base + '/reviews'
const sourceId = 'f2a6939b-b706-4037-b294-68b106ebd602'
const task = {
  ...taskFixture, id: 'review-task', project_id: projectId, task_type: 'review_round_plan', phase: 'verify', status: 'succeeded',
  display_status: 'succeeded', error_code: null, reason_code: null,
  input_version: { kind: 'review_round_plan', round_id: 'round1', base_version_id: 'v1', workflow_version: 'review_round_plan_v1' },
}
const opinion = (number: number, needs: { kind: string; description: string }[]) => ({
  id: `${sourceId}:${number}`, source_id: sourceId, number, original_number: String(number), original_text: '意见原文 ' + number,
  source_location: null, revision: 1, status: 'waiting_material', uncompleted_reason: '', decision: null, category: 'method',
  locations: [], translation: null, plan: '', evidence_ids: [], needs, flags: [], conflicting_item_ids: [],
  proposed_action: 'modify', not_adopt_reason: '',
})
const analysisItem = opinion(1, [{ kind: 'analysis', description: '补充生存分析' }, { kind: 'literature', description: '补充文献' }])
const materialItem = opinion(2, [{ kind: 'material', description: '补充原始记录' }])
const round = {
  id: 'round1', project_id: projectId, title: '一审意见', project_type: 'thesis', round_number: 1, revision: 1, synthetic: false,
  manuscript: { id: 'm1', revision: 1, version_id: 'v1', title: '送审稿' },
  sources: [{ id: sourceId, role: 'advisor', label: '导师 1', format: 'text', original_text: '原文', segments: [], warnings: [] }],
  items: [analysisItem, materialItem], materials: [], constraints: { school_confirmation_id: null, journal_target_id: null },
  versions: [], decisions: [], task, wait: null, created_at: task.created_at, real_model_calls: false, real_network_calls: false,
}
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('keeps the operator labels and buttons unchanged', async () => {
  const operatorRound = {...round, project_type: 'sci', sources: [{...round.sources[0], role: 'reviewer', label: '审稿人 1'}]}
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === reviews + '/inputs') return Response.json({ project_type: 'sci', manuscripts: [], documents: [], journal_targets: [], school_confirmations: [] })
    if (url === reviews + '/rounds') return Response.json({ items: [operatorRound] })
    if (url === reviews + '/rounds/round1') return Response.json(operatorRound)
    return Response.json({ items: [] })
  }))
  render(<ReviewsWorkspace projectId={projectId} projectType="sci" active view="items" roundId="round1"
    onSelectRound={vi.fn()} onOpenTask={vi.fn()} />)
  const rows = await screen.findAllByRole('button', { name: /审稿人 1/ })
  expect(rows.map(row => row.querySelector('small')?.textContent)).toEqual(['待补材料', '待补材料'])
  expect(screen.queryByText('等分析结果')).toBeNull()
})
