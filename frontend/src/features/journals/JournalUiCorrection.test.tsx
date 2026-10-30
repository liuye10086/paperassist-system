import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {setLocale} from '../../shared/i18n'
import JournalFormatPanel,{GuideView} from './JournalFormatPanel'
import JournalAdaptationPanel from './JournalAdaptationPanel'
import StorageDeletion from '../operations/StorageDeletion'

afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const guide={id:'guide1',name:'Original guide',source_version:'v1',requirements_version:'a'.repeat(64),article_types:['research'],requirements:[],extracted_requirements:[],source_type:'user_provided',source_status:'available',permission_status:'unknown',source_text:'原始指南',permission:'许可原文',conditions:'原始条件'}
const target={id:'target1',guide,additional_guides:[],synthetic:false}
const callbacks={onSaveGuide:vi.fn(),onConfirm:vi.fn(),onCheck:vi.fn(),onRetry:vi.fn(),onUnavailable:vi.fn()}
it.each([
 {code:'storage_quota_exceeded',zh:'存储配额不足；已有成果仍可读取，请调整配额后显式重试原操作。',en:'Storage quota exceeded; existing results remain readable. Adjust quota before explicitly retrying the original operation.'},
 {code:'PRIVATE_UNKNOWN_CODE',zh:'格式检查任务失败，请查看任务详情。',en:'Format check task failed. Please view task details.'},
])('renders the $code journal task error in both languages while preserving the fixed check',({code,zh,en})=>{
 const check={id:'check1',created_at:'2026-10-27',task:{id:'task1',status:'failed',revision:1,current_attempt:1,error_code:code,retry_count:0},input_snapshot:{target,manuscript:{id:'old-manuscript',revision:1,version_id:'version1'}},result:null}
 const before=JSON.stringify(check)
 render(<JournalFormatPanel projectId="p1" recommendations={[]} profiles={[]} guides={[]} targets={[]} checks={[check] as never} manuscripts={[]} materials={[]} busy={false} {...callbacks}/>)
 expect(screen.getByRole('alert').textContent).toContain(zh)
 act(()=>setLocale('en'));expect(screen.getByRole('alert').textContent).toContain(en)
 expect(screen.getByRole('alert').textContent).not.toContain('PRIVATE_UNKNOWN_CODE')
 act(()=>setLocale('zh-CN'));expect(screen.getByRole('alert').textContent).toContain(zh)
 expect(JSON.stringify(check)).toBe(before)
})
it('retains a custom requirement origin when translating known rule labels',()=>{
 const custom='University graduate school'
 const rule={id:'r1',key:'word_limit',value:3000,status:'known',quote:'User original quote',location:'line:1',article_type:null,count_method:null,origin:custom,note:''}
 const value={...guide,requirements:[rule]};const before=JSON.stringify(value)
 render(<GuideView guide={value as never} expanded/>)
 const displayed=()=>screen.queryByText((_,node)=>node?.tagName==='P'&&!!node.textContent?.includes(custom))
 expect(displayed()).toBeTruthy()
 act(()=>setLocale('en'));expect(displayed()?.textContent).toContain('Body word count');expect(displayed()).toBeTruthy()
 act(()=>setLocale('zh-CN'));expect(displayed()).toBeTruthy();expect(JSON.stringify(value)).toBe(before)
})
it.each(['validation','result'] as const)('keeps complete %s issue evidence beside its localized summary',branch=>{
 const issue={id:'numeric:paragraph:1',category:'numeric',severity:'error',message:'Reference numbering is not contiguous.',location:'paragraph:exact-1',actual:4.2,expected:3.2,source_evidence:[{id:'fact1',text:'原始来源证据'}]}
 const item={id:'adapt1',created_at:'2026-10-27',task:{id:'task1',status:'succeeded'},input_snapshot:{target_id:'target1',check_id:'check1',requirements_version:'a'.repeat(64),manuscript:{id:'m1',revision:1,version_id:'v1'},selected_action_ids:[],preview:{sections:[],actions:[],unexecuted:[]}},validation:branch==='validation'?{public_issues:[issue],public_check_version:3,candidate_sha256:'b'.repeat(64),can_publish:false}:null,result:branch==='result'?{actual_changes:[],unexecuted:[],public_issues:[issue],display_version:'journal_display_v1',output:{manuscript_id:'m1',version_id:'v2',revision:2,parent_version_id:'v1',task_id:'pub1'}}:null}
 const before=JSON.stringify(item)
 render(<JournalAdaptationPanel projectId="p1" active={false} checks={[]} targets={[]} manuscripts={[]} items={[item] as never} busy={false} onPreview={vi.fn()} onAdopt={vi.fn()} onRetry={vi.fn()} onUnavailable={vi.fn()}/>)
 const summary=screen.getByText('参考文献编号不连续。');expect(summary.tagName).toBe('SUMMARY')
 fireEvent.click(summary)
 const evidence=()=>screen.getByText((_,node)=>node?.tagName==='P'&&!!node.textContent?.includes('location: paragraph:exact-1'))
 expect(evidence().textContent).toContain('actual: 4.2');expect(evidence().textContent).toContain('expected: 3.2');expect(evidence().textContent).toContain('原始来源证据')
 act(()=>setLocale('en'));expect(screen.getByText(issue.message).tagName).toBe('SUMMARY');expect(evidence().textContent).toContain('source_evidence:')
 act(()=>setLocale('zh-CN'));expect(evidence().textContent).toContain('原始来源证据');expect(JSON.stringify(item)).toBe(before)
})
it('renders a known per-object deletion error rather than the generic fallback',async()=>{
 const plan={id:'plan1',project_id:'p1',file_id:null,scope_kind:'project',reason:'用户理由',manifest_sha256:'a'.repeat(64),state:'preview',physical_deletion_available:false,blockers:[],items:[{object_id:'o1',kind:'原始对象类型',size_bytes:1,sha256:'b'.repeat(64),action:'retain',state:'failed',reason_codes:['原始保留原因'],error_code:'storage_quota_exceeded'}],deleted_object_count:0,deleted_bytes:0}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(plan)))
 render(<StorageDeletion onForbidden={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('删除项目标识'),{target:{value:'p1'}});fireEvent.change(screen.getByLabelText('删除理由'),{target:{value:'用户理由'}});fireEvent.click(screen.getByRole('button',{name:'预览处置范围'}))
 expect(await screen.findByText('存储配额不足；已有成果仍可读取，请调整配额后显式重试原操作。')).toBeTruthy()
 act(()=>setLocale('en'));expect(screen.getByText('Storage quota exceeded; existing results remain readable. Adjust quota before explicitly retrying the original operation.')).toBeTruthy()
 expect(screen.getByText('原始对象类型')).toBeTruthy();expect(screen.getByText('原始保留原因')).toBeTruthy()
})
