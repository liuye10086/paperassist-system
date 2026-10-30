import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import SendCollectionReportToWriting from './SendCollectionReportToWriting'
import {AnalysisWritingProvider} from './AnalysisWritingContext'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function packet(projectType:'sci'|'thesis'){
 const sources=['B','A'].flatMap(run=>[{kind:'analysis_run',id:'run'+run,file_id:'file1',role:'computed_results',label:run,sha256:'a'.repeat(64),download_url:null,content:{id:'run'+run,setup_revision:1}},{kind:'figure',id:'figure'+run,file_id:'file1',role:'image_observation',label:run,sha256:'b'.repeat(64),download_url:null,content:{analysis_run_id:'run'+run}}])
 sources.push({kind:'collection_report',id:'report1',file_id:'file1',role:'user_results',label:'Report',sha256:'c'.repeat(64),download_url:null,content:{text:'Saved collection report prose'}} as unknown as typeof sources[number])
 const groups=['B','A'].map(run=>({id:'analysis-run'+run,title:run,analysis_run_ids:['run'+run],figure_ids:['figure'+run]}))
 return {selection_kind:'collection_report',project_id:'p1',project_type:projectType,file_id:'file1',analysis_run_id:'runB',analysis_run_ids:['runB','runA'],setup_revision:1,report_status:'selected',collection_id:'collection1',collection_version_id:'version1',report_id:'report1',sources,results_group:groups[0],results_groups:groups,figure_notes:['B','A'].map(run=>({figure_id:'figure'+run,caption:'Caption '+run,panels:[]}))}
}
it.each(['sci','thesis'] as const)('selects saved collection version for %s with one read-only server request',async projectType=>{
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json(packet(projectType)));vi.stubGlobal('fetch',fetcher)
 const open=vi.fn();render(<AnalysisWritingProvider projectId="p1" projectType={projectType} onOpenWriting={open}><SendCollectionReportToWriting collectionId="collection1" versionId="version1" reportId="report1" disabled={false}/></AnalysisWritingProvider>)
 fireEvent.click(screen.getByRole('button',{name:projectType==='sci'?'送入SCI写作':'送入毕业论文写作'}))
 await waitFor(()=>expect(open).toHaveBeenCalledTimes(1))
 expect(fetcher.mock.calls).toHaveLength(1)
 expect(fetcher.mock.calls[0][0]).toBe('/api/v1/projects/p1/manuscripts/collection-report-selection')
 expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({collection_id:'collection1',collection_version_id:'version1',report_id:'report1'})
})
it('rejects a response for a different collection version without navigating',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...packet('sci'),collection_version_id:'latest-other'})))
 const open=vi.fn();render(<AnalysisWritingProvider projectId="p1" projectType="sci" onOpenWriting={open}><SendCollectionReportToWriting collectionId="collection1" versionId="version1" reportId="report1" disabled={false}/></AnalysisWritingProvider>)
 fireEvent.click(screen.getByRole('button',{name:'送入SCI写作'}));await screen.findByRole('alert');expect(open).not.toHaveBeenCalled()
})
