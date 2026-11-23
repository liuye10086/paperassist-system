import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import CustomerThesisRequirements, {ThesisTemplateOrganizer} from './CustomerThesisRequirements'
import {thesisBasicsDraft, type ThesisRequirements} from './thesisProjectRequirements'

const requirements: ThesisRequirements = {revision:2, language:'zh-CN',school:'示例大学',education_level:'硕士',
  title:'运动成绩分析',keywords:['cohort','training','performance','sports'],template:{name:'体育学模板',confirmation_id:'school1',
    chapters:[{id:'methods',title:'研究方法',level:1},{id:'results',title:'研究结果',level:1}]},
  sections:[{chapter_id:'methods',purpose:'materials_and_methods',content:'先说明入组要求。'}]}
const common = {projectId:'p1',registerLeaveGuard:vi.fn(() => () => {})}
function serve(input:ThesisRequirements) {
  let saved = structuredClone(input)
  const api = vi.fn(async (url:string, init?:RequestInit) => {
    if (url !== '/api/v1/projects/p1/thesis-requirements') throw new Error(url)
    if (init?.method === 'PUT') {
      const update = JSON.parse(String(init.body))
      saved = {...saved,...update.basics,language:update.language,revision:saved.revision+1,
        sections:update.chapter_plan?.sections ?? saved.sections}
    }
    return Response.json(saved)
  })
  vi.stubGlobal('fetch',api)
  return () => api.mock.calls.flatMap(([, init]) => init?.method === 'PUT' ? [JSON.parse(String(init.body))] : [])
}
afterEach(() => {cleanup();vi.unstubAllGlobals();sessionStorage.clear()})

it.each([true,false])('saves just the thesis basics and continues to uploads with or without a school template (%s)', async adopted => {
  const writes = serve({...requirements,template:adopted ? requirements.template : null})
  const next = vi.fn()
  render(<CustomerThesisRequirements {...common} onLanguageChanged={vi.fn()} onContinue={next}/>)
  fireEvent.click(await screen.findByRole('button',{name:'编辑毕业论文需求'}))
  expect(screen.queryByRole('button',{name:/学校模板/})).toBeNull()
  expect(screen.queryByRole('group',{name:'材料与方法章节'})).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'保存并继续 上传资料'}))
  await waitFor(() => expect(next).toHaveBeenCalledOnce())
  expect(writes()).toEqual([{basics:{title:requirements.title,school:requirements.school,education_level:'硕士',keywords:['cohort','training','performance','sports']},
    language:'zh-CN',expected_revision:2,expected_language:'zh-CN'}])
})
it('saves optional chapter requirements in the organizer without changing the thesis basics or leaving the step', async () => {
  const writes = serve(requirements)
  const open = vi.fn(), notifyMaterials = vi.fn()
  render(<ThesisTemplateOrganizer {...common} onOpenTemplate={open} onSectionsSaved={notifyMaterials}/>)
  fireEvent.click(await screen.findByRole('button',{name:'管理学校模板'}))
  expect(open).toHaveBeenCalledWith(true)
  expect(notifyMaterials).not.toHaveBeenCalled()
  expect(screen.queryByRole('button',{name:'编辑毕业论文需求'})).toBeNull()
  fireEvent.click(screen.getByText('逐章写作要求（选填）'))
  const results = within(screen.getByRole('group',{name:'主要结果章节'}))
  fireEvent.change(results.getByRole('combobox',{name:'模板章节'}),{target:{value:'results'}})
  fireEvent.click(results.getByRole('button',{name:'添加章节'}))
  fireEvent.change(results.getByRole('textbox',{name:'研究结果'}),{target:{value:'报告组间差异。'}})
  fireEvent.click(screen.getByRole('button',{name:'保存章节要求'}))
  expect((await screen.findByRole('status')).textContent).toContain('章节要求已保存。')
  expect(notifyMaterials).toHaveBeenCalledOnce()
  expect(writes()).toEqual([{basics:{title:requirements.title,school:requirements.school,education_level:'硕士',keywords:['cohort','training','performance','sports']},
    language:'zh-CN',expected_revision:2,expected_language:'zh-CN',
    chapter_plan:{confirmation_id:'school1',sections:[...requirements.sections,{chapter_id:'results',purpose:'results',content:'报告组间差异。'}]}}])
  expect(screen.queryByRole('button',{name:/下一步/})).toBeNull()
})
it('offers the upload entry only in the organizer until a template is adopted', async () => {
  serve({...requirements,template:null,sections:[]})
  const open = vi.fn()
  render(<ThesisTemplateOrganizer {...common} onOpenTemplate={open}/>)
  fireEvent.click(await screen.findByRole('button',{name:'上传学校模板'}))
  expect(open).toHaveBeenCalledWith(false)
  expect(screen.queryByText('逐章写作要求（选填）')).toBeNull()
})
it('keeps the automatic contents page out of the selectable methods and results chapters', async () => {
  serve({...requirements,template:{...requirements.template!,chapters:[
    {id:'toc',title:'目  录',level:1},...requirements.template!.chapters,
  ]}})
  render(<ThesisTemplateOrganizer {...common} onOpenTemplate={vi.fn()}/>)
  fireEvent.click(await screen.findByText('逐章写作要求（选填）'))
  const group = within(screen.getByRole('group',{name:'主要结果章节'}))
  expect(group.getByRole('option',{name:'研究结果'})).toBeTruthy()
  expect(group.queryByRole('option',{name:/目\s*录/})).toBeNull()
})
it.each(['customer-thesis-requirements','customer-thesis-chapter-requirements'])('preserves pending chapter edits across a successful basics save (%s)', async scope => {
  const writes = serve(requirements), next = vi.fn()
  const sections = [{...requirements.sections[0], content:'上次尚未保存的研究设计。'}]
  sessionStorage.setItem('paperassist.research-draft.v1:anonymous:p1:' + scope,JSON.stringify({
    revision:2,expectedLanguage:'zh-CN',confirmationId:'school1',basics:thesisBasicsDraft(requirements),sections,
  }))
  const first = render(<CustomerThesisRequirements {...common} onLanguageChanged={vi.fn()} onContinue={next}/>)
  if (scope === 'customer-thesis-chapter-requirements') fireEvent.click(await screen.findByRole('button',{name:'编辑毕业论文需求'}))
  fireEvent.click(await screen.findByRole('button',{name:'保存并继续 上传资料'}))
  await waitFor(() => expect(next).toHaveBeenCalledOnce())
  expect(writes()[0].chapter_plan).toBeUndefined()
  first.unmount()
  render(<ThesisTemplateOrganizer {...common} onOpenTemplate={vi.fn()}/>)
  expect(await screen.findByRole('textbox',{name:'研究方法'})).toHaveProperty('value',sections[0].content)
  fireEvent.click(screen.getByRole('button',{name:'保存章节要求'}))
  await waitFor(() => expect(writes()).toHaveLength(2))
  expect(writes()[1]).toMatchObject({expected_revision:3,chapter_plan:{confirmation_id:'school1',sections}})
})
