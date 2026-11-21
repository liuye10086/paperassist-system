// B03 task 9: customer journal pages show business wording only, with no <details> folds.
// Each step scans the whole rendered tree (hidden task views included) with every fixture ID registered.
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {clearApiSession,setApiSession} from '../../shared/api/client'
import {setLocale,translate} from '../../shared/i18n'
import {findTechnicalText} from '../../test/technicalText'
import JournalAdaptationPanel from './JournalAdaptationPanel'
import JournalFormatPanel,{GuideView} from './JournalFormatPanel'
import JournalGuideForm from './JournalGuideForm'
import JournalOutput from './JournalOutput'
import JournalResults from './JournalResults'
import JournalSourceForm from './JournalSourceForm'
import JournalWorkspace from './JournalWorkspace'
import type {GuideRequest} from './formatContracts'
import {adaptation,adaptationOutput,check,guide,guide2,guideId,manuscripts,material,preview,profile,profileId,projectId,rawValues,recommendation,systemIds,target,checkId} from './journalCustomerFixtures'

const scan=()=>findTechnicalText(document.body,{systemIds,rawValues})
const folds=()=>document.querySelectorAll('details').length
const callbacks={onSaveGuide:vi.fn(),onConfirm:vi.fn(),onCheck:vi.fn(),onRetry:vi.fn(),onUnavailable:vi.fn()}

const extractionNote='有限固定行提取；仅反映登记原文，不认证来源真实性。'
const englishExtraction='These rules come from recognized lines in the supplied text. The source has not been authenticated.'

beforeEach(()=>{setApiSession('csrf','customer-test');vi.stubGlobal('fetch',vi.fn(async()=>Response.json({},{status:503})))})
afterEach(()=>{cleanup();setLocale('zh-CN');clearApiSession();vi.restoreAllMocks();vi.unstubAllGlobals()})

it.each([['en',englishExtraction],['zh-CN',extractionNote]] as const)('shows saved guide extraction notes in %s while preserving original text and manual notes',(locale,expected)=>{
 setLocale(locale)
 const extracted=[
  {...guide.requirements[0],id:'extracted:1',note:extractionNote},
  {...guide.requirements[0],id:'extracted:2',key:'figure_limit' as const,value:4,quote:'图数上限：4',location:'line:2',note:extractionNote},
 ]
 const manual={...guide.requirements[0],id:'custom-rule',note:extractionNote,quote:'客户手填引文'}
 const corrected={...manual,id:'extracted:3',note:'参考文献编号不连续。'}
 const sourceText=extracted.map(rule=>rule.quote).join('\n')
 const saved={...guide,source_text:sourceText,requirements:[...extracted,manual,corrected],extracted_requirements:extracted}
 const original=JSON.stringify(saved)
 render(<GuideView customer guide={saved as never}/>)
 const automatic=screen.getByRole('region',{name:locale==='en'?'Original automatic extraction':'自动提取的原始记录'})
 expect(within(automatic).getAllByText(expected)).toHaveLength(2)
 expect(within(automatic).getByText('图数上限：4',{selector:'blockquote'})).toBeTruthy()
 const visibleRules=screen.getByRole('article').querySelectorAll(':scope > .journal-evidence')
 expect(Array.from(visibleRules,element=>element.lastElementChild?.textContent)).toEqual([expected,expected,extractionNote,corrected.note])
 expect(screen.getByRole('article').querySelector('.journal-source-text')?.textContent).toBe(sourceText)
 expect(JSON.stringify(saved)).toBe(original)
})

