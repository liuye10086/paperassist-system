import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { apiError, setLocale, translate } from '../../shared/i18n'
import { issueDescription } from '../analysisPlan/diagnostics'
import { isPlanCheck } from '../analysisPlan/analysisPlanApi'
import TaskDetail from './TaskDetail'
import { eventsFixture, usageFixture, workspaceFixture } from './taskFixtures'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })

// Independent user-facing expectations, not the production message catalog.
const failures = [
  ['numeric_descriptive_limit', /100,000.*值/, /100,000.*values/, /重新.*确认/, /confirm/i],
  ['numeric_row_limit', /10,000.*行/, /10,000.*rows/, /重新.*确认/, /confirm/i],
  ['numeric_effect_limit', /20.*展开/, /20.*expanded/, /协变量.*编码/, /covariate.*encoding/i],
  ['numeric_input_bytes_limit', /8 MiB/, /8 MiB/, /字段.*编码/, /fields.*encodings/i],
  ['numeric_output_limit', /16 MiB/, /16 MiB/, /管理员/, /administrator/i],
  ['numeric_output_missing', /未生成.*输出/, /output.*missing/i, /管理员/, /administrator/i],
  ['numeric_output_invalid', /输出.*损坏|输出.*无效/, /output.*invalid|output.*corrupt/i, /管理员/, /administrator/i],
  ['numeric_timeout_invalid', /超时配置.*无效/, /timeout configuration.*invalid/i, /管理员/, /administrator/i],
  ['numeric_timeout', /30 秒/, /30.second/i, /原任务/, /original task/i],
  ['numeric_failure', /进程.*异常/, /process.*unexpected/i, /管理员/, /administrator/i],
] as const

it.each(failures)('translates %s with the actual reason and safe next action', (code, zh, en, actionZh, actionEn) => {
  for (const locale of ['zh-CN', 'en'] as const) {
    setLocale(locale)
    const displayed = translate(apiError({ code, message: 'private-marker', params: { reason: 'private-marker' } }, 'fallback'))
    expect(displayed).toMatch(locale === 'en' ? en : zh)
    expect(displayed).toMatch(locale === 'en' ? actionEn : actionZh)
    expect(displayed).not.toContain('private-marker')
    if (code !== 'numeric_row_limit') expect(displayed).not.toMatch(/10,000|8 个协变量|8 covariates/)
    if (['numeric_output_missing', 'numeric_output_invalid', 'numeric_timeout_invalid', 'numeric_failure'].includes(code)) {
      expect(displayed).not.toMatch(/删.*行|reduce.*rows|remove.*rows/i)
    }
    expect(translate(issueDescription(code, 'private-marker'))).toBe(displayed)
    expect(isPlanCheck({ rules_version: 'analysis_plan_rules_v3', research_missing: [], data_range: 'A2:A3',
      row_count: 2, selected_fields: [], selection_check: null, limitations: [],
      issues: [{ id: code, code, severity: 'blocking', field: null, count: 1, coordinates: [], message: 'private-marker', allowed_resolutions: [] }] })).toBe(true)
  }
})

it('keeps legacy limit readable without inventing the historic failure reason', () => {
  for (const locale of ['zh-CN', 'en'] as const) {
    setLocale(locale)
    const displayed = translate(apiError({ code: 'numeric_input_limit' }, 'fallback'))
    expect(displayed).toMatch(locale === 'en' ? /specific limit.*not recorded/i : /未记录具体.*限制/)
    expect(displayed).not.toMatch(/10,000|100,000|8 MiB|16 MiB|8 个协变量|8 covariates/)
    expect(translate(issueDescription('numeric_input_limit', 'private-marker'))).toBe(displayed)
  }
})

