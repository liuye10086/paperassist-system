import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import AnalysisGuide from './AnalysisGuide'
import {entryMethods} from './analysisEntryState'
import type {Version} from '../research-intake/contracts'

afterEach(cleanup)
const version:Version={id:'r1',version:1,operation:'save',created_at:'',sha256:'x',content:{schema_version:1,scope_items:['multiomics','candidates'].map(kind=>({id:'questionnaire.analysis.'+kind,title:kind,delivery_kind:'analysis',status:'planned'}))}}
const props={version,files:[],loading:false,error:'',filesLoading:false,filesError:'',imports:[],importsUnknown:false,importsError:'',onRefresh:vi.fn(),onReloadFiles:vi.fn(),onNavigate:vi.fn(),onFile:vi.fn()}
it('focuses one saved task and separates existing analyses without new computation',()=>{
 render(<AnalysisGuide {...props}/>);
 expect(screen.getByRole('article',{name:'multiomics'})).toBeTruthy()
 expect(screen.queryByRole('article',{name:'candidates'})).toBeNull()
 expect(screen.queryByRole('button',{name:/表格数据与统计/})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'candidates'}))
 expect(screen.getByRole('article',{name:'candidates'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'已有分析'}))
 expect(screen.queryByRole('article',{name:'candidates'})).toBeNull()
 expect(screen.getByRole('button',{name:/统计结果/})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'本次任务'}))
 expect(screen.getByRole('article',{name:'candidates'})).toBeTruthy()
 expect(props.onNavigate).not.toHaveBeenCalled()
})
it('starts new table comparisons and validation with configuration rather than skipping to results',()=>{
 for(const kind of ['differential','validation'])expect(entryMethods(kind).find(m=>m.id==='table')?.navigation.view).toBe('setup')
})
it('asks for an analysis method before deciding that source material is missing',()=>{
 const differential={...version,content:{...version.content,scope_items:[{id:'questionnaire.analysis.differential',title:'差异分析',delivery_kind:'analysis' as const,status:'planned' as const}]}}
 render(<AnalysisGuide {...props} version={differential} onRequirements={vi.fn()}/>);
 expect(screen.getByText('需选择分析方式')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'补充材料关联'})).toBeNull()
 expect(screen.getByRole('button',{name:'进入配置'})).toHaveProperty('disabled',true)
 fireEvent.change(screen.getByLabelText('分析方式'),{target:{value:'table'}})
 expect(screen.getByRole('button',{name:'补充材料关联'})).toHaveProperty('disabled',false)
})

it('keeps bioinformatics history reachable independently of the current task',()=>{
 const navigate=vi.fn();render(<AnalysisGuide {...props} onNavigate={navigate}/>);
 fireEvent.click(screen.getByRole('button',{name:'已有分析'}))
 fireEvent.click(screen.getByRole('button',{name:/生信计划与运行/}))
 expect(navigate).toHaveBeenCalledWith({view:'bio-insight-plan',fileId:''})
})