it('translates automatic target decisions and conflicts while preserving customer reasons',()=>{
 setLocale('en')
 const priority='明确适用文章类型的专属条款优先同来源一般条款。'
 const conflict='不同来源或同范围条款存在冲突；请有限选择或暂缓并写理由。'
 const automatic={...target.decisions[0],reason:priority}
 const manual={...target.decisions[0],key:'figure_limit',reason:priority}
 const saved={...target,decisions:[automatic,manual],
  resolutions:[{key:manual.key,requirement_id:manual.selected_id,reason:manual.reason}],
  conflicts:[{...target.conflicts[0],reason:conflict,deferred:false},{...target.conflicts[0],key:'figure_limit',reason:conflict,deferred:true}]}
 render(<JournalFormatPanel customerSci projectId={projectId} recommendations={[recommendation] as never} profiles={[profile] as never} guides={[guide] as never} targets={[saved] as never} checks={[]} manuscripts={manuscripts} materials={[]} busy={false} {...callbacks}/>)
 expect(screen.getByText(/An explicitly applicable article-specific requirement/)).toBeTruthy()
 expect(screen.getByText(/Requirements from different sources or within the same scope conflict/)).toBeTruthy()
 expect(screen.getAllByText(new RegExp(priority))).toHaveLength(1)
 expect(screen.getAllByText(new RegExp(conflict))).toHaveLength(1)
})

it('reads a historical target without resolution metadata and retains its recorded decision reason',()=>{
 setLocale('en')
 const saved={...target,resolutions:undefined}
 render(<JournalFormatPanel customerSci projectId={projectId} recommendations={[recommendation] as never} profiles={[profile] as never} guides={[guide] as never} targets={[saved] as never} checks={[]} manuscripts={manuscripts} materials={[]} busy={false} {...callbacks}/>)
 expect(screen.getByText(/以期刊要求为准/)).toBeTruthy()
})

it.each(['zh-CN','en'] as const)('shows the guide edition and finding details without the internal rules version in %s',locale=>{
 setLocale(locale)
 const issue={...check.result.public_issues[0],rules_version:'manuscript-review-v1'}
 const sourceVersion='QA guide 2026'
 const rule={...guide.requirements[0],source_id:guideId,source_version:sourceVersion}
 const item={...check.result.items[0],evidence:[rule],actual:{public_violations:[issue]}}
 const saved={...check,result:{...check.result,public_issues:[issue],items:[item]}}
 const before=JSON.stringify(saved)
 const {rerender}=render(<JournalFormatPanel customerSci projectId={projectId} recommendations={[]} profiles={[]} guides={[]} targets={[]} checks={[saved] as never} manuscripts={[]} materials={[]} busy={false} {...callbacks}/>)
 const current=screen.getByRole('region',{name:translate('当前格式检查')})
 expect(current.textContent).toContain(translate('参考文献编号不连续。'))
 expect(current.textContent).toContain('4.2')
 expect(current.textContent).not.toContain(issue.rules_version)
 expect(current.textContent).toContain(translate('指南来源版本')+' · '+sourceVersion)
 rerender(<JournalFormatPanel projectId={projectId} recommendations={[]} profiles={[]} guides={[]} targets={[]} checks={[saved] as never} manuscripts={[]} materials={[]} busy={false} {...callbacks}/>)
 expect(screen.getByRole('region',{name:translate('当前格式检查')}).textContent).toContain(issue.rules_version)
 expect(JSON.stringify(saved)).toBe(before)
})

it('shows a suggestion batch, its inputs and candidate evidence without IDs or folds',()=>{
 render(<JournalResults customerSci item={{...recommendation,task:{...recommendation.task,status:'failed',display_status:'failed',error_code:'task_failed'}} as never} busy={false} projectId={projectId} onRetry={vi.fn()}/>)
 expect(screen.getByRole('heading',{name:'心衰队列研究',level:3})).toBeTruthy()
 expect(screen.getByText(/建议任务失败/).textContent).not.toContain('task_failed')
 expect(screen.queryByText(/任务版本|尝试次数/)).toBeNull()
 expect(folds()).toBe(0)
 expect(scan()).toEqual([])
})

