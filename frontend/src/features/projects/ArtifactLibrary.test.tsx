import type { ProjectSummaryData } from './projectSummaryTypes'
import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ArtifactLibrary from './ArtifactLibrary'
import ProjectSummary from './ProjectSummary'
import type { ArtifactNavigation } from './analysisViews'
import { summaryFixture } from '../../test/fixtures/summaryFixture'
import { clearApiSession, setApiSession } from '../../shared/api/client'

afterEach(()=>{cleanup();clearApiSession();vi.unstubAllGlobals()})
const fixture=()=>{
  const data=summaryFixture() as ProjectSummaryData
  data.artifacts={items:(['figure','report'] as const).map(kind=>({kind,id:'same-id',file_id:'file1',filename:'研究.xlsx',analysis_run_id:'old-run',setup_revision:2,current_revision:4,engine_version:'engine-1',recorded_at:'2026-10-26T00:00:00Z',figure_id:null,explanation_id:null,download_filename:kind==='figure'?'固定图.png':'固定报告.docx',size_bytes:200,sha256:'a'.repeat(64),download_url:`/api/v1/projects/p1/files/file1/analysis-runs/old-run/${kind==='figure'?'figures':'report'}/same-id/download`})),total:2,page:1,page_size:10}
  return data
}
function Library(){
  const [navigation,onNavigate]=useState<ArtifactNavigation>({view:'list',artifactId:'',kind:'',page:1})
  return <ArtifactLibrary projectId="p1" data={fixture()} navigation={navigation} onNavigate={onNavigate}/>
}
it('opens only the selected artifact and retains the historical run download',()=>{
  render(<Library/>);expect(screen.queryByRole('region',{name:'成果详情'})).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'查看成果 固定报告.docx'}))
  expect(screen.getByRole('region',{name:'成果详情'}).textContent).toContain('历史结果')
  expect(screen.queryByRole('button',{name:'查看成果 固定图.png'})).toBeNull()
  expect(screen.getByRole('link',{name:'下载成果 固定报告.docx'}).getAttribute('href')).toContain('/old-run/report/same-id/download')
  fireEvent.click(screen.getByRole('button',{name:'成果列表'}))
  expect(screen.getByRole('button',{name:'查看成果 固定图.png'})).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'排版导出记录'}))
  expect(screen.getByText('尚无排版导出记录。')).toBeTruthy()
  expect(screen.queryByRole('button',{name:'查看成果 固定图.png'})).toBeNull()
})
it('does not substitute another artifact when a fixed identifier disappears',()=>{
  render(<ArtifactLibrary projectId="p1" data={fixture()} navigation={{view:'detail',artifactId:'missing',kind:'figure',page:1}} onNavigate={()=>{}}/>);
  expect(screen.getByRole('alert').textContent).toContain('不会替换为其他版本')
  expect(screen.queryByRole('link')).toBeNull()
})
it('loads the route page before displaying a fixed artifact detail',async()=>{
  setApiSession('artifact-test')
  const fetch=vi.fn(async(url:string)=>{
    const page=Number(new URL(url,'http://localhost').searchParams.get('artifact_page'))
    const data=fixture();data.artifacts={...data.artifacts,total:12,page}
    return Response.json(data)
  })
  vi.stubGlobal('fetch',fetch)
  render(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" artifactNavigation={{view:'detail',artifactId:'same-id',kind:'figure',page:2}} onArtifactNavigate={()=>{}}/>);
  expect(await screen.findByRole('region',{name:'成果详情'})).toBeTruthy()
  expect(fetch.mock.calls[0][0]).toContain('artifact_page=2')
  expect(screen.getByRole('link',{name:'下载成果 固定图.png'}).getAttribute('href')).toContain('old-run')
})
