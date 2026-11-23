import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import CustomerMaterials, { ThesisMaterialOrganizer } from './CustomerMaterials'

afterEach(() => { cleanup(); clearApiSession(); vi.unstubAllGlobals() })

it('places thesis figures in a bound school chapter without requiring a caption and keeps ordinary files optional', async () => {
  setApiSession('csrf', 'customer-test')
  const chapter = { id: 'thesis:results:confirmed:design', label: '第二章 研究设计' }
  let chapterLabel = chapter.label
  const writes: Record<string, unknown>[] = []
  const pick = vi.fn(), organize = vi.fn(), upload = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/files?')) return Response.json({ total: 5, items: [
      { id: 'img', filename: '流程.png', file_type: 'png', parse_status: 'stored' },
      { id: 'doc', filename: '记录.docx', file_type: 'docx', parse_status: 'parsed' },
      { id: 'school', filename: '学校格式.docx', file_type: 'docx', parse_status: 'parsed' },
      { id: 'book', filename: '结果.xlsx', file_type: 'xlsx', parse_status: 'parsed' },
      { id: 'newBook', filename: '数据.xlsx', file_type: 'xlsx', parse_status: 'parsed' },
    ] })
    if (url.includes('/paper-materials?')) return Response.json({ items: [
      {id:'note',file_id:'book',revision:1,target_id:'results',target_label:'研究结果',target_available:true,
        result:'已核对结果。',worksheet_names:['汇总']},
    ], targets: [{id:'results',label:'研究结果'}], figure_targets: [{...chapter,label:chapterLabel}], template_source_file_ids: ['school'] })
    if (url.includes('/paper-materials/worksheets/')) return Response.json({sheets:[
      {name:'汇总',columns:['计数'],preview_rows:[['5']],row_count:1,values_ready:true},
    ]})
    if (url.includes('/paper-materials/') && init?.method === 'PUT') {
      writes.push(JSON.parse(String(init.body)))
      return Response.json({})
    }
    return Response.json({ items: [], total: 0 })
  }))
  const guard = () => () => {}
  const uploadStep = render(<CustomerMaterials projectId="p1" forWriting="thesis" onContinue={organize} onUnavailable={vi.fn()}
    registerLeaveGuard={guard} onAnalysisResults={pick} />)
  await screen.findByText('流程.png')
  fireEvent.click(screen.getByRole('button', { name: '从我的分析项目取用成果' }))
  expect(pick).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', { name: '设置配图' })).toBeNull()
  expect(screen.queryByRole('button', { name: '添加说明' })).toBeNull()
  expect(screen.queryByRole('button', { name: /编辑.*图表资料/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '下一步 模板与资料整理' }))
  expect(organize).toHaveBeenCalledOnce()
  uploadStep.unmount()
  const organizer = render(<ThesisMaterialOrganizer projectId="p1" registerLeaveGuard={guard} onUpload={upload} chapterRevision={0}/>)
  const figure = within((await screen.findByText('流程.png')).closest('li')!)
  const edit = figure.getByRole('button', { name: '设置配图' })
  await waitFor(() => expect(edit).toHaveProperty('disabled', false))
  const template = within(screen.getByText('学校格式.docx').closest('li')!)
  expect(template.getByText(/学校模板/)).toBeTruthy()
  expect(template.queryByRole('button', { name: '添加说明' })).toBeNull()
  expect(figure.getByText(/自动安排/)).toBeTruthy()
  expect(screen.queryByRole('heading', {level:1})).toBeNull()
  expect(document.querySelector('input[type=file]')).toBeNull()
  expect(screen.queryByRole('button', {name:/下一步|从我的分析项目取用成果/})).toBeNull()
  fireEvent.click(edit)
  const select = figure.getByRole('combobox', { name: '入稿章节' })
  expect(select).toHaveProperty('value', '')
  const caption = figure.getByRole('textbox', { name: '图注与出处（选填）' })
  fireEvent.change(caption, {target:{value:'尚未保存的说明'}})
  chapterLabel = '第三章 实验方法'
  organizer.rerender(<ThesisMaterialOrganizer projectId="p1" registerLeaveGuard={guard} onUpload={upload} chapterRevision={1}/>)
  await figure.findByRole('option',{name:chapterLabel})
  expect(caption).toHaveProperty('value','尚未保存的说明')
  fireEvent.change(caption, {target:{value:''}})
  fireEvent.change(select, { target: { value: chapter.id } })
  fireEvent.click(figure.getByRole('button', { name: '保存配图设置' }))
  await waitFor(() => expect(writes).toEqual([{ expected_revision: 0, result: '', file_id: 'img', target_id: chapter.id }]))
  const doc = within(screen.getByText('记录.docx').closest('li')!)
  fireEvent.click(doc.getByRole('button', { name: '添加说明' }))
  expect(doc.getByRole('textbox', { name: '文件说明（选填）' })).toBeTruthy()
  expect(doc.queryByRole('combobox')).toBeNull()
  fireEvent.click(doc.getByRole('button', { name: '取消' }))
  fireEvent.click(screen.getByRole('button', {name:'编辑 结果.xlsx 的图表资料'}))
  expect(await screen.findByRole('checkbox', {name:'汇总'})).toHaveProperty('checked',true)
  expect(screen.getByRole('textbox', {name:'主要结果'})).toHaveProperty('value','已核对结果。')
  fireEvent.click(screen.getByRole('button', {name:'返回项目文件'}))
  const newBook = within(screen.getByText('数据.xlsx').closest('li')!)
  expect(newBook.getByRole('button', {name:'添加说明'})).toBeTruthy()
  fireEvent.click(newBook.getByRole('button', {name:'入稿工作表'}))
  expect(await screen.findByRole('checkbox', {name:'汇总'})).toBeTruthy()
  fireEvent.click(screen.getByRole('button', {name:'返回项目文件'}))
  fireEvent.click(screen.getByRole('button', { name: '返回上传资料' }))
  expect(upload).toHaveBeenCalledOnce()
})