it('walks guide material, target confirmation history and format checks without IDs or folds',async()=>{
 render(<JournalFormatPanel customerSci taskLayout projectId={projectId} recommendations={[recommendation] as never} profiles={[profile] as never} guides={[guide,guide2] as never} targets={[target] as never} checks={[check] as never} manuscripts={manuscripts} materials={[material]} busy={false} {...callbacks}/>)
 fireEvent.click(screen.getByRole('button',{name:/Author guidelines.*2026 版/}))
 expect(screen.getAllByText('Maximum body words: 3000',{selector:'blockquote'}).length).toBeGreaterThan(0)
 expect(folds()).toBe(0);expect(scan()).toEqual([])
 fireEvent.click(screen.getByRole('button',{name:'确认目标'}))
 expect(within(screen.getByLabelText('检查稿件版本')).getByRole('option',{name:/心衰队列研究稿 · 第 1 版 · .*2026/})).toBeTruthy()
 fireEvent.change(screen.getByLabelText('目标候选'),{target:{value:profileId}})
 fireEvent.change(screen.getByLabelText('主指南版本'),{target:{value:guideId}})
 fireEvent.click(screen.getByLabelText(/附加指南.*2026 单位版/))
 expect(screen.getAllByText(/以期刊要求为准/).length).toBeGreaterThan(0)
 expect(screen.queryByText(/确认人/)).toBeNull()
 expect(folds()).toBe(0);expect(scan()).toEqual([])
 fireEvent.click(screen.getByRole('button',{name:'检查历史'}))
 const current=screen.getByRole('region',{name:'当前格式检查'})
 expect(within(current).getByText('参考文献编号不连续。')).toBeTruthy()
 expect(current.textContent).not.toMatch(/真实模型调用|任务版本|尝试/)
 expect(folds()).toBe(0);expect(scan()).toEqual([])
})

it('previews and reports an adaptation with validation and result without IDs or folds',async()=>{
 const onPreview=vi.fn(async()=>preview as never)
 render(<JournalAdaptationPanel customerSci projectId={projectId} active checks={[check] as never} targets={[target] as never} manuscripts={manuscripts} items={[adaptation] as never} busy={false} onPreview={onPreview} onAdopt={vi.fn()} onRetry={vi.fn()} onUnavailable={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('适配成功检查'),{target:{value:checkId}})
 expect(within(screen.getByLabelText('适配稿件版本')).getByRole('option',{name:/心衰队列研究稿 · 第 1 版 · .*2026/})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'预览固定稿件适配'}))
 await screen.findByRole('region',{name:'七部分差异预览'})
 expect(screen.getAllByText(/材料与方法/).length).toBeGreaterThan(0)
 expect(screen.getAllByText(/页码与连续行号/).length).toBeGreaterThan(0)
 expect(screen.getAllByText('参考文献编号不连续。').length).toBe(2)
 expect(folds()).toBe(0);expect(scan()).toEqual([])
})

it('labels the adapted output by version only',async()=>{
 render(<JournalOutput customerSci projectId={projectId} adaptationId={adaptation.id} output={adaptationOutput} active onUnavailable={vi.fn()}/>)
 await screen.findByRole('alert')
 expect(screen.getByRole('region',{name:'固定公共新稿与导出'}).textContent).toContain('第 2 版')
 expect(scan()).toEqual([])
})

