import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import CustomerSciResources from './CustomerSciResources'

const path = '/api/v1/projects/p1/sci-resources'
const chapters = [{id:'results', label:'结果'}, {id:'discussion', label:'讨论'}]
const figures = ['主图甲', '主图乙', '主图丙'].map((title, i) => ({
  id:`f${i + 1}`, title, preview_url:`/api/v1/projects/p1/sci-figures/f${i + 1}/members/png/download`, revision:1,
}))
type Placement = {figure_id:string; chapter_id:string; caption:string}
function open(initial: Placement[], conflict = false) {
  let revision = 5
  let placements = initial
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url !== path) throw new Error(`Unexpected request ${url}`)
    if (init?.method === 'PUT') {
      if (conflict && revision === 5) {
        revision = 6
        return Response.json({detail:{code:'sci_settings_revision_conflict'}}, {status:409})
      }
      const input = JSON.parse(String(init.body))
      expect(input.expected_revision).toBe(revision)
      placements = [...input.placements].sort((left, right) => chapters.findIndex(ch => ch.id === left.chapter_id) -
        chapters.findIndex(ch => ch.id === right.chapter_id))
      revision += 1
    }
    return Response.json({revision, template_id:'template1', chapters, figures, placements})
  })
  vi.stubGlobal('fetch', fetcher)
  const next = vi.fn()
  render(<CustomerSciResources projectId="p1" registerLeaveGuard={() => () => {}} onTemplate={vi.fn()} onFigures={vi.fn()} onContinue={next} />)
  return {fetcher, next}
}

afterEach(() => {cleanup(); vi.unstubAllGlobals()})

it('saves the chapter, caption and within-chapter order of selected formal figures', async () => {
  const {fetcher, next} = open([{figure_id:'f1', chapter_id:'results', caption:'第一张图。'}])
  const chapter = await screen.findByRole('combobox', {name:'入稿章节 主图乙'})
  expect(screen.queryAllByText('第 1 版')).toHaveLength(0)
  const third = screen.getByRole('combobox', {name:'入稿章节 主图丙'})
  fireEvent.change(third, {target:{value:'discussion'}})
  fireEvent.change(screen.getByRole('textbox', {name:'图注 主图丙'}), {target:{value:'第三张图。'}})
  fireEvent.change(chapter, {target:{value:'results'}})
  expect(screen.getByRole('button', {name:'保存资源配置'})).toHaveProperty('disabled', true)
  fireEvent.change(screen.getByRole('textbox', {name:'图注 主图乙'}), {target:{value:'第二张图。'}})
  fireEvent.click(screen.getByRole('button', {name:'主图乙 在本章前移'}))
  fireEvent.click(screen.getByRole('button', {name:'下一步 文献与初稿'}))
  await waitFor(() => expect(next).toHaveBeenCalledTimes(1))
  const write = fetcher.mock.calls.find(([, init]) => init?.method === 'PUT')
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({expected_revision:5, placements:[
    {figure_id:'f2', chapter_id:'results', caption:'第二张图。'}, {figure_id:'f1', chapter_id:'results', caption:'第一张图。'},
    {figure_id:'f3', chapter_id:'discussion', caption:'第三张图。'},
  ]})
})

it('requires explicit repair of an obsolete chapter and retains edits across a revision conflict', async () => {
  const {fetcher} = open([{figure_id:'f1', chapter_id:'removed', caption:'保留的图注。'}], true)
  const chapter = await screen.findByRole('combobox', {name:'入稿章节 主图甲'})
  expect(chapter).toHaveProperty('value','removed')
  expect(within(chapter).getByRole('option', {name:'原章节已失效'})).toBeTruthy()
  expect(screen.getByRole('button', {name:'保存资源配置'})).toHaveProperty('disabled', true)
  fireEvent.change(chapter, {target:{value:'discussion'}})
  fireEvent.click(screen.getByRole('button', {name:'保存资源配置'}))
  fireEvent.click(await screen.findByRole('button', {name:'重新读取并核对'}))
  expect(await screen.findByText('已读取最新资源。请核对当前草稿后再保存。')).toBeTruthy()
  expect(chapter).toHaveProperty('value','discussion')
  expect(screen.getByRole('textbox', {name:'图注 主图甲'})).toHaveProperty('value','保留的图注。')
  fireEvent.click(screen.getByRole('button', {name:'保存资源配置'}))
  await screen.findByText('资源配置已保存。')
  const writes = fetcher.mock.calls.filter(([, init]) => init?.method === 'PUT')
  expect(writes.map(([, init]) => JSON.parse(String(init?.body)).expected_revision)).toEqual([5,6])
})

it('keeps the thesis composer accessible while a school template is unavailable', async () => {
  const compose = vi.fn()
  const fetcher = vi.fn(async () => Response.json({revision:1, template_id:null, chapters:[], figures:[figures[0]], placements:[]}))
  vi.stubGlobal('fetch', fetcher)
  render(<CustomerSciResources projectType="thesis" projectId="p1" registerLeaveGuard={() => () => {}} onFigures={compose} />)
  await screen.findByText('请先采用学校模板。')
  expect(screen.queryByRole('button', {name:'保存资源配置'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'前往图件拼版'}))
  expect(compose).toHaveBeenCalledOnce()
})

it('lets the customer clear the last thesis placement when its figure is unavailable', async () => {
  const state = {revision:5, template_id:'template1', chapters, figures:[],
    placements:[{figure_id:'removed',chapter_id:'old-chapter',caption:'原配置的说明。'}]}
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => init?.method === 'PUT' ?
    Response.json({...state,revision:6,placements:[]}) : Response.json(state))
  vi.stubGlobal('fetch', fetcher)
  render(<CustomerSciResources projectType="thesis" projectId="p1" registerLeaveGuard={() => () => {}} onFigures={vi.fn()} />)
  expect((await screen.findByRole('alert')).textContent).toContain('请为失效的图件配置重新指定章节，或设为未选用。')
  const chapter = screen.getByRole('combobox', {name:/入稿章节 原配图/})
  fireEvent.change(chapter, {target:{value:''}})
  fireEvent.click(screen.getByRole('button', {name:'保存资源配置'}))
  await waitFor(() => expect(screen.queryByRole('button', {name:'保存资源配置'})).toBeNull())
  const write = fetcher.mock.calls.find(([, init]) => init?.method === 'PUT')
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({expected_revision:5, placements:[]})
})