it.each([
  ['correlation_input_limit', /10,000/, /10,000/],
  ['correlation_sample_size', /3.*完整/, /3 complete/],
  ['correlation_constant', /没有变化/, /constant/i],
  ['correlation_near_constant', /变化过小/, /too little variation/i],
  ['correlation_invalid_input', /相关字段/, /correlation fields/i],
  ['comparison_input_limit', /10,000/, /10,000/],
  ['comparison_sample_size', /Kruskal/, /Kruskal/],
  ['comparison_constant', /没有足够变化/, /insufficient variation/i],
  ['comparison_near_constant', /变化过小/, /too little variation/i],
  ['comparison_invalid_input', /比较字段/, /comparison fields/i],
  ['group_not_selected', /未选组/, /unselected groups/i],
  ['groups_missing', /参与组/, /participating groups/i],
  ['group_type', /分组字段/, /grouping field/i],
  ['numeric_type', /实际数值/, /numeric values/i],
  ['pair_id_missing', /配对 ID/, /pair IDs/i],
  ['pair_id_duplicate', /配对 ID/, /pair IDs/i],
  ['pair_id_type', /配对 ID/, /pair IDs/i],
  ['unit_conflict', /单位/, /units/i],
  ['recommendation_not_configured', /分析建议/, /recommendation/i],
  ['recommendation_invalid', /分析建议/, /recommendation/i],
  ['projection_limit', /投影/, /projection/i],
  ['violin_unsupported_group', /小提琴图/, /violin/i],
  ['task_uncertain', /不能重新发送/, /do not resend/i],
] as const)('keeps existing public code %s actionable instead of falling back to a generic error', (code, zh, en) => {
  for (const locale of ['zh-CN', 'en'] as const) {
    setLocale(locale)
    const displayed = translate(apiError({ code, message: 'private-marker' }, 'fallback'))
    expect(displayed).toMatch(locale === 'en' ? en : zh)
    expect(displayed).not.toContain('private-marker')
  }
})

it.each([
  ['task_source_conflict', /冻结.*来源/, /frozen.*source/i, /新.*确认|重新.*确认/, /confirm/i],
  ['plot_result_mismatch', /核对/, /verification/i, /差异/, /differences/i],
  ['explanation_invalid', /事实核验/, /fact verification/i, /来源/, /source/i],
  ['model_submission_unknown', /未知/, /unknown/i, /不能重新发送/, /do not resend/i],
  ['model_budget_exceeded', /预算不足/, /budget.*insufficient/i, /原任务/, /original task/i],
] as const)('shows %s guidance in the real task without creating a resend control', async (code, zh, en, actionZh, actionEn) => {
  const workspace = { ...workspaceFixture, task: { ...workspaceFixture.task, status: 'failed', display_status: 'failed', error_code: code }, wait: null, allowed_actions: [] }
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => Response.json(url.endsWith('/workspace') ? workspace : url.includes('/events') ? eventsFixture : usageFixture))
  vi.stubGlobal('fetch', fetch)
  render(<TaskDetail projectId="p1" taskId="t1" onChanged={() => {}} />)
  await screen.findByText('执行失败', { selector: '.task-status' })
  for (const locale of ['zh-CN', 'en'] as const) {
    act(() => setLocale(locale))
    const region = screen.getByRole('region', { name: locale === 'en' ? 'Task details' : '任务详情' })
    const warning = region.querySelector('.warning-panel')!
    expect(warning.textContent).toMatch(locale === 'en' ? en : zh)
    expect(warning.textContent).toMatch(locale === 'en' ? actionEn : actionZh)
    expect(within(region).queryByRole('button', { name: /重试原任务|继续原任务|retry|resume|continue/i })).toBeNull()
  }
  expect(fetch.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')).toHaveLength(0)
})

it('keeps unknown submission read only even if a stale action is returned', async () => {
  const workspace = { ...workspaceFixture, task: { ...workspaceFixture.task, error_code: 'model_submission_unknown' },
    wait: { ...workspaceFixture.wait, kind: 'submission_unknown', error_code: 'model_submission_unknown' }, allowed_actions: ['resume', 'retry'] }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.endsWith('/workspace') ? workspace : url.includes('/events') ? eventsFixture : usageFixture)))
  render(<TaskDetail projectId="p1" taskId="t1" onChanged={() => {}} />)
  await screen.findByText('提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。')
  for (const locale of ['zh-CN', 'en'] as const) {
    act(() => setLocale(locale))
    const actions = screen.getByRole('region', { name: locale === 'en' ? 'Task actions' : '任务处理' })
    expect(within(actions).queryAllByRole('button')).toHaveLength(0)
  }
})