it('registers an author guide only by pasting the original text, with one example sentence',async()=>{
 const save=vi.fn(async(_value:GuideRequest)=>true)
 render(<JournalGuideForm customerSci taskLayout projectId={projectId} profiles={[profile] as never} guides={[guide] as never} materials={[material]} busy={false} onSave={save} onUnavailable={vi.fn()}/>)
 expect(document.querySelector('pre')).toBeNull()
 expect(screen.queryByText(/section_id=display_name/)).toBeNull()
 expect(screen.getByText(/例如/)).toBeTruthy()
 expect(screen.queryByLabelText('指南公共材料版本')).toBeNull()
 expect(screen.queryByLabelText(/提取有限明确行/)).toBeNull()
 fireEvent.change(screen.getByLabelText('基于指南另存版本'),{target:{value:guideId}})
 fireEvent.click(screen.getByRole('button',{name:'添加规则'}))
 fireEvent.change(screen.getByLabelText('规则 2 类型'),{target:{value:'section_display_names'}})
 expect(screen.getByLabelText('规则 2 材料与方法 显示名称')).toBeTruthy()
 expect(folds()).toBe(0);expect(scan()).toEqual([])
 fireEvent.change(screen.getByLabelText('规则 2 类型'),{target:{value:'reference_style'}})
 fireEvent.change(screen.getByLabelText('规则 2 状态'),{target:{value:'known'}})
 fireEvent.change(screen.getByLabelText('规则 2 引用样式'),{target:{value:'NLM'}})
 fireEvent.change(screen.getByLabelText('规则 2 原文引文'),{target:{value:'Reference style: NLM'}})
 fireEvent.change(screen.getByLabelText('规则 2 原文所在行'),{target:{value:'3'}})
 fireEvent.click(screen.getByRole('button',{name:'保存作者指南新版本'}))
 await waitFor(()=>expect(save).toHaveBeenCalledOnce())
 const sent=save.mock.calls[0][0]
 expect(sent).toMatchObject({extract:true,material:null,previous_version_id:guideId})
 expect(sent.requirements.at(-1)).toMatchObject({key:'reference_style',value:'NLM',location:'line:3'})
 expect(sent.requirements[0]).toMatchObject({location:'line:1'})
})

it('registers journal sources with every field shown and no IDs',()=>{
 render(<JournalSourceForm customerSci projectId={projectId} profiles={[profile] as never} materials={[material]} busy={false} onSave={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('费用状态'),{target:{value:'verified'}})
 expect(screen.getByLabelText('费用金额')).toBeTruthy()
 expect(folds()).toBe(0);expect(scan()).toEqual([])
})

it('requires pasted text when a customer saves a new version of an older file-backed journal source',async()=>{
 const save=vi.fn(async()=>true)
 const older={...profile,source_text:'',fields:{}}
 render(<JournalSourceForm customerSci projectId={projectId} profiles={[older]} materials={[material]} busy={false} onSave={save}/>)
 fireEvent.change(screen.getByLabelText('以已有资料另存新版本'),{target:{value:profileId}})
 expect(screen.queryByLabelText('来源公共资料（可选）')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'保存期刊资料新版本'}))
 expect(screen.getByRole('alert').textContent).toBe('请粘贴来源原文。')
 expect(save).not.toHaveBeenCalled()
 fireEvent.change(screen.getByLabelText('来源原文'),{target:{value:'New pasted instructions.'}})
 fireEvent.click(screen.getByRole('button',{name:'保存期刊资料新版本'}))
 await waitFor(()=>expect(save).toHaveBeenCalledOnce())
 expect(save).toHaveBeenCalledWith(expect.objectContaining({previous_version_id:profileId,source_text:'New pasted instructions.',material:null}))
})

it('shows a paste-only instruction in English when journal source text is missing',()=>{
 setLocale('en')
 const save=vi.fn()
 render(<JournalSourceForm customerSci projectId={projectId} profiles={[]} materials={[]} busy={false} onSave={save}/>)
 fireEvent.submit(screen.getByRole('form'))
 expect(screen.getByRole('alert').textContent).toBe('Paste the source text.')
 expect(save).not.toHaveBeenCalled()
})

it('asks for the location in the pasted source when the old quotation pointed to a file item',async()=>{
 const save=vi.fn(async()=>true)
 const older={...profile,source_type:'official_local' as const,fields:{topics:{...profile.fields.topics,location:profile.material.content.items[0].id}}}
 render(<JournalSourceForm customerSci projectId={projectId} profiles={[older]} materials={[material]} busy={false} onSave={save}/>)
 fireEvent.change(screen.getByLabelText('以已有资料另存新版本'),{target:{value:profileId}})
 const location=screen.getByLabelText<HTMLInputElement>('原文位置')
 expect(location.value).toBe('')
 fireEvent.click(screen.getByRole('button',{name:'保存期刊资料新版本'}))
 expect(save).not.toHaveBeenCalled()
 fireEvent.change(location,{target:{value:'第 1 行'}})
 fireEvent.click(screen.getByRole('button',{name:'保存期刊资料新版本'}))
 await waitFor(()=>expect(save).toHaveBeenCalledOnce())
 expect(save).toHaveBeenCalledWith(expect.objectContaining({source_type:'user_provided',fields:expect.objectContaining({
  topics:expect.objectContaining({quote:'Scope: cardiology',location:'第 1 行'}),
 })}))
})

