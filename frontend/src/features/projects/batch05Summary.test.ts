import {expect,test} from 'vitest'
import {isProjectSummary} from './projectSummaryTypes'
import {summaryFixture} from '../../test/fixtures/summaryFixture'
const report={id:'report1',file_id:'file1',filename:'study.xlsx',analysis_run_id:null,setup_revision:null,current_revision:null,engine_version:'collection_word_v1',recorded_at:'2026-10-15T10:00:00Z',figure_id:null,explanation_id:null,kind:'report',collection_id:'collection1',collection_version_id:'version1',collection_revision:2,export_revision:3,collection_title:'Saved report',result_count:2,download_filename:'generated.docx',size_bytes:10,sha256:'a'.repeat(64),download_url:'/api/v1/projects/p1/report-collections/collection1/reports/report1/download'}
test('collection summary cannot masquerade as one analysis or authorize another resource download',()=>{
 const fixture=summaryFixture(),summary=(item:unknown)=>({...fixture,artifacts:{...fixture.artifacts,total:1,items:[item]}})
 expect(isProjectSummary(summary(report),'p1','sci',1,1)).toBe(true)
 for(const change of [{analysis_run_id:'pretend-single-run'},{setup_revision:1},{figure_id:'pretend-single-figure'},{download_url:'/api/v1/projects/p2/report-collections/collection1/reports/report1/download'},{download_url:'/api/v1/projects/p1/report-collections/other/reports/report1/download'},{result_count:0}])expect(isProjectSummary(summary({...report,...change}),'p1','sci',1,1)).toBe(false)
})
