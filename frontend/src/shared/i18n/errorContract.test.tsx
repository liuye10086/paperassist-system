import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { useState } from 'react'
import { apiError, safeError, setLocale, translate, useI18n } from './index'
import { errorMessages } from './errorMessages'

const fallback = '请求失败，请重试。'

it.each([
  ['selected_reference_excluded', '已排除', 'excluded'],
  ['selected_reference_metadata_incomplete', '书目', 'bibliographic'],
  ['selected_reference_quote_invalid', '摘要原文', 'abstract'],
])('identifies the selected PubMed reference and explains %s in both languages', (code, zh, en) => {
  const id = apiError({ detail: { code, params: { position: 2 } } }, fallback)
  setLocale('zh-CN')
  expect(translate(id)).toContain(zh)
  expect(translate(id)).toContain('2')
  setLocale('en')
  expect(translate(id)).toContain(en)
  expect(translate(id)).toContain('2')
})

afterEach(() => { cleanup(); setLocale('zh-CN') })

it.each(Object.keys(errorMessages))('retains the safe %s identifier and translates it at render time', code => {
  const requiredParams: Record<string, Record<string, string | number>> = {
    file_too_large: { max_bytes: 1048576 },
    numeric_precision: { column: 'A', row: 2 },
    plot_label_too_long: { max_chars: 200 },
    // Codes whose message has a placeholder must list it here, or the text keeps "{position}".
    thesis_chapter_protected: { position: 3 },
    manuscript_review_heading_language: { position: 2 },
    manuscript_finding_figure_reference: { position: 1 },
    selected_reference_excluded: { position: 2 },
    selected_reference_metadata_incomplete: { position: 2 },
    selected_reference_quote_invalid: { position: 2 },
    selected_reference_abstract_unusable: { position: 2, pmid: 990000002 },
    selected_reference_abstract_limit: { position: 2, pmid: 990000002 },
  }
  const id = apiError({ detail: { code, message: 'PRIVATE TRACE', params: { ...requiredParams[code], reason: 'PRIVATE TRACE', secret: 'PRIVATE TRACE' } } }, fallback)
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

it.each([
  ['manuscript_exists', '这个项目已经有稿件。请覆盖之前的写作材料。', /already has a manuscript/],
  ['paper_materials_unavailable', '图表资料只适用于 SCI 论文和毕业论文项目。', /only to SCI manuscript and thesis projects/],
  ['thesis_requirements_changed', '毕业论文需求或学校资料已更新，请核对后继续。', /have changed\. Review/],
  ['thesis_requirements_unavailable', '毕业论文需求只适用于毕业论文项目。', /only to thesis projects/],
  ['thesis_template_changed', '学校模板绑定已变化，请核对当前模板和章节。', /school template binding has changed\. Review the current template and chapters\./i],
  ['thesis_template_required', '请先确认并绑定可用的学校模板。', /confirm and bind an available school template first\./i],
  ['analysis_quality_required', '请先完成本次分析所用数据的质量控制。', /complete quality control for the data used in this analysis first\./i],
  ['customer_sample_information_read_only', '样本分组和样本信息由客户填写。需要更正时，请向客户请求补充资料。', /customer provides sample groups and sample details/i],
  ['sci_settings_unavailable', 'SCI 建项资料仅适用于 SCI 论文项目。', /only to SCI manuscript projects/],
  ['project_assignment_type_invalid', '论文项目仅可撤回已有分配。', /can only be revoked/],
] as const)('gives readable %s text in both languages', (code, zh, en) => {
  const id = apiError({ detail: { code, message: 'PRIVATE TRACE' } }, fallback)
  expect(translate(id)).toBe(zh)
  setLocale('en')
  expect(translate(id)).toMatch(en)
  expect(translate(id)).not.toMatch(/\b(revision|id|sha|internal|PRIVATE)\b/i)
})
