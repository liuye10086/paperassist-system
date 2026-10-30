import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {setLocale,translateForLocale,apiError} from './index'
import JournalGuideForm from '../../features/journals/JournalGuideForm'
import JournalFormatPanel from '../../features/journals/JournalFormatPanel'
import JournalSubmissionPanel from '../../features/journals/JournalSubmissionPanel'
import WritingAuthorization from '../../features/manuscripts/WritingAuthorization'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('translates missing ordinary messages and safe fallback identifiers in both languages',()=>{
 const cases={'正在提交……':'Submitting…','文件':'File','成果分页':'Artifact pagination','Kaplan–Meier 曲线':'Kaplan–Meier curve','正常':'Normal','已开始':'Started','处理中':'Processing','分析配置读取失败，请重试。':'Unable to load analysis configuration. Please try again.'}
 for(const [key,value] of Object.entries(cases)){expect(translateForLocale(key,'zh-CN')).toBe(key);expect(translateForLocale(key,'en')).toBe(value)}
 const error=apiError({code:'untrusted',message:'SECRET'},'固定新稿读取失败，请刷新。')
 expect(translateForLocale(error,'en')).toBe('Unable to load the fixed manuscript. Please refresh.')
})
it('retranslates a guide validation error without replacing user inputs or the saved identifier',()=>{
 render(<JournalGuideForm projectId="p1" profiles={[]} guides={[]} materials={[]} busy={false} onUnavailable={vi.fn()} onSave={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('指南名称'),{target:{value:'原始 draft'}})
 fireEvent.click(screen.getByText('登记作者指南新版本'))
 fireEvent.click(screen.getByRole('button',{name:'保存作者指南新版本'}))
 expect(screen.getByRole('alert').textContent).toContain('请补齐固定档案')
 act(()=>setLocale('en'))
 expect(screen.getByLabelText('Guide name')).toHaveProperty('value','原始 draft')
 expect(screen.getByRole('alert').textContent).toContain('Complete the fixed profile')
 expect(screen.getByRole('button',{name:'Save new author guide version'})).toBeTruthy()
 act(()=>setLocale('zh-CN'))
 expect(screen.getByRole('alert').textContent).toContain('请补齐固定档案')
 expect(screen.getByLabelText('指南名称')).toHaveProperty('value','原始 draft')
})
it('renders journal empty states and submission controls in English without changing record notes',()=>{
 setLocale('en')
 render(<><JournalFormatPanel projectId="p1" recommendations={[]} profiles={[]} guides={[]} targets={[]} checks={[]} manuscripts={[]} materials={[]} busy={false} onSaveGuide={vi.fn()} onConfirm={vi.fn()} onCheck={vi.fn()} onRetry={vi.fn()} onUnavailable={vi.fn()}/><JournalSubmissionPanel targets={[]} manuscripts={[]} history={{items:[],current_by_target:{}}} busy={false} onSave={vi.fn()}/></>)
 expect(screen.getByRole('heading',{name:'Target confirmation and guide checks'})).toBeTruthy()
 expect(screen.getByText('No target confirmations yet.')).toBeTruthy()
 expect(screen.getByText('No format checks yet.')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('Submission record note'),{target:{value:'研究者原始备注'}})
 act(()=>setLocale('zh-CN'))
 expect(screen.getByLabelText('投稿记录备注')).toHaveProperty('value','研究者原始备注')
})
it('translates authorization protocol states while preserving active authorization selection',async()=>{
 const auth={id:'a1',project_id:'p1',status:'active',revision:1,manifest_sha256:'a'.repeat(64),manifest:{tasks:Array.from({length:4},(_,i)=>({logical_task_id:`task-${i}`,bundles:[{bundle_id:`b-${i}`,bundle_sha256:"a".repeat(64)}]})),max_posts:6,max_corrections:2,cap_micro_usd:12000000,logical_task_cap_micro_usd:3000000,materials:[]},occupied_posts:0,occupied_micro_usd:0,logical_task_usage:[]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json({items:url.endsWith('writing-authorizations')?[auth]:[]})))
 const selected=vi.fn();render(<WritingAuthorization projectId="p1" onSelect={selected}/>)
 fireEvent.click(screen.getByRole('button',{name:'读取同项目稿件与授权'}))
 expect(await screen.findByRole('heading',{name:'a1 · 有效'})).toBeTruthy()
 fireEvent.change(screen.getByLabelText('明确选择已有授权'),{target:{value:'a1'}})
 act(()=>setLocale('en'))
 expect(screen.getByRole('heading',{name:'a1 · Active'})).toBeTruthy()
 expect(screen.getByLabelText('Explicitly select an existing authorization')).toHaveProperty('value','a1')
 expect(selected.mock.calls.at(-1)?.[0]).toEqual(auth)
})
it('keeps numeric validation bounds and guide rule drafts when the locale changes',()=>{
 render(<JournalGuideForm projectId="p1" profiles={[]} guides={[]} materials={[]} busy={false} onUnavailable={vi.fn()} onSave={vi.fn()}/>)
 fireEvent.click(screen.getByText('登记作者指南新版本'));fireEvent.click(screen.getByRole('button',{name:'添加规则'}))
 fireEvent.change(screen.getByLabelText('规则 1 类型'),{target:{value:'heading_line_spacing'}})
 fireEvent.change(screen.getByLabelText('规则 1 状态'),{target:{value:'known'}})
 fireEvent.change(screen.getByLabelText('规则 1 原文引文'),{target:{value:'Exact user original'}})
 fireEvent.change(screen.getByLabelText('规则 1 原文位置'),{target:{value:'line:1'}})
 fireEvent.change(screen.getByLabelText('规则 1 数值（倍）'),{target:{value:'9'}})
 fireEvent.click(screen.getByRole('button',{name:'保存作者指南新版本'}))
 expect(screen.getByRole('alert').textContent).toBe('数值范围须为 1–3 倍。')
 act(()=>setLocale('en'))
 expect(screen.getByRole('alert').textContent).toBe('Value must be within 1–3 multiples.')
 expect(screen.getByLabelText('Rule 1 Exact original quote')).toHaveProperty('value','Exact user original')
 expect(screen.getByLabelText('Rule 1 Original text location')).toHaveProperty('value','line:1')
 act(()=>setLocale('zh-CN'));expect(screen.getByRole('alert').textContent).toBe('数值范围须为 1–3 倍。')
})
it('preserves a fixed old target and manuscript selection across locale switches',()=>{
 const guide={id:'g1',name:'Original guide',source_version:'v1',requirements_version:'a'.repeat(64),article_types:['research'],requirements:[],extracted_requirements:[],source_type:'user_provided',source_status:'available',permission_status:'unknown',source_text:'原始指南',permission:'许可原文',conditions:'原始条件'}
 const target={id:'target-old',recommendation_id:'r-old',article_type:'research',candidate:{profile:{name:'原始期刊'}},guide,additional_guides:[],conflicts:[],decisions:[],warnings:[]}
 const check=vi.fn().mockResolvedValue(null)
 render(<JournalFormatPanel projectId="p1" recommendations={[]} profiles={[]} guides={[]} targets={[target] as never} checks={[]} manuscripts={[{id:'m-old',title:'用户稿件',versions:[{id:'v-old',revision:1,status:'published'},{id:'v-new',revision:2,status:'published'}]}] as never} materials={[]} busy={false} onSaveGuide={vi.fn()} onConfirm={vi.fn()} onCheck={check} onRetry={vi.fn()} onUnavailable={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('检查稿件版本'),{target:{value:'m-old:1'}})
 act(()=>setLocale('en'))
 expect(screen.getByLabelText('Manuscript version to check')).toHaveProperty('value','m-old:1')
 expect(screen.getByText('原始指南')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Check fixed manuscript version'}))
 expect(check).toHaveBeenCalledWith('target-old',{id:'m-old',revision:1})
})
