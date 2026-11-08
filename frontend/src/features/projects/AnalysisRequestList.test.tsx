import {cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import type {Version} from '../research-intake/contracts'
import AnalysisRequestList from './AnalysisRequestList'

afterEach(()=>{cleanup();sessionStorage.clear()})
const file=(id:string,status='parsed',type='xlsx')=>({id,filename:id+'.'+type,file_type:type,parse_status:status as 'parsed',size_bytes:10,uploaded_at:'',error:null})
const version=(kind:string,ids=['one']):Version=>({id:'req1',version:3,operation:'save',content:{schema_version:1,scope_items:[{id:'questionnaire.analysis.'+kind,title:kind,delivery_kind:'analysis',status:'planned'}]},sha256:'hash',created_at:'',material_refs:ids.map(file_id=>({file_id,availability:'provided',purpose:'raw_data'}))})
it('preselects only a unique compatible table and navigates with the saved requirement identity',()=>{
 const onNavigate=vi.fn();render(<AnalysisRequestList version={version('qc')} files={[file('one'),file('pdf','parsed','pdf')]} onNavigate={onNavigate}/> )
 fireEvent.click(screen.getByRole('button',{name:'进入配置'}))
 expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({view:'profile',fileId:'one',entry:{requirementVersionId:'req1',scopeItemId:'questionnaire.analysis.qc'}}))
})
it('requires a choice for multiple files and preserves exact selection',()=>{
 const onNavigate=vi.fn();render(<AnalysisRequestList version={version('qc',['one','two'])} files={[file('one'),file('two')]} onNavigate={onNavigate}/> )
 expect((screen.getByRole('button',{name:'进入配置'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('本项使用的来源'),{target:{value:'file:two'}})
 fireEvent.click(screen.getByRole('button',{name:'进入配置'}))
 expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({fileId:'two'}))
})
it('does not mark failed reads ready or allow a pending parse into configuration',()=>{
 const onNavigate=vi.fn(),onFile=vi.fn();const props={version:version('qc'),files:[file('one','parsing')],onNavigate,onFile}
 const {rerender}=render(<AnalysisRequestList {...props}/>)
 expect(screen.getAllByText('解析中').length).toBeGreaterThan(0);expect(screen.queryByRole('button',{name:'进入配置'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'查看材料'}));expect(onFile).toHaveBeenCalledWith('one')
 rerender(<AnalysisRequestList {...props} filesError="读取失败"/>)
 expect(screen.getByRole('alert').textContent).toContain('读取失败');expect(onNavigate).not.toHaveBeenCalled()
})
it('opens integration directly and leaves ORA/GSEA and qPCR/statistics as explicit choices',()=>{
 const onNavigate=vi.fn();const v=version('multiomics',[]);v.content.scope_items=['multiomics','enrichment','validation'].map(k=>({id:'questionnaire.analysis.'+k,title:k,delivery_kind:'analysis',status:'planned'}))
 render(<AnalysisRequestList version={v} files={[]} onNavigate={onNavigate}/>)
 fireEvent.click(within(screen.getByRole('article',{name:'multiomics'})).getByRole('button',{name:'进入配置'}))
 expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({intent:'integration',view:'bio-insights'}))
 expect((within(screen.getByRole('article',{name:'enrichment'})).getByLabelText('分析方式') as HTMLSelectElement).value).toBe('')
 expect((within(screen.getByRole('article',{name:'validation'})).getByLabelText('分析方式') as HTMLSelectElement).value).toBe('')
})
it('takes differential analysis with an unpublished original back to the existing import',()=>{
 const onNavigate=vi.fn();render(<AnalysisRequestList version={version('differential',['raw'])} files={[file('raw','stored','bio_bundle')]} imports={[{id:'existing',status:'waiting_confirmation',fileIds:['raw'],datasetId:'d',createdAt:''}]} onNavigate={onNavigate}/> )
 fireEvent.click(screen.getByRole('button',{name:'继续导入核对'}))
 expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({view:'bio-import',importId:'existing'}))
})
it('does not silently replace an explicitly selected import when it disappears on reread',()=>{
 const onNavigate=vi.fn(),record={id:'first',status:'waiting_confirmation',fileIds:['raw'],datasetId:'d',createdAt:'2026-11-03T00:00:00Z'},props={version:version('qc',['raw']),files:[file('raw','stored','bio_bundle')],onNavigate}
 const {rerender}=render(<AnalysisRequestList {...props} imports={[record,{...record,id:'second'}]}/> )
 fireEvent.change(screen.getByLabelText('本项使用的来源'),{target:{value:'file:raw:import:second'}})
 rerender(<AnalysisRequestList {...props} imports={[record]}/>)
 expect((screen.getByRole('button',{name:'进入配置'}) as HTMLButtonElement).disabled).toBe(true);expect(onNavigate).not.toHaveBeenCalled()
 fireEvent.change(screen.getByLabelText('本项使用的来源'),{target:{value:'file:raw:import:first'}})
 fireEvent.click(screen.getByRole('button',{name:'继续导入核对'}));expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({importId:'first'}))
})
it('restores the task, explicit method and exact source after reopening the same requirement',()=>{
 const v={...version('qc',['one','two']),project_id:'p1'};v.content.scope_items=['qc','differential'].map(kind=>({id:'questionnaire.analysis.'+kind,title:kind,delivery_kind:'analysis',status:'planned'}))
 const props={focused:true,version:v,files:[file('one'),file('two')],onNavigate:vi.fn()}
 const view=render(<AnalysisRequestList {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'differential'}))
 const row=within(screen.getByRole('article',{name:'differential'}))
 fireEvent.change(row.getByLabelText('分析方式'),{target:{value:'table'}})
 fireEvent.change(row.getByLabelText('本项使用的来源'),{target:{value:'file:two'}})
 view.unmount();render(<AnalysisRequestList {...props}/>);
 expect(screen.getByRole('article',{name:'differential'})).toBeTruthy()
 expect(within(screen.getByRole('article',{name:'differential'})).getByLabelText('本项使用的来源')).toHaveProperty('value','file:two')
 fireEvent.click(screen.getByRole('button',{name:'进入配置'}));expect(props.onNavigate).toHaveBeenCalledWith(expect.objectContaining({fileId:'two',view:'setup'}))
})
it('does not reuse choices in another project or requirement on a mounted list',()=>{
 const props={focused:true,version:{...version('qc',['one','two']),project_id:'p1'},files:[file('one'),file('two')],onNavigate:vi.fn()}
 const view=render(<AnalysisRequestList {...props}/>);fireEvent.change(screen.getByLabelText('本项使用的来源'),{target:{value:'file:two'}})
 view.rerender(<AnalysisRequestList {...props} version={{...props.version,project_id:'p2'}}/>);
 expect(screen.getByLabelText('本项使用的来源')).toHaveProperty('value','')
 view.rerender(<AnalysisRequestList {...props} version={{...props.version,id:'req2'}}/>);
 expect(screen.getByLabelText('本项使用的来源')).toHaveProperty('value','')
})
it('takes missing material associations directly to the material step',()=>{
 const onRequirements=vi.fn();render(<AnalysisRequestList version={version('qc',[])} files={[]} onNavigate={vi.fn()} onRequirements={onRequirements}/>);
 fireEvent.change(screen.getByLabelText('分析方式'),{target:{value:'table'}})
 fireEvent.click(screen.getByRole('button',{name:'补充材料关联'}));expect(onRequirements).toHaveBeenCalledWith('materials')
})
