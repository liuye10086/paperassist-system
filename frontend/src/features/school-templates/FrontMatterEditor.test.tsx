import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {useState} from 'react'
import FrontMatterEditor from './FrontMatterEditor'
import {setLocale} from '../../shared/i18n'
import type {FrontMatter,FrontSource} from './contracts'

afterEach(()=>{cleanup();setLocale('zh-CN')})
const sources=[{id:'p1',source:{part:'word/document.xml',path:'/p[1]',text:'培养层次：示例值'},section_id:'s1',suggested_label:'培养层次',style:{font_size_pt:18},style_sources:{}},{id:'p2',source:{part:'word/document.xml',path:'/p[2]',text:'作者签名：示例签名'},section_id:'s1',suggested_label:'作者签名',style:{font_size_pt:12},style_sources:{}}] as FrontSource[]
function View(){const [value,setValue]=useState<FrontMatter|null>(null);return <><FrontMatterEditor value={value} onChange={setValue} sources={sources} sections={[{id:'s1'}]} chapters={[{id:'c1',title:'声明',level:1}]}/><output>{JSON.stringify(value)}</output></>}
it('confirms source-backed dynamic fields without copying examples and preserves values on language switch',()=>{
 render(<View/>);fireEvent.click(screen.getByLabelText('使用来源绑定的前置规则'))
 fireEvent.change(screen.getByLabelText('新增字段来源'),{target:{value:'p1'}});fireEvent.click(screen.getByRole('button',{name:'添加前置字段'}))
 expect((screen.getByLabelText('字段标签 1') as HTMLInputElement).value).toBe('培养层次')
 fireEvent.click(screen.getByLabelText('必填字段 1'));fireEvent.change(screen.getByLabelText('字段标签 1'),{target:{value:'人工标签草稿'}})
 act(()=>setLocale('en'));expect((screen.getByLabelText('Field label 1') as HTMLInputElement).value).toBe('人工标签草稿')
 expect(screen.getByRole('status').textContent).not.toContain('示例值')
 expect(screen.getByRole('status').textContent).toContain('"required":true')
})
it('names customer source options by source and original text without storage paths',()=>{
 const supplement={id:'p3',source:{part:'学校补充规范.docx',path:'document-version:5f7a9b1d-3e5a-4c7b-9d1f-2a4c6e8b0d35:e1',text:'学号：'},section_id:'s1',suggested_label:'学号',style:{font_size_pt:12},style_sources:{}} as FrontSource
 const value:FrontMatter={schema_version:1,cover_section_id:'s1',fields:[{id:'field-1',label:'培养层次',kind:'text',required:false,source_id:'p1',style_source_id:null,section_id:'s1',chapter_id:null}],content_requirements:[]}
 const view=render(<FrontMatterEditor customerView value={value} onChange={()=>{}} sources={[...sources,supplement]} sections={[{id:'s1'}]} chapters={[]}/>)
 const labels=[...view.container.querySelectorAll('option')].map(option=>option.textContent??'')
 expect(labels).toContain('学校模板 · 培养层次：示例值');expect(labels).toContain('补充规范《学校补充规范.docx》 · 学号：')
 expect(labels.join('\n')).not.toMatch(/word\/|\/p\[|document-version:/)
 cleanup()
 const staff=render(<FrontMatterEditor value={value} onChange={()=>{}} sources={sources} sections={[{id:'s1'}]} chapters={[]}/>)
 expect(staff.container.textContent).toContain('word/document.xml · /p[1]')
})
