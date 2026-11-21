// B04 task 8: the customer chapter fields name the chapter a template trip returns to; staff keep their wording.
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {customerManuscriptNavigation} from '../customer/customerPaperNavigation'
import ProjectManuscripts from './ProjectManuscripts'
import {candidatesFixture} from './manuscriptFixtures'
import {setLocale} from '../../shared/i18n'

const profile={revision:2,school:'测试学校',department:'',major:'',degree_type:'硕士',education_level:'研究生',applicable_version:'2026',bound_confirmation_id:'confirm1'}
const chapters=[{id:'chapter-design',title:'第 3 章 研究设计',level:2}]
const readiness={ready:true,blocking_reasons:[],profile,confirmation_id:'confirm1',chapters,purposes:['introduction','materials_and_methods'],template_source_file_ids:[]}
const props={projectId:'p1',researchTopic:'学校研究',outputLanguage:'zh-CN' as const,active:true,projectType:'thesis' as const}
function serve(thesis:unknown){vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?{...candidatesFixture,project_type:'thesis',thesis}:{items:[]})))}
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear();setLocale('zh-CN')})

it('hides the chapter level from customers and keeps it for staff',async()=>{
 serve(readiness)
 const view=render(<ProjectManuscripts {...props}/>)
 expect(within(await screen.findByRole('group',{name:'第 3 章 研究设计'})).getByText('章节层级 2')).toBeTruthy()
 view.unmount();sessionStorage.clear()
 render(<ProjectManuscripts {...props} customerThesis={{wordOnly:false}} view="materials" onOpenSchoolTemplate={vi.fn()}/>)
 const chapter=await screen.findByRole('group',{name:'第 3 章 研究设计'})
 expect(chapter.id).toBe('thesis-chapter-chapter-design')
 expect(within(chapter).queryByText(/章节层级/)).toBeNull()
})

it('sends each chapter that needs a template with its own way back',async()=>{
 serve({...readiness,ready:false,blocking_reasons:['school_template_source_changed']})
 const open=vi.fn()
 render(<ProjectManuscripts {...props} customerThesis={{wordOnly:false}} view="materials" onOpenSchoolTemplate={open}/>)
 fireEvent.click(await screen.findByRole('button',{name:'去采用学校模板（完成后回到第 3 章 研究设计）'}))
 expect(open).toHaveBeenCalledWith({id:'chapter-design',title:'第 3 章 研究设计'})
 expect(screen.getByText('学校模板来源已变化，请重新确认。')).toBeTruthy()
})

it('keeps the staff school template link and binding wording',async()=>{
 serve({...readiness,ready:false,confirmation_id:null,blocking_reasons:['school_template_not_bound'],chapters:[]})
 render(<ProjectManuscripts {...props}/>)
 expect(await screen.findByText('请先绑定学校模板')).toBeTruthy()
 expect(screen.getByRole('link',{name:'配置学校模板'})).toBeTruthy()
 expect(screen.queryByRole('button',{name:/去采用学校模板/})).toBeNull()
})

it('reads the chapter to return to only on the materials view',()=>{
 const read=(hash:string)=>customerManuscriptNavigation(new URLSearchParams(hash),false,true)
 expect(read('view=materials&chapter=chapter-design').chapter).toEqual({id:'chapter-design'})
 expect(read('view=materials&focus=chapters').chapter).toEqual({id:null})
 expect(read('view=materials&chapter=bad%20id').chapter).toBeUndefined()
 expect(read('view=list&chapter=chapter-design').chapter).toBeUndefined()
 expect(read('view=materials&focus=other').chapter).toBeUndefined()
})

it('words the template trip in English',async()=>{
 setLocale('en')
 serve({...readiness,ready:false,confirmation_id:null,blocking_reasons:['school_template_not_bound'],chapters:[]})
 render(<ProjectManuscripts {...props} customerThesis={{wordOnly:false}} view="materials" onOpenSchoolTemplate={vi.fn()}/>)
 expect(await screen.findByRole('button',{name:'Adopt a school template (then back to Chapters and review)'})).toBeTruthy()
 expect(screen.getByText('No school template is in use yet. Once you adopt one, the chapter titles and levels can be checked against the school format.')).toBeTruthy()
})
