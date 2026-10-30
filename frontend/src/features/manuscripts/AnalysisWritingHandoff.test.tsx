import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectManuscripts from './ProjectManuscripts'
import * as types from './manuscriptTypes'
import {candidatesFixture,snapshotFixture} from './manuscriptFixtures'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const selected={project_id:'p1',project_type:'sci',file_id:'file1',analysis_run_id:'historicalA',setup_revision:1,report_status:'selected',sources:[
 {kind:'analysis_run',id:'historicalA',file_id:'file1',role:'computed_results',label:'Historical A',sha256:'a'.repeat(64),download_url:null,content:{}},
 {kind:'figure',id:'figureA',file_id:'file1',role:'image_observation',label:'Figure A',sha256:'b'.repeat(64),download_url:null,content:{}},
 {kind:'analysis_report',id:'reportA',file_id:'file1',role:'user_results',label:'Report A',sha256:'c'.repeat(64),download_url:null,content:{text:'Saved report prose'}}
],results_group:{id:'analysis-historicalA',title:'Historical A',analysis_run_ids:['historicalA'],figure_ids:['figureA']},figure_notes:[{figure_id:'figureA',caption:'Source caption',panels:[]}]} as unknown as types.AnalysisSelection

it('merges twice without replacing methods, citations, thesis mappings or manual captions',()=>{
 const input=types.emptyInput('User title','zh-CN');input.methods.procedures='Keep procedures';input.citation_draft={id:'cite1',revision:1};input.method_conflicts=[{field:'groups',values:['A','B'],note:'Keep note'}];input.figure_notes=[{figure_id:'figureA',caption:'Manual caption',panels:[{label:'A',description:'Manual panel'}]}]
 const original={...input,thesis:{confirmation_id:'school',profile_revision:1,chapter_mappings:[{chapter_id:'chapter',purpose:'results' as const,output_language:'project' as const,result_group_ids:['old-group']}]}}
 const merge=(types as unknown as {mergeAnalysisSelection:(input:types.ManuscriptInput,value:unknown)=>types.ManuscriptInput}).mergeAnalysisSelection
 expect(typeof merge).toBe('function')
 const once=merge(original,selected),twice=merge(once,selected)
 expect(twice).toEqual(once);expect(once.sources).toHaveLength(3);expect(once.results_groups).toHaveLength(1)
 for(const key of ['title','output_language','methods','citation_draft','method_conflicts','thesis','figure_notes'] as const)expect(once[key]).toEqual(original[key])
})

it('receives historical materials into the existing hidden draft and sends actual merged preview input without save/model calls',async()=>{
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/candidates')?candidatesFixture:url.endsWith('/preview')?snapshotFixture:{items:[]}));vi.stubGlobal('fetch',fetcher)
 const props={projectId:'p1',researchTopic:'Draft',outputLanguage:'en' as const,active:true}
 const view=render(<ProjectManuscripts {...props}/>);await screen.findByRole('checkbox',{name:'固定统计结果'})
 fireEvent.change(screen.getByLabelText('实验步骤'),{target:{value:'Original methods'}})
 view.rerender(<ProjectManuscripts {...props} active={false} {...{analysisSelection:selected}}/>)
 view.rerender(<ProjectManuscripts {...props} {...{analysisSelection:selected}}/>)
 await screen.findByText(/historicalA/)
 expect(screen.getByLabelText('实验步骤')).toHaveProperty('value','Original methods')
 expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(0)
 fireEvent.click(screen.getByRole('button',{name:'预览事实稿'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([u])=>u.endsWith('/preview'))).toBe(true))
 const payload=JSON.parse(String(fetcher.mock.calls.find(([u])=>u.endsWith('/preview'))![1]?.body))
 expect(payload.sources.map((s:{id:string})=>s.id)).toEqual(['historicalA','figureA','reportA'])
 expect(payload.methods.procedures).toBe('Original methods');expect(payload.results_groups[0].analysis_run_ids).toEqual(['historicalA'])
 expect(payload.figure_notes[0].caption).toBe('Source caption')
})

it('merges all collection groups in frozen order and preserves manual captions on resend',()=>{
 const input=types.emptyInput('Collection draft','en')
 input.figure_notes=[{figure_id:'figureA',caption:'My existing caption',panels:[]}]
 const groupB={id:'analysis-historicalB',title:'B',analysis_run_ids:['historicalB'],figure_ids:['figureB']}
 const packet={...selected,selection_kind:'collection_report',analysis_run_ids:['historicalB','historicalA'],results_groups:[groupB,selected.results_group],sources:[{...selected.sources[0],id:'historicalB'},{...selected.sources[1],id:'figureB'},...selected.sources],figure_notes:[{figure_id:'figureB',caption:'Collection B note',panels:[]},...selected.figure_notes]} as unknown as types.AnalysisSelection
 const once=types.mergeAnalysisSelection(input,packet),twice=types.mergeAnalysisSelection(once,packet)
 expect(once.results_groups.map(g=>g.id)).toEqual(['analysis-historicalB','analysis-historicalA'])
 expect(once.analysis_handoff_run_ids).toEqual(['historicalB','historicalA'])
 expect(once.figure_notes.map(n=>n.caption)).toEqual(['My existing caption','Collection B note'])
 expect(twice).toEqual(once)
})
