import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {BindingEvidence,DiffEvidence} from './ConfigurationEvidence'
import ConfigurationDomainForms from './ConfigurationDomainForms'
import {testBundle,testCatalog} from './configurationTestFixtures'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();setLocale('zh-CN');vi.unstubAllGlobals()})
it.each(['zh-CN','en'] as const)('shows installed workflow nodes and templates as bilingual read-only capability evidence (%s)',locale=>{
 setLocale(locale);const catalog={...testCatalog,installed:{...testCatalog.installed,workflows:[{id:'installed-v1',editable:false,nodes:['material','policy','authorization','admission','provider','validation']}],templates:['sci-writing-v1','sci-writing-v2','literature_assistance_v1']}}
 render(<ConfigurationDomainForms domain="prompts" bundle={testBundle} catalog={catalog} onChange={()=>{}}/>);const summary=screen.getByText(locale==='en'?'Installed workflow and template scope':'已安装工作流与模板范围');expect(summary.closest('details')?.open).toBe(false);expect(screen.getByText(locale==='en'?'Materials':'材料准备')).toBeTruthy();expect(screen.getByText(locale==='en'?'User authorization':'用户授权')).toBeTruthy();expect(screen.getByText(locale==='en'?'Output validation':'输出验证')).toBeTruthy();expect(screen.getByText(locale==='en'?'Manuscript writing template (v2)':'论文写作模板（v2）')).toBeTruthy();expect(screen.queryByRole('button',{name:/添加节点|Add node/})).toBeNull()
})
it.each(['zh-CN','en'] as const)('translates finite diff values by path and preserves user text and version identifiers (%s)',locale=>{
 setLocale(locale);render(<DiffEvidence diff={{version_id:'v2',against:'v1',changes:[{path:'journals.update_result',before:'recorded',after:'failed'},{path:'models.writing.price_source',before:'installed_code',after:'synthetic_fixture'},{path:'models.writing.price_status',before:'unverified',after:'synthetic'},{path:'review.default_language',before:'zh-CN',after:'en'},{path:'review.category_order',before:['experiment','statistics'],after:['statistics','experiment']},{path:'schools.heading_aliases',before:[],after:[{text:'body',role:'heading1'}]},{path:'prompts.writing_instruction',before:'',after:'synthetic_fixture'},{path:'models.writing.execution.policy.price.version',before:'old',after:'unverified'}]}}/>);
 const cells=(path:string)=>within(screen.getByText(path).closest('tr')!).getAllByRole('cell')
 expect(cells('journals.update_result')[1].textContent).toBe(locale==='en'?'Update failed':'更新失败');expect(cells('models.writing.price_source')[1].textContent).toBe(locale==='en'?'Synthetic acceptance fixtures':'合成验收样例');expect(cells('models.writing.price_status')[0].textContent).toBe(locale==='en'?'Source unverified':'来源尚未核实');expect(cells('review.default_language')[1].textContent).toBe(locale==='en'?'English':'英语');expect(cells('review.category_order')[1].textContent).toContain(locale==='en'?'Experiment':'实验');expect(cells('schools.heading_aliases')[1].textContent).toContain(locale==='en'?'Heading 1':'一级标题');expect(cells('schools.heading_aliases')[1].textContent).toContain('body');expect(cells('prompts.writing_instruction')[1].textContent).toBe('synthetic_fixture');expect(cells('models.writing.execution.policy.price.version')[1].textContent).toBe('unverified')
})
it('aborts hidden binding reads, ignores their late response and retains query inputs for resuming',async()=>{
 let finish!:(response:Response)=>void;let signal:AbortSignal|undefined
 const fetch=vi.fn((_url:string,init?:RequestInit)=>{signal=init?.signal as AbortSignal;return new Promise<Response>(resolve=>{finish=resolve})});vi.stubGlobal('fetch',fetch)
 const onForbidden=vi.fn(),view=render(<BindingEvidence onForbidden={onForbidden} active/>)
 fireEvent.change(screen.getByLabelText('绑定对象标识'),{target:{value:'retained-task'}});fireEvent.click(screen.getByRole('button',{name:'查询安全绑定'}));await waitFor(()=>expect(finish).toBeTypeOf('function'))
 view.rerender(<BindingEvidence onForbidden={onForbidden} active={false}/>);expect(signal?.aborted).toBe(true);await act(async()=>finish(Response.json({status:'bound',version_id:'late-version',sha256:'late-sha'})))
 expect(screen.queryByText('late-version')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'查询安全绑定'}));expect(fetch).toHaveBeenCalledTimes(1)
 view.rerender(<BindingEvidence onForbidden={onForbidden} active/>);expect(screen.getByLabelText('绑定对象标识')).toHaveProperty('value','retained-task');expect(screen.getByRole('button',{name:'查询安全绑定'})).toHaveProperty('disabled',false)
})
