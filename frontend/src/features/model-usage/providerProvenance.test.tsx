import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import ProjectModelUsage from './ProjectModelUsage'
import TaskModelUsage from './TaskModelUsage'
import { reconciliationCall, reconciliationFixture } from './reconciliationFixtures'

beforeEach(() => { setApiSession('provenance-test'); setLocale('zh-CN') })
afterEach(() => { cleanup(); clearApiSession(); vi.unstubAllGlobals() })

for (const scope of ['project', 'task']) {
  const mount = () => render(scope === 'project' ? <ProjectModelUsage projectId="p1" /> : <TaskModelUsage taskId="t1" />)

  test(`${scope} labels synthetic amounts as offline demo usage and never as actual charges`, async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...reconciliationFixture,
      items: [{ ...reconciliationCall, provider_provenance: 'synthetic_fixture' }] })))
    mount()
    const row = (await screen.findByText('partial-model')).closest('tr')!
    expect(within(row).getByText('离线模拟回执')).toBeTruthy()
    expect(within(row).getByText('演示用量')).toBeTruthy()
    expect(within(row).getByText('本地账本演示，不代表实际付费。')).toBeTruthy()
    expect(within(row).queryByText('USD 0.000600')).toBeNull()
    expect(within(row).queryByText('部分已核对')).toBeNull()
    expect(screen.getByText('账本可能包含离线模拟回执；演示用量与预算占用不代表实际付费。')).toBeTruthy()
  })

  test(`${scope} distinguishes live unknown charges and preserves reservation messaging`, async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...reconciliationFixture,
      items: [{ ...reconciliationCall, model: 'live-model', provider_provenance: 'openai_live',
        status: 'submission_unknown', estimated_cost_micro_usd: null, usage_status: 'pending',
        reconciliation: { status: 'pending', token_micro_usd: null, tool_micro_usd: null,
          tool_applicable: false, actual_micro_usd: null, reconciled_at: null } }] })))
    mount()
    const row = (await screen.findByText('live-model')).closest('tr')!
    expect(within(row).getByText('真实供应商调用')).toBeTruthy()
    expect(within(row).getByText('实际费用未知')).toBeTruthy()
    expect(within(row).getByText('仍占预留额度，等待核对。')).toBeTruthy()
    expect(within(row).queryByText('USD 0.000000')).toBeNull()
    expect(within(row).queryByText('离线模拟回执')).toBeNull()
  })

  test(`${scope} keeps historical receipts readable without asserting live provenance`, async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(reconciliationFixture)))
    mount()
    const row = (await screen.findByText('partial-model')).closest('tr')!
    expect(within(row).getByText('历史记录：来源未标注')).toBeTruthy()
    expect(within(row).getByText('USD 0.000600')).toBeTruthy()
    expect(within(row).queryByText('真实供应商调用')).toBeNull()
  })

  test(`${scope} treats an explicitly unknown provenance as historical rather than live`, async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...reconciliationFixture,
      items: [{ ...reconciliationCall, provider_provenance: null }] })))
    mount()
    const row = (await screen.findByText('partial-model')).closest('tr')!
    expect(within(row).getByText('历史记录：来源未标注')).toBeTruthy()
    expect(within(row).queryByText('真实供应商调用')).toBeNull()
  })

  test(`${scope} preserves unknown failed charges while allowing a reconciled actual zero`, async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...reconciliationFixture, total: 2,
      items: [{ ...reconciliationCall, model: 'failed-live', provider_provenance: 'openai_live',
        status: 'failed', estimated_cost_micro_usd: null, usage_status: 'pending',
        reconciliation: { status: 'pending', token_micro_usd: null, tool_micro_usd: null,
          tool_applicable: false, actual_micro_usd: null, reconciled_at: null } },
      { ...reconciliationCall, id: 'zero-live', model: 'zero-live', provider_provenance: 'openai_live',
        reconciliation: { ...reconciliationCall.reconciliation, status: 'reconciled', token_micro_usd: 0,
          tool_micro_usd: null, tool_applicable: false, actual_micro_usd: 0 } }] })))
    mount()
    const failed = (await screen.findByText('failed-live')).closest('tr')!
    expect(within(failed).getByText('实际费用未知')).toBeTruthy()
    expect(within(failed).queryByText('USD 0.000000')).toBeNull()
    const zero = screen.getByText('zero-live').closest('tr')!
    expect(within(zero).getByText('USD 0.000000')).toBeTruthy()
    expect(within(zero).queryByText('实际费用未知')).toBeNull()
  })
}
