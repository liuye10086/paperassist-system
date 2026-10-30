import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { useState } from 'react'
import { apiError, safeError, setLocale, translate, useI18n } from './index'

const missingCodes = `
figure_language_invalid_image figure_language_not_found figure_language_unsupported
journal_adaptation_invalid journal_adaptation_no_changes journal_adaptation_preview_conflict
literature_citation_conflict manuscript_not_found manuscript_review_blocked
manuscript_review_input_invalid manuscript_review_not_found manuscript_revision_conflict
manuscript_writing_input_limit manuscript_writing_language_invalid manuscript_writing_language_required
manuscript_writing_material_blocked manuscript_writing_review_invalid manuscript_writing_review_required
manuscript_writing_selection_invalid numeric_resource_limit school_change_blocked school_change_invalid
school_change_preview_conflict school_export_input_invalid storage_deletion_idempotency_conflict
storage_deletion_identity_changed storage_deletion_input_invalid storage_deletion_io_failed
storage_deletion_pending storage_deletion_scope_unknown storage_policy_invalid storage_reservation_conflict
literature_pmc_not_authorized review_continuation_invalid review_document_export_not_found
review_document_export_not_ready review_document_not_found review_progress_correction_conflict
review_progress_invalid review_return_blocked review_return_invalid review_return_preview_conflict
review_revision_not_ready
`.trim().split(/\s+/)
const fallback = '请求失败，请重试。'

afterEach(() => { cleanup(); setLocale('zh-CN') })

it.each(missingCodes)('retains the safe %s identifier and translates it at render time', code => {
  const id = apiError({ detail: { code, message: 'PRIVATE TRACE', params: { reason: 'PRIVATE TRACE', secret: 'PRIVATE TRACE' } } }, fallback)
  expect(id).toContain('PA_ERROR:')
  expect(id).toContain(`"code":"${code}"`)
  expect(safeError(new Error(id), fallback)).toBe(id)
  expect(id).not.toContain('PRIVATE TRACE')
  const zh = translate(id)
  expect(zh).not.toBe(translate(fallback))
  expect(zh).toMatch(/[\u3400-\u9fff]/)
  setLocale('en')
  const en = translate(id)
  expect(en).not.toBe(translate(fallback))
  expect(en).not.toMatch(/[\u3400-\u9fff]/)
  expect(en).not.toBe(zh)
  expect(en).not.toContain('PRIVATE TRACE')
  setLocale('zh-CN')
  expect(translate(id)).toBe(zh)
})

it('updates a mounted error while retaining an edited draft and original task', () => {
  const task = { id: 'original-task', status: 'failed', error_code: 'review_return_blocked' }
  const id = apiError({ detail: { code: task.error_code, message: 'PRIVATE TRACE' } }, fallback)
  function View() {
    const { t } = useI18n()
    const [error] = useState(id)
    const [currentTask] = useState(task)
    const [draft, setDraft] = useState('原稿')
    return <><input value={draft} onChange={event => setDraft(event.target.value)} /><p role="alert">{t(error)}</p><output>{currentTask.id}:{currentTask.status}:{currentTask.error_code}</output></>
  }
  render(<View />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '未保存研究稿' } })
  const before = screen.getByRole('alert').textContent
  act(() => setLocale('en'))
  expect(screen.getByRole('alert').textContent).not.toBe(before)
  expect(screen.getByRole('alert').textContent).not.toContain('PRIVATE TRACE')
  expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('未保存研究稿')
  expect(screen.getByRole('status').textContent).toBe('original-task:failed:review_return_blocked')
  expect(task).toEqual({ id: 'original-task', status: 'failed', error_code: 'review_return_blocked' })
})

it('uses a local fallback for unknown codes and untrusted exception text', () => {
  for (const code of ['unlisted_code', '__proto__', 'constructor']) {
    expect(apiError({ detail: { code, message: 'PRIVATE TRACE' } }, fallback)).toBe(fallback)
  }
  expect(safeError(new Error('PRIVATE TRACE'), fallback)).toBe(fallback)
})

it.each([
  ['zh-CN', ['v2', '候选', '精确文本科学审核', '全文语言审核', '受控写作工作区']],
  ['en', ['v2', 'candidate', 'exact-text scientific review', 'full-text language review', 'controlled writing workspace']],
] as const)('explains both v2 candidate readiness and required publication reviews in %s', (locale, required) => {
  // live_review.raw rejects an unready candidate; service.publish also rejects a
  // succeeded v2 candidate without review_request. One code must guide both cases.
  const id = apiError({ detail: {
    code: 'manuscript_writing_review_required',
    message: 'v2候选必须完成精确文本科学审核和全文语言审核后才能发布。 PRIVATE TRACE',
  } }, fallback)
  setLocale(locale)
  const text = translate(id)
  for (const meaning of required) expect(text).toContain(meaning)
  expect(text).not.toContain('PRIVATE TRACE')
})

it.each([
  ['zh-CN', ['导出输入', '排版配置', '启用目录', '正文入口']],
  ['en', ['export input', 'layout configuration', 'table of contents', 'enabled', 'body section']],
] as const)('explains invalid school export input and the enabled-contents body requirement in %s', (locale, required) => {
  // school_docx already has a plan when enabled contents cannot find an eligible
  // body entry. manuscript_docx and school_export also use this code for input.
  const id = apiError({ detail: {
    code: 'school_export_input_invalid',
    message: '当前章节没有可放置目录的正文入口。 PRIVATE TRACE',
  } }, fallback)
  setLocale(locale)
  const text = translate(id)
  for (const meaning of required) expect(text).toContain(meaning)
  expect(text).not.toContain('PRIVATE TRACE')
  expect(text).not.toMatch(/导出缺少固定排版配置|is missing its saved layout configuration/)
})
