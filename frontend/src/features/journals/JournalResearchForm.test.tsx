import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import JournalResearchForm from './JournalResearchForm'
import type {MaterialCandidate,Profile,ResearchRequest} from './contracts'
import {setLocale,translate} from '../../shared/i18n'
import {versionMinute} from '../../shared/versionLabelText'
afterEach(()=>{cleanup();setLocale('zh-CN')})
const config={default_limit:2,max_limit:4,configuration:{status:'bound' as const,version_id:'v2',sha256:'a'.repeat(64)}}
function fill(){fireEvent.change(screen.getByLabelText('研究标题'),{target:{value:'Synthetic local study'}});fireEvent.change(screen.getByLabelText('主题标签（逗号或换行分隔）'),{target:{value:'synthetic'}});fireEvent.change(screen.getByRole('textbox',{name:'文章类型'}),{target:{value:'research'}})}
it('omits default count, sends an explicit count and preserves that choice when configuration refreshes',()=>{
 const create=vi.fn(async(_request:ResearchRequest)=>true);const props={manuscripts:[],materials:[],profiles:[],busy:false,onCreate:create,configuration:config}
 const view=render(<JournalResearchForm {...props}/>);fill();expect(screen.getByText('当前默认 2 条，最多 4 条。')).toBeTruthy();fireEvent.submit(screen.getByRole('form',{name:'研究信息与投稿偏好'}));expect(create.mock.calls[0][0]).not.toHaveProperty('limit')
 fireEvent.click(screen.getByLabelText('明确指定建议数量'));fireEvent.change(screen.getByLabelText('建议数量'),{target:{value:'3'}});fireEvent.submit(screen.getByRole('form',{name:'研究信息与投稿偏好'}));expect(create.mock.calls[1][0]).toHaveProperty('limit',3)
 view.rerender(<JournalResearchForm {...props} configuration={{...config,default_limit:1,max_limit:2}}/>);expect(screen.getByLabelText('建议数量')).toHaveProperty('value','3');expect(screen.getByLabelText('建议数量')).toHaveProperty('max','2')
})

const filename='figure-Parsed document v1.jpeg'
const materials:MaterialCandidate[]=[
 {kind:'original',id:'file1',file_id:'file1',label:filename,version:null},
 {kind:'document_version',id:'parsed1',file_id:'file1',label:filename+' — 文档解析 / Parsed document v1',version:1},
 {kind:'ocr_review_version',id:'review2',file_id:'file1',label:filename+' — 人工核对 / Human reviewed v2',version:2},
 {kind:'external_evidence_version',id:'evidence3',file_id:'file1',label:'Saved evidence',version:3},
]
const manuscriptIds=['45Af46f0-acf5-42cc-9513-c7eda248fc88','41419d26-5064-47ad-8cad-1c33108ac7e9']
const dates=['2026-11-19T06:04:00Z','2026-11-20T09:54:00Z']
const manuscripts=manuscriptIds.map((id,index)=>({id,title:'Working title',versions:[
 {id:'v'+index,revision:1,status:'published',snapshot:{title:'Same saved title'},created_at:dates[index]},
]}))
const profile:Profile={id:'d1c78892-e1c1-400c-bca0-e1685c4281a5',name:'Saved journal',project_id:'p1',source_type:'user_provided',source_text:'',source_url:'',official_url:'',source_status:'available',verified_on:'2026-11-19',conditions:'',permission:'',fields:{},synthetic:false,verification_level:'user_material_only',created_at:dates[0]}
function show(customerSci:boolean){
 const create=vi.fn(async(_request:ResearchRequest)=>true)
 render(<JournalResearchForm customerSci={customerSci} manuscripts={manuscripts} materials={materials} profiles={[profile]} busy={false} configuration={config} onCreate={create}/>)
 return create
}
it.each(['en','zh-CN'] as const)('shows readable material names and preserves source identities in %s',locale=>{
 setLocale(locale)
 const create=show(true)
 const names=[
  filename+' · '+translate('原始文件'),filename+(locale==='en'?' — Parsed document v1':' — 文档解析 v1'),
  filename+(locale==='en'?' — Human reviewed v2':' — 人工核对 v2'),
  'Saved evidence · '+translate('外部证据版本')+' · '+translate('版本 {number}',{number:3}),
 ]
 names.forEach(name=>fireEvent.click(screen.getByRole('checkbox',{name})))
 fireEvent.submit(screen.getByRole('form'))
 expect(create.mock.calls[0][0].materials).toEqual(materials.map(({kind,id,file_id})=>({kind,id,file_id})))
})
it.each(['en','zh-CN'] as const)('identifies fixed manuscripts and journal profiles by saved time in %s',locale=>{
 setLocale(locale)
 const create=show(true)
 const names=dates.map(date=>'Same saved title · '+translate('第 {revision} 版',{revision:1})+' · '+versionMinute(date,locale))
 names.forEach(name=>expect(screen.getByRole('option',{name})).toBeTruthy())
 fireEvent.change(screen.getByLabelText(translate('固定稿件版本')),{target:{value:manuscriptIds[1]+':1'}})
 const form=screen.getByRole('form')
 expect(Array.from(form.querySelectorAll('p')).find(el=>el.textContent?.includes(names[1]))).toBeTruthy()
 fireEvent.click(screen.getByLabelText(translate('使用每条来源链的最新版本')))
 fireEvent.click(screen.getByRole('checkbox',{name:'Saved journal · '+versionMinute(profile.created_at,locale)}))
 for(const id of [...manuscriptIds,profile.id])expect(form.textContent).not.toContain(id)
 fireEvent.submit(form)
 expect(create.mock.calls[0][0]).toMatchObject({manuscript:{id:manuscriptIds[1],revision:1},profile_ids:[profile.id]})
})
it('retains source protocol labels and selected identities for staff',()=>{
 show(false)
 expect(screen.getByRole('checkbox',{name:materials[1].label+' · document_version'})).toBeTruthy()
 fireEvent.change(screen.getByLabelText('固定稿件版本'),{target:{value:manuscriptIds[0]+':1'}})
 expect(screen.getByText('本批固定所选版本：'+manuscriptIds[0]+':1')).toBeTruthy()
 fireEvent.click(screen.getByLabelText('使用每条来源链的最新版本'))
 expect(screen.getByRole('checkbox',{name:'Saved journal · '+profile.id})).toBeTruthy()
})
