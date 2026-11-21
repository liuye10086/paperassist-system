import {act,cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import ManuscriptPreview from './ManuscriptPreview'
import {snapshotFixture} from './manuscriptFixtures'
import type {Snapshot} from './manuscriptTypes'
import {setLocale} from '../../shared/i18n'

afterEach(()=>{cleanup();setLocale('zh-CN')})
const frozenNotice='科学审核已完成；逐章语言与学校导出仍待核对。'
function schoolSnapshot(status='scientific_and_language_reviewed'):Snapshot{
 return {...snapshotFixture,notice:frozenNotice,thesis_context:{profile:{school:'Synthetic school',applicable_version:'2026'},confirmation_id:'frozen-confirmation'},sections:[],writing_provenance:{schema_version:2,school_content_version:'school-live-v1',provider_provenance:'synthetic_fixture',verification_status:status}} as unknown as Snapshot
}

it('keeps the completed candidate-stage notice in evidence, outside the body, without a collapse panel',()=>{
 const snapshot=schoolSnapshot(),original=JSON.stringify(snapshot)
 const {rerender}=render(<ManuscriptPreview snapshot={snapshot} presentation="body"/> )
 expect(screen.getByText(frozenNotice).closest('[hidden]')).not.toBeNull()
 expect(screen.getByText('已记录人工科学与语言审核；不等同科学有效性证明。').closest('details')).toBeNull()
 rerender(<ManuscriptPreview snapshot={snapshot} presentation="evidence"/> )
 expect(screen.getByText(frozenNotice).closest('[hidden]')).toBeNull()
 expect(document.querySelector('details')).toBeNull()
 expect(screen.getByText(frozenNotice).textContent).toBe(frozenNotice)
 act(()=>setLocale('en'))
 expect(screen.getByText('Frozen school configuration')).toBeTruthy()
 expect(screen.getByText(frozenNotice).textContent).toBe(frozenNotice)
 expect(JSON.stringify(snapshot)).toBe(original)
})

it('keeps the original notice visible for pending school reviews and fully reviewed SCI or legacy school drafts',()=>{
 const snapshot=schoolSnapshot('scientific_reviewed_language_pending')
 const {rerender}=render(<ManuscriptPreview snapshot={snapshot}/> )
 expect(screen.getByText(frozenNotice).closest('details')).toBeNull()
 expect(screen.queryByText('查看候选阶段的冻结提示')).toBeNull()
 const sci={...snapshot,thesis_context:undefined,writing_provenance:{...snapshot.writing_provenance!,school_content_version:undefined,verification_status:'scientific_and_language_reviewed'}}
 rerender(<ManuscriptPreview snapshot={sci}/> )
 expect(screen.getByText(frozenNotice).closest('details')).toBeNull()
 rerender(<ManuscriptPreview snapshot={{...schoolSnapshot(),writing_provenance:{...schoolSnapshot().writing_provenance!,school_content_version:undefined}}}/> )
 expect(screen.getByText(frozenNotice).closest('details')).toBeNull()
})

it('names the school template and sources in customer terms while preserving the saved scope notice',()=>{
 const original='根据项目需求和关联资料整理的事实稿。请核对发现及其依据，再继续写作。'
 const snapshot:Snapshot={...schoolSnapshot(),issues:[{id:'scope',kind:'limitation',field:'scope',message:original,values:[]}]}
 const {rerender}=render(<ManuscriptPreview customerView snapshot={snapshot} presentation="evidence"/>)
 expect(screen.getByRole('heading',{name:'本版使用的学校模板'})).toBeTruthy()
 expect(screen.getByRole('heading',{name:'本版资料与依据'})).toBeTruthy()
 expect(screen.getByText('这些材料来自项目需求和已关联的资料。继续写作前，请核对结果与来源。')).toBeTruthy()
 act(()=>setLocale('en'))
 expect(screen.getByRole('heading',{name:'School template for this version'})).toBeTruthy()
 expect(screen.getByRole('heading',{name:'Materials and evidence for this version'})).toBeTruthy()
 expect(screen.getByText('These materials come from the project requirements and linked sources. Check the findings and their sources before writing.')).toBeTruthy()
 rerender(<ManuscriptPreview snapshot={snapshot} presentation="evidence"/>)
 expect(screen.getByRole('heading',{name:'Frozen school configuration'})).toBeTruthy()
 expect(screen.getByText(original)).toBeTruthy()
 expect(snapshot.issues[0].message).toBe(original)
 const savedEnglish='Fact draft based on the saved requirements and linked materials. Review observations and sources before continuing.'
 const englishSnapshot={...snapshot,issues:[{...snapshot.issues[0],message:savedEnglish}]}
 rerender(<ManuscriptPreview customerView snapshot={englishSnapshot} presentation="evidence"/>)
 expect(screen.getByText('These materials come from the project requirements and linked sources. Check the findings and their sources before writing.')).toBeTruthy()
 rerender(<ManuscriptPreview snapshot={englishSnapshot} presentation="evidence"/>)
 expect(screen.getByText(savedEnglish)).toBeTruthy()
})

it.each(['zh-CN','en'] as const)('shows the school system scope and research source instruction in customer language for a saved %s notice',savedLocale=>{
 const original=savedLocale==='en'
  ? 'Frozen school chapter candidate. Scientific review complete; language and school export review pending. Live model response; research data provenance remains independently reviewable.'
  : '冻结学校章节候选. 科学审核已完成；逐章语言与学校导出仍待核对。 真实模型回执；研究数据来源仍须独立核对。'
 const raw=schoolSnapshot()
 const saved={...raw,notice:original,writing_provenance:{...raw.writing_provenance!,provider_provenance:'openai_live'},
  issues:[{id:'scope',kind:'limitation' as const,field:'scope',message:original,values:[]},
   {id:'other',kind:'limitation' as const,field:'note',message:original+'（原备注）',values:[]}]}
 const bytes=JSON.stringify(saved)
 const {rerender}=render(<ManuscriptPreview customerView snapshot={saved}/>)
 expect(screen.getByText('请对照本版资料，独立核对研究数据的来源。')).toBeTruthy()
 expect(screen.getByText('这份稿件按学校章节整理，已完成科学与语言核对。内容由模型生成，数据来源仍需独立核对。')).toBeTruthy()
 expect(screen.getByText(original+'（原备注）')).toBeTruthy()
 act(()=>setLocale('en'))
 expect(screen.getByText('Independently check the research data against the sources for this version.')).toBeTruthy()
 expect(screen.getByText('This manuscript follows the school chapters. Its scientific and language checks are complete. A model generated the content. Check the data sources independently.')).toBeTruthy()
 rerender(<ManuscriptPreview snapshot={saved}/>)
 expect(screen.getAllByText(original).length).toBeGreaterThan(0)
 expect(screen.getByText('Research data provenance must be checked independently against the frozen sources.')).toBeTruthy()
 expect(JSON.stringify(saved)).toBe(bytes)
})


it('recognizes pending synthetic school notices while keeping other limitations and staff text as saved',()=>{
 const raw=schoolSnapshot('pending')
 const text='Frozen school chapter candidate. Scientific and language review pending. Synthetic provider fixture; no live model call.'
 const scope={id:'scope',kind:'limitation' as const,field:'scope',message:text,values:[]}
 const candidate={...raw,notice:text,issues:[scope]}
 const {rerender}=render(<ManuscriptPreview customerView snapshot={candidate}/>)
 expect(screen.getByText('这份稿件按学校章节整理，请核对科学内容和各章语言。这份示例使用模拟内容，未调用模型。')).toBeTruthy()
 rerender(<ManuscriptPreview customerView snapshot={{...candidate,issues:[{...scope,id:'business-note'}]}}/>)
 expect(screen.getByText(text)).toBeTruthy()
 rerender(<ManuscriptPreview snapshot={candidate}/>)
 expect(screen.getAllByText(text).length).toBeGreaterThan(0)
})
