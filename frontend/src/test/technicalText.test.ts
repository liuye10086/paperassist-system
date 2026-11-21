import { afterEach, describe, expect, it } from 'vitest'
import { findTechnicalText } from './technicalText'

const uuid = '3f2b8c1e-9d4a-4f6b-8a2c-1e5d7f9a0b3c'
const sha256 = 'b4c5aa10906907938f6830b5ee517c5b2367515fefef8ff9a50c213a6486212c'
const hash = '18533238bb1daaa4a8600f1c'

function mount(html: string) {
  const root = document.createElement('div')
  root.innerHTML = html
  document.body.append(root)
  return root
}

const values = (root: Element, options?: Parameters<typeof findTechnicalText>[1]) =>
  findTechnicalText(root, options).map(item => [item.kind, item.value])

afterEach(() => { document.body.innerHTML = '' })

describe('findTechnicalText', () => {
  it('flags a system UUID shown as page text', () => {
    expect(findTechnicalText(mount(`<p>主张 ${uuid} · 版本 2</p>`))).toEqual([
      { kind: 'uuid', value: uuid, where: 'text' },
    ])
  })

  it('reports a UUID once even when its last segment looks like a hash', () => {
    const lettered = '3f2b8c1e-9d4a-4f6b-8a2c-ab5d7f9a0b3c'
    expect(values(mount(`<p>${lettered}</p>`))).toEqual([['uuid', lettered]])
  })

  it('flags full and shortened SHA-256 values', () => {
    const found = findTechnicalText(mount(`<p>原始 SHA: ${sha256}</p><small>SHA256 ${sha256.slice(0, 12)}…</small>`))
    expect(found.map(item => [item.kind, item.value])).toEqual([['hex', sha256], ['hex', sha256.slice(0, 12)]])
  })

  it('flags hashes joined to a prefix with a hyphen', () => {
    expect(values(mount(`<code>writing-v2-${hash}</code>`))).toEqual([['hex', hash]])
  })

  it('flags registered system IDs shown in full or cut to 8 or 12 characters', () => {
    const root = mount(`<p>来源 ${uuid.slice(0, 8)} 的固定比较</p><p>包 ${sha256.slice(0, 12)}</p><p>任务 ${uuid}</p>`)
    expect(values(root, { systemIds: [uuid, sha256] })).toEqual([
      ['system-id', uuid.slice(0, 8)], ['hex', sha256.slice(0, 12)], ['uuid', uuid],
    ])
  })

  it('flags raw snake_case status and error codes', () => {
    const found = findTechnicalText(mount('<p>needs_review</p><p>失败：research_source_not_found</p>'))
    expect(found.map(item => item.value)).toEqual(['needs_review', 'research_source_not_found'])
    expect(found.every(item => item.kind === 'internal-value')).toBe(true)
  })

  it('flags explicitly listed raw values as whole words', () => {
    const root = mount('<p>supported</p><p>unsupportedness</p>')
    expect(findTechnicalText(root, { rawValues: ['supported'] })).toEqual([
      { kind: 'internal-value', value: 'supported', where: 'text' },
    ])
  })

  it('flags storage paths and JSON text', () => {
    const found = findTechnicalText(mount('<small>正文 · word/document.xml</small><pre>{"model": "gpt", "limit": 3}</pre>'))
    expect(found.map(item => [item.kind, item.value])).toEqual([['path', 'word/document.xml'], ['json', '{"model":']])
  })

  it('flags absolute server and Windows paths', () => {
    const paths = ['/srv/paperassist/storage/abc.docx', '/work' + 'space/volumes/v_bac8/data/a.docx', '/var/lib/app/uploads',
      'D:/exports/a.docx', 'C:\\paperassist\\storage\\a.docx']
    const root = mount(paths.map(path => `<p>保存于 ${path}</p>`).join(''))
    expect(values(root)).toEqual(paths.map(path => ['path', path]))
  })

  it('flags request errors and developer symbols', () => {
    const root = mount("<p>[object Object]</p><p>TypeError: Failed to fetch</p><pre>{'detail': 'x'}</pre>")
    expect(values(root)).toEqual([['dev-symbol', '[object Object]'], ['dev-symbol', 'TypeError:'], ['json', "{'detail':"]])
  })

  it('checks accessible names, titles, placeholders, alt text, labels and button values', () => {
    const root = mount(`<button aria-label="查看 ${uuid}"></button><span title="${sha256}"></span>`
      + '<input placeholder="task_input_invalid"><img alt="figure_projection_invalid_group">'
      + '<select><optgroup label="group_a_title"><option label="option_b_label">选项</option></optgroup></select>'
      + '<input type="submit" value="submit_task_now"><div role="slider" aria-valuetext="step_two_value"></div>'
      + '<div aria-description="dev_description_text"></div>')
    expect(findTechnicalText(root).map(item => item.where)).toEqual([
      'aria-label', 'title', 'placeholder', 'alt', 'label', 'label', 'value', 'aria-valuetext', 'aria-description',
    ])
  })

  it('includes hidden views because users reach them by switching views', () => {
    expect(findTechnicalText(mount(`<div hidden><p>${uuid}</p></div>`))).toHaveLength(1)
  })

  it('reads adjacent text nodes as one string, as React renders {name}.{ext}', () => {
    const name = document.createElement('p')
    name.append('sample_data', '.', 'xlsx')
    const id = document.createElement('p')
    id.append(uuid.slice(0, 18), uuid.slice(18))
    const root = mount('')
    root.append(name, id)
    expect(values(root)).toEqual([['uuid', uuid]])
  })

  it('flags system values in read-only or disabled fields', () => {
    const root = mount(`<input readonly value="${uuid}"><textarea disabled>${sha256}</textarea>`)
    expect(findTechnicalText(root).map(item => [item.kind, item.where])).toEqual([['uuid', 'value'], ['hex', 'value']])
  })

  it('accepts what the user typed into editable fields', () => {
    const root = mount(`<textarea>${sha256}</textarea>`)
    const input = document.createElement('input')
    input.value = `用户粘贴的 ${uuid}`
    root.append(input)
    expect(findTechnicalText(root)).toEqual([])
  })

  it('accepts business wording, file names, DOI, URLs, e-mail addresses, doses and fractions', () => {
    const root = mount([
      '<h1>讨论第 2 段还缺一条文献依据。</h1>',
      '<p>第 3 版 · 2026-11-18 14:20 · 当前</p>',
      '<p>sample_data_v2.xlsx · 172,111 字节</p>',
      '<p>raw_counts (1).csv · raw_counts(1).csv</p>',
      '<p>DOI 10.1038/s41586-020-2649-2 · PMID 38012345</p>',
      '<a>https://pubmed.ncbi.nlm.nih.gov/38012345/</a>',
      '<a>https://example.org/search?term=x&amp;sort_by=date</a>',
      '<a>https://x.org/a#section_2</a>',
      `<a>https://github.com/o/r/commit/${hash}</a>`,
      '<p>zhang_san@example.com</p>',
      '<p>剂量 1/2.5mg · 5 mg /kg/d · 2026/11/18</p>',
      '<p>Version 2 · Supported by the cited abstract.</p>',
      '<p>Error handling is described in the methods.</p>',
    ].join(''))
    expect(findTechnicalText(root)).toEqual([])
  })

  it('keeps user variable names, sample IDs and citation keys marked as user content (DESIGN.md 9.1)', () => {
    const root = mount('<table><tr><th data-user-content>sample_id</th><th data-user-content>age_group</th></tr></table>'
      + '<p>分组变量 <span data-user-content>bmi_baseline</span> · 引用键 <cite class="key">smith_2020</cite></p>'
      + '<p>样本 20261118ab0001 · serum_boxplot</p>')
    expect(findTechnicalText(root, { exclude: 'cite.key', allowValues: ['20261118ab0001', 'serum_boxplot'] })).toEqual([])
    expect(values(root)).toEqual([['internal-value', 'smith_2020'], ['hex', '20261118ab0001'], ['internal-value', 'serum_boxplot']])
  })

  it('exempts the whole user-content subtree, and elsewhere only the listed values', () => {
    const root = mount('<div data-user-content title="sample_id"><p>age_group</p></div>'
      + '<p title="needs_review">age_group · task_input_invalid</p>')
    expect(findTechnicalText(root, { allowValues: ['age_group'] })).toEqual([
      { kind: 'internal-value', value: 'task_input_invalid', where: 'text' },
      { kind: 'internal-value', value: 'needs_review', where: 'title' },
    ])
  })
})
