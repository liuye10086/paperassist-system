import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {setLocale} from './index'
import FigureLanguagePanel from '../../features/manuscripts/FigureLanguagePanel'
import CitationSnapshot from '../../features/literature/CitationSnapshot'
import StorageDeletion from '../../features/operations/StorageDeletion'
import {snapshotFixture} from '../../features/manuscripts/manuscriptFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('translates figure control names while retaining original labels, series and the edited draft',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 const content={title:'原始图 1',x_label:'Value −3 mg/L',y_label:'组别',caption:'原始图注',series:[{label:'原始系列'}]}
 const source={kind:'figure',id:'fig1',file_id:'file1',role:'image_observation',label:'Original',sha256:'a'.repeat(64),download_url:null,content}
 const snapshot={...snapshotFixture,sources:[source],results_groups:[{id:'g1',title:'原始分组',paragraphs:[],tables:[],figures:[{id:'fig1',title:content.title,caption:content.caption,number:1,sha256:source.sha256,source_ids:['fig1']}]}]}
 render(<FigureLanguagePanel projectId="p1" snapshot={snapshot as never}/>)
 fireEvent.click(screen.getByRole('button',{name:'独立图语言版本'}))
 expect(await screen.findByLabelText('图标题')).toHaveProperty('value',content.title)
 fireEvent.change(screen.getByLabelText('图标题'),{target:{value:'用户修正 draft'}})
 act(()=>setLocale('en'))
 expect(screen.getByLabelText('Figure title')).toHaveProperty('value','用户修正 draft')
 expect(screen.getByLabelText('X-axis label')).toHaveProperty('value',content.x_label)
 expect(screen.getByLabelText('Series 0')).toHaveProperty('value','原始系列')
 expect(content.title).toBe('原始图 1')
 act(()=>setLocale('zh-CN'));expect(screen.getByLabelText('图标题')).toHaveProperty('value','用户修正 draft')
})
it('translates the References interface heading while keeping frozen output text and bibliography exact',()=>{
 const output={text:'Frozen body 原文 [1]',references:[{number:1,text:'Frozen bibliography 原文'}]}
 const view={id:'draft1',revision:2,current_changes:[],snapshot:{output_language:'en',output,paragraphs:[]}}
 const before=JSON.stringify(view)
 render(<CitationSnapshot projectId="p1" view={view as never}/>)
 expect(screen.getByRole('heading',{name:'参考文献'})).toBeTruthy()
 act(()=>setLocale('en'));expect(screen.getByRole('heading',{name:'References'})).toBeTruthy()
 expect(screen.getByText(output.text)).toBeTruthy();expect(screen.getByText(output.references[0].text)).toBeTruthy()
 expect(JSON.stringify(view)).toBe(before)
})
it('safely localizes unknown deletion error codes and retains original reason, kind and input values',async()=>{
 const plan={id:'plan1',project_id:'p1',file_id:null,scope_kind:'project',reason:'用户理由',manifest_sha256:'a'.repeat(64),state:'preview',retention_policy:'retain_all',physical_deletion_available:false,blockers:[],items:[{object_id:'object1',kind:'original-kind',size_bytes:42,sha256:'b'.repeat(64),action:'retain',state:'failed',reason_codes:['original-reason'],attempt_no:0,error_code:'PRIVATE_UNTRUSTED_TRACE'}],deleted_object_count:0,deleted_bytes:0,all_deleted:false}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(plan)))
 render(<StorageDeletion onForbidden={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('删除项目标识'),{target:{value:'p1'}})
 fireEvent.change(screen.getByLabelText('删除理由'),{target:{value:'用户理由'}})
 fireEvent.click(screen.getByRole('button',{name:'预览处置范围'}))
 expect(await screen.findByText('original-kind')).toBeTruthy()
 expect(screen.getByText('original-reason')).toBeTruthy()
 expect(screen.queryByText('PRIVATE_UNTRUSTED_TRACE')).toBeNull()
 act(()=>setLocale('en'))
 expect(screen.getByText('Object deletion failed. Please view task details.')).toBeTruthy()
 expect(screen.getByDisplayValue('用户理由')).toBeTruthy();expect(screen.getByDisplayValue('p1')).toBeTruthy()
 expect(plan.items[0].error_code).toBe('PRIVATE_UNTRUSTED_TRACE')
})
