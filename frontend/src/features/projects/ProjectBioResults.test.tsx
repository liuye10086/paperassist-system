import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectSummary from './ProjectSummary'
import type {ArtifactNavigation} from './analysisViews'
import BioAnalysisRuns from '../bioinformatics/BioAnalysisRuns'
import {rawFixture,processedFixture,runFixture} from '../bioinformatics/spatialFixtures'
import {summaryFixture} from '../../test/fixtures/summaryFixture'
import {clearApiSession,setApiSession} from '../../shared/api/client'

afterEach(()=>{cleanup();clearApiSession();vi.unstubAllGlobals()})
const raw={...rawFixture,parser_version:'single_cell_import_v1'}
const succeeded={...runFixture,raw_source:raw,result_source:{...processedFixture.source,raw_source:raw},task:{...runFixture.task,status:'succeeded' as const}}
const navigation:ArtifactNavigation={view:'list',artifactId:'',kind:'',page:1}
it('surfaces an existing bio result from step five when the generic artifact list is empty',async()=>{
 setApiSession('test','owner');const onAnalysisNavigate=vi.fn(),fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.includes('/bio-analysis-runs?')?{items:[runFixture,succeeded],total:2,page:1,page_size:50}:summaryFixture('p1','research')));vi.stubGlobal('fetch',fetcher)
 render(<ProjectSummary projectId="p1" projectType="research" view="artifacts" active artifactNavigation={navigation} onAnalysisNavigate={onAnalysisNavigate}/>)
 expect(await screen.findByRole('heading',{name:'生信分析结果与 Word'})).toBeTruthy();fireEvent.click(await screen.findByRole('button',{name:'打开固定处理结果'}));expect(onAnalysisNavigate).toHaveBeenCalledWith({view:'bio-result',fileId:'',processedId:'processed1',tab:'qc'})
 expect(screen.getByText('暂无通用分析图表或报告。')).toBeTruthy();expect(screen.queryByText('暂无已生成的分析图表或报告。')).toBeNull();expect(screen.queryByRole('button',{name:'查看空间分析运行与 QC 确认'})).toBeNull();expect(fetcher.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})
it('reads bio result history only while the current artifact list is visible',async()=>{
 setApiSession('test','owner');const onAnalysisNavigate=vi.fn(),fetcher=vi.fn(async(url:string)=>Response.json(url.includes('/bio-analysis-runs?')?{items:[succeeded],total:1,page:1,page_size:50}:summaryFixture('p1','research')));vi.stubGlobal('fetch',fetcher)
 const props={projectId:'p1',projectType:'research' as const,artifactNavigation:navigation,onAnalysisNavigate}
 const {rerender}=render(<ProjectSummary {...props} view="overview" active/>);await act(async()=>{});expect(fetcher.mock.calls.filter(([url])=>url.includes('/bio-analysis-runs?'))).toHaveLength(0)
 rerender(<ProjectSummary {...props} view="artifacts" active={false}/>);await act(async()=>{});expect(fetcher.mock.calls.filter(([url])=>url.includes('/bio-analysis-runs?'))).toHaveLength(0)
 rerender(<ProjectSummary {...props} view="artifacts" active/>);await screen.findByRole('button',{name:'打开固定处理结果'});expect(fetcher.mock.calls.filter(([url])=>url.includes('/bio-analysis-runs?'))).toHaveLength(1)
 rerender(<ProjectSummary {...props} view="artifacts" active artifactNavigation={{...navigation,view:'layout'}}/>);await act(async()=>{});expect(screen.queryByRole('heading',{name:'生信分析结果与 Word'})).toBeNull();expect(fetcher.mock.calls.filter(([url])=>url.includes('/bio-analysis-runs?'))).toHaveLength(1)
})
it('reuses the run-history pagination to find successful results beyond the first page',async()=>{
 setApiSession('test','owner');const onNavigate=vi.fn();vi.stubGlobal('fetch',vi.fn(async(url:string)=>{const page=Number(new URL(url,'http://localhost').searchParams.get('page'));return Response.json({items:page===1?[runFixture]:[succeeded],total:51,page,page_size:50})}))
 render(<BioAnalysisRuns projectId="p1" active resultsOnly title="生信分析结果与 Word" onNavigate={onNavigate}/>);await screen.findByText('本页暂无已完成的生信分析结果。');expect(screen.queryByRole('button',{name:'查看空间分析运行与 QC 确认'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:'下一页'}));fireEvent.click(await screen.findByRole('button',{name:'打开固定处理结果'}));expect(onNavigate).toHaveBeenCalledWith({view:'bio-result',fileId:'',processedId:'processed1',tab:'qc'})
})
