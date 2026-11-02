import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import PresentationLanguagePanel from './PresentationLanguagePanel'
import PresentationExportDetails from './PresentationExportDetails'
import {exportFixture} from './manuscriptFixtures'
import type {ManuscriptExport} from './manuscriptTypes'
import {emptyPresentation,type PresentationExport,type SavedPresentation} from './presentationTypes'
const config=emptyPresentation(),quality={scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending',language_review:'pending_explicit_review'}
const binding={presentation_version_id:'presentation-source',language_view:'en' as const,review_mode:'identified' as const}
const presentation={id:'presentation-source',manuscript_id:'m1',revision:1,base_version_id:'v1',peer_version_id:null,config} as SavedPresentation
const body={location:'body',kind:'export_text',text:'English text.',content_sha256:'b'.repeat(64),target_language:'en',protected_identity:false,scope:'narrative',verification:'pending_manual_review',finite_check:{status:'passed',message:'有限规则通过'}}
afterEach(cleanup)
it('accepts known image and figure-text items and blocks an unknown image as missing material',async()=>{
 const inventory=[body,{location:'image:known',kind:'image',text:'',content_sha256:'c'.repeat(64),target_language:'en',language_known:true,no_text:false},{location:'image:known:title',kind:'figure_text',text:'Known label',content_sha256:'d'.repeat(64),target_language:'en',scope:'label'},{location:'image:blank',kind:'image',text:'',content_sha256:'f'.repeat(64),target_language:'en',language_known:true,no_text:true}]
 const source={...exportFixture,version_id:'v1',sha256:'a'.repeat(64),presentation:{binding,checks:[],quality,language_inventory:inventory}} as ManuscriptExport
 const changed=vi.fn(),blocked=vi.fn(),props={figures:[{id:'known',number:1,title:'Known image'},{id:'blank',number:2,title:'No-text image'}],config,baseVersionId:'v1',peerVersionId:null,exports:[source],presentations:[presentation],onChange:changed,onBlocked:blocked}
 const view=render(<PresentationLanguagePanel {...props}/>);expect(screen.getByRole('option',{name:/DOCX 导出 1/})).toBeTruthy();fireEvent.change(screen.getByLabelText('语言确认来源 DOCX'),{target:{value:source.id}})
 for(const [location,decision] of [['body','target_language'],['image:known','target_language'],['image:known:title','target_language'],['image:blank','no_text']]){const group=screen.getByRole('group',{name:new RegExp('^核对项目 '+(['body','image:known','image:known:title','image:blank'].indexOf(location)+1)+' ·')});fireEvent.change(within(group).getByLabelText('此项语言决定'),{target:{value:decision}});fireEvent.change(within(group).getByLabelText('此项语言审核理由'),{target:{value:'Explicitly checked '+location}})}
 await waitFor(()=>expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({decisions:expect.arrayContaining([expect.objectContaining({location:'image:known',decision:'target_language'}),expect.objectContaining({location:'image:known:title',decision:'target_language'})])})));expect(blocked).toHaveBeenLastCalledWith(false)
 const unknown={...source,id:'unknown-export',presentation:{...source.presentation!,language_inventory:[{location:'image:unknown',kind:'image',text:'',content_sha256:'e'.repeat(64),target_language:'en',language_known:false,no_text:false}]}} as ManuscriptExport
 changed.mockClear();blocked.mockClear();view.rerender(<PresentationLanguagePanel key="unknown" {...props} exports={[unknown]}/>);fireEvent.change(screen.getByLabelText('语言确认来源 DOCX'),{target:{value:unknown.id}});await screen.findByText('图内文字未知，须补充已核实的图语言来源或无文字版本；此项不能确认。');expect(screen.queryByRole('group',{name:/image:unknown/})).toBeNull();expect(blocked).toHaveBeenLastCalledWith(true);expect(changed).not.toHaveBeenCalledWith(expect.objectContaining({source_export_id:unknown.id}))
})
it('distinguishes finite checks from an exact-output language receipt while scientific and real-compliance checks remain pending',()=>{
 const value={binding,checks:[],quality,language_inventory:[body]} as PresentationExport
 const view=render(<PresentationExportDetails value={value}/>);expect(screen.queryByText('当前精确输出已记录逐项语言确认。')).toBeNull();expect(screen.getByText('自动有限检查通过；不等同人工语言确认。')).toBeTruthy();expect(screen.getByText('仍需人工核对')).toBeTruthy()
 const review={status:'confirmed' as const,inventory_sha256:'a'.repeat(64),decision_count:1,source_checks:[],source_export_id:'source-docx',source_sha256:'f'.repeat(64),language_view:'en' as const,review_mode:'identified' as const,decisions:[{location:'body',content_sha256:body.content_sha256,decision:'target_language' as const,reason:'Checked this exact output',exceptions:[]}]}
 view.rerender(<PresentationExportDetails value={{...value,quality:{...quality,language_review:'confirmed_for_exact_output'},language_review:review,language_inventory:[{...body,kind:'export_text',target_language:'en',verification:'pending_manual_review',finite_check:{status:'passed',message:'有限规则通过'},confirmation:{...review.decisions[0],status:'confirmed_for_exact_output',source_export_id:review.source_export_id,source_sha256:review.source_sha256}}]}}/>);expect(screen.getByText('当前精确输出已记录逐项语言确认。')).toBeTruthy();expect(screen.queryByText('source-docx')).toBeNull();expect(screen.queryByText(review.source_sha256)).toBeNull();expect(screen.getByText('已记录此项语言确认。')).toBeTruthy();expect(screen.getByText('科学语义仍待人工核对。')).toBeTruthy();expect(screen.getByText('真实学校或期刊合规仍待核对。')).toBeTruthy();expect(screen.getByText('Word/WPS 仍待人工验收。')).toBeTruthy();expect(screen.queryByText('仍需人工核对')).toBeNull();expect(body.verification).toBe('pending_manual_review')
 view.rerender(<PresentationExportDetails value={{...value,quality:{...quality,language_review:'confirmed_for_exact_output'}}}/>);expect(screen.queryByText('当前精确输出已记录逐项语言确认。')).toBeNull()
})
it('locates multiple image checks by their fixed figure numbers and titles without treating inventory order as figure number',()=>{
 const figures=[{id:'figure-a',number:3,title:'Treatment comparison'},{id:'figure-b',number:8,title:'External validation'}]
 const inventory=[body,{location:'en:image:figure-b',kind:'image',text:'',content_sha256:'c'.repeat(64),target_language:'en',language_known:true,no_text:true},{location:'zh-CN:image:figure-a',kind:'image',text:'',content_sha256:'d'.repeat(64),target_language:'en',language_known:true,no_text:true}]
 const source={...exportFixture,version_id:'v1',sha256:'a'.repeat(64),presentation:{binding,checks:[],quality,language_inventory:inventory}} as ManuscriptExport
 const view=render(<PresentationLanguagePanel config={config} baseVersionId="v1" peerVersionId={null} exports={[source]} presentations={[presentation]} figures={figures} onChange={vi.fn()} onBlocked={vi.fn()}/>);fireEvent.change(screen.getByLabelText('语言确认来源 DOCX'),{target:{value:source.id}})
 expect(screen.getByText('图 8 · External validation')).toBeTruthy();expect(screen.getByText('图 3 · Treatment comparison')).toBeTruthy();expect(document.body.textContent).not.toContain('figure-a');expect(document.body.textContent).not.toContain('figure-b');view.unmount();render(<PresentationExportDetails value={source.presentation!} figures={figures}/>);expect(screen.getByText('图 8 · External validation')).toBeTruthy();expect(screen.getByText('图 3 · Treatment comparison')).toBeTruthy()
})
it('keeps unresolved empty images traceable by image-only order and preserves the unknown-image guard',()=>{
 const inventory=[body,...['missing-a','missing-b'].map(id=>({location:'image:'+id,kind:'image',text:'',content_sha256:'c'.repeat(64),target_language:'en',language_known:false,no_text:false}))]
 const source={...exportFixture,version_id:'v1',sha256:'a'.repeat(64),presentation:{binding,checks:[],quality,language_inventory:inventory}} as ManuscriptExport;const blocked=vi.fn()
 render(<PresentationLanguagePanel config={config} baseVersionId="v1" peerVersionId={null} exports={[source]} presentations={[presentation]} onChange={vi.fn()} onBlocked={blocked}/>);fireEvent.change(screen.getByLabelText('语言确认来源 DOCX'),{target:{value:source.id}})
 expect(screen.getAllByText('图像定位待确认；请返回当前固定版本的图表清单核对。')).toHaveLength(2);expect(screen.getByText('本次清单中的第 1 个图像项目（不是图号）')).toBeTruthy();expect(screen.getByText('本次清单中的第 2 个图像项目（不是图号）')).toBeTruthy();expect(blocked).toHaveBeenLastCalledWith(true)
})

it('blocks a known empty image that cannot be matched to the fixed figure list',()=>{
 const inventory=[{location:'en:image:unmatched',kind:'image',text:'',content_sha256:'c'.repeat(64),target_language:'en',language_known:true,no_text:true}]
 const source={...exportFixture,version_id:'v1',sha256:'a'.repeat(64),presentation:{binding,checks:[],quality,language_inventory:inventory}} as ManuscriptExport;const blocked=vi.fn()
 render(<PresentationLanguagePanel config={config} baseVersionId="v1" peerVersionId={null} exports={[source]} presentations={[presentation]} onChange={vi.fn()} onBlocked={blocked}/>);fireEvent.change(screen.getByLabelText('语言确认来源 DOCX'),{target:{value:source.id}});expect((screen.getByLabelText('此项语言决定').closest('fieldset') as HTMLFieldSetElement).disabled).toBe(true);expect(blocked).toHaveBeenLastCalledWith(true)
})