function serveWorkspace(){vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
 const path=url.split('?')[0]
 if(path.endsWith('/journals/config'))return Response.json({workflow_version:'journal_recommendation_v1',metrics_enabled:false,real_model_calls:false,real_network_calls:false,default_limit:3,max_limit:5,configuration:{status:'legacy_unbound',version_id:null,sha256:null}})
 if(path.endsWith('/journals/profiles'))return Response.json({items:[profile]})
 if(path.endsWith('/journals/recommendations'))return Response.json({items:[recommendation]})
 if(path.endsWith('/journals/guides'))return Response.json({items:[guide,guide2]})
 if(path.endsWith('/journals/targets'))return Response.json({items:[target]})
 if(path.endsWith('/journals/checks'))return Response.json({items:[check]})
 if(path.endsWith('/manuscripts'))return Response.json({items:manuscripts})
 return Response.json({items:[]})
}))}

it('hides development notes and IDs in the customer overview and suggestion history',async()=>{
 serveWorkspace()
 const view=render(<JournalWorkspace customerSci={null} projectId={projectId} active view="overview"/>)
 await screen.findByRole('heading',{name:'期刊建议'})
 await waitFor(()=>expect(screen.queryByText('正在读取期刊资料……')).toBeNull())
 expect(document.body.textContent).not.toContain('真实模型调用')
 view.rerender(<JournalWorkspace customerSci={null} projectId={projectId} active view="recommendations"/>)
 fireEvent.click(await screen.findByRole('button',{name:/心衰队列研究/}))
 await screen.findByRole('heading',{name:'心衰队列研究',level:3})
 view.rerender(<JournalWorkspace customerSci={null} projectId={projectId} active view="sources"/>)
 fireEvent.click(screen.getByRole('button',{name:/Frontiers in Cardiovascular Medicine/}))
 await waitFor(()=>expect(screen.getAllByText('Scope: cardiology').length).toBeGreaterThan(0))
 view.rerender(<JournalWorkspace customerSci={null} projectId={projectId} active view="guidelines"/>)
 expect(folds()).toBe(0);expect(scan()).toEqual([])
})

it('keeps analyst journal pages unchanged',()=>{
 render(<JournalFormatPanel taskLayout projectId={projectId} recommendations={[recommendation] as never} profiles={[profile] as never} guides={[guide] as never} targets={[target] as never} checks={[check] as never} manuscripts={manuscripts} materials={[material]} busy={false} {...callbacks}/>)
 expect(screen.getByText(new RegExp(`确认人.*${target.confirmed_by}`))).toBeTruthy()
 expect(screen.getByText(/格式检查版本 1/)).toBeTruthy()
})

it('shows the customer guide wording in English',()=>{
 setLocale('en')
 render(<JournalGuideForm customerSci taskLayout projectId={projectId} profiles={[profile] as never} guides={[guide] as never} materials={[material]} busy={false} onSave={vi.fn()} onUnavailable={vi.fn()}/>)
 expect(screen.getByRole('heading',{name:'Register author guide'})).toBeTruthy()
 expect(screen.getByText(/For example, put each requirement on its own line/)).toBeTruthy()
 // In English only snake_case raw values count: words such as guide or check are normal English there.
 expect(findTechnicalText(document.body,{systemIds,rawValues:rawValues.filter(v=>v.includes('_'))})).toEqual([])
})
