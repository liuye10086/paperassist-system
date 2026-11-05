import { cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ResearchWorkspace from './ResearchWorkspace'
import { useResearchRead } from './api'

vi.mock('./api', async load => ({ ...await load<object>(), useResearchRead: vi.fn() }))
vi.mock('../school-templates/SchoolTemplates', () => ({ default: ({ active }: { active: boolean }) => active ? <p>学校模板工作区</p> : null }))
vi.mock('./ResearchFindings', () => ({ default: () => null }))
vi.mock('./ResearchFigureComposer', () => ({ default: () => null }))
vi.mock('./ResearchReport', () => ({ default: () => null }))
vi.mock('./ResearchWritingHandoff', () => ({ default: () => null }))
vi.mock('./ResearchCandidateReview', () => ({ default: () => null }))
vi.mock('./ResearchPublished', () => ({ default: () => null }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('opens school settings after the results action automatically selects thesis writing', async () => {
  const data = { deliveries: [{ id: 'thesis-delivery', kind: 'thesis_draft', active: true, name: 'thesis_draft' }] }
  vi.mocked(useResearchRead).mockReturnValue({ data, error: '', loading: false, loadingMessage: '', valid: true, refresh: vi.fn() })
  const props = { projectId: 'p1', projectType: 'research' as const, active: true, preferredDeliveryKind: 'thesis_draft' as const,
    section: 'manuscripts' as const, analysis: { view: 'overview' as const, fileId: '' }, artifact: { view: 'list' as const, artifactId: '', kind: '' as const, page: 1 },
    manuscriptView: 'research-selection' as const, manuscriptId: '', revision: 0, schoolNavigation: { view: 'list' as const, templateId: '' },
    onAnalysis: vi.fn(), onArtifact: vi.fn(), onManuscriptView: vi.fn(), onCandidate: vi.fn(), onPublished: vi.fn(), onSchoolNavigate: vi.fn() }
  const view = render(<ResearchWorkspace {...props} />)
  await waitFor(() => expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe('thesis-delivery'))
  view.rerender(<ResearchWorkspace {...props} section="school-templates" />)
  expect(await screen.findByText('学校模板工作区')).toBeTruthy()
  expect(screen.queryByText('thesis_draft')).toBeNull()
})

it('passes the fixed source and selected delivery to writing materials and persists delivery changes',async()=>{
 const data={deliveries:[{id:'d1',kind:'sci_draft',active:true},{id:'d2',kind:'thesis_draft',active:true}]}
 vi.mocked(useResearchRead).mockReturnValue({data,error:'',loading:false,loadingMessage:'',valid:true,refresh:vi.fn()})
 const onWritingDelivery=vi.fn(),onReturnSource=vi.fn(),source={kind:'research_report_version' as const,id:'r1'}
 render(<ResearchWorkspace projectId="p1" projectType="research" active section="manuscripts" analysis={{view:'overview',fileId:''}} artifact={{view:'list',artifactId:'',kind:'',page:1}} manuscriptView="research-selection" manuscriptId="" revision={0} schoolNavigation={{view:'list',templateId:''}} onAnalysis={vi.fn()} onArtifact={vi.fn()} onManuscriptView={vi.fn()} onCandidate={vi.fn()} onPublished={vi.fn()} onSchoolNavigate={vi.fn()} writingSource={source} writingDeliveryId="d1" onWritingDelivery={onWritingDelivery} onReturnSource={onReturnSource}/> )
 await waitFor(()=>expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe('d1'))
 fireEvent.change(screen.getByLabelText('已启用的稿件交付'),{target:{value:'d2'}});expect(onWritingDelivery).toHaveBeenCalledWith('d2')
})


it('clears a previous delivery when history restores a writing link without one',async()=>{
 const data={deliveries:[{id:'d1',kind:'sci_draft',active:true},{id:'d2',kind:'thesis_draft',active:true}]};vi.mocked(useResearchRead).mockReturnValue({data,error:'',loading:false,loadingMessage:'',valid:true,refresh:vi.fn()})
 const props={projectId:'p1',projectType:'research' as const,active:true,section:'manuscripts' as const,analysis:{view:'overview' as const,fileId:''},artifact:{view:'list' as const,artifactId:'',kind:'' as const,page:1},manuscriptView:'research-selection' as const,manuscriptId:'',revision:0,schoolNavigation:{view:'list' as const,templateId:''},onAnalysis:vi.fn(),onArtifact:vi.fn(),onManuscriptView:vi.fn(),onCandidate:vi.fn(),onPublished:vi.fn(),onSchoolNavigate:vi.fn(),onWritingDelivery:vi.fn()}
 const view=render(<ResearchWorkspace {...props} writingDeliveryId="d1"/>);await waitFor(()=>expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe('d1'))
 view.rerender(<ResearchWorkspace {...props}/>);await waitFor(()=>expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe(''))
})

it('shows an intake read error without claiming that no writing delivery exists',()=>{
 vi.mocked(useResearchRead).mockReturnValue({data:null,error:'交付读取失败',loading:false,loadingMessage:'',valid:true,refresh:vi.fn()})
 render(<ResearchWorkspace projectId="p1" projectType="research" active section="manuscripts" analysis={{view:'overview',fileId:''}} artifact={{view:'list',artifactId:'',kind:'',page:1}} manuscriptView="research-selection" manuscriptId="" revision={0} schoolNavigation={{view:'list',templateId:''}} onAnalysis={vi.fn()} onArtifact={vi.fn()} onManuscriptView={vi.fn()} onCandidate={vi.fn()} onPublished={vi.fn()} onSchoolNavigate={vi.fn()}/> )
 expect(screen.getByRole('alert').textContent).toBe('交付读取失败');expect(screen.queryByText('先在需求中勾选需要的 SCI 或毕业论文服务并保存，再回来选择写作材料。')).toBeNull()
})

it('clears a stale delivery when the restored delivery is no longer active',async()=>{
 const data={deliveries:[{id:'d1',kind:'sci_draft',active:true},{id:'d2',kind:'thesis_draft',active:false}]};vi.mocked(useResearchRead).mockReturnValue({data,error:'',loading:false,loadingMessage:'',valid:true,refresh:vi.fn()})
 const props={projectId:'p1',projectType:'research' as const,active:true,section:'manuscripts' as const,analysis:{view:'overview' as const,fileId:''},artifact:{view:'list' as const,artifactId:'',kind:'' as const,page:1},manuscriptView:'research-selection' as const,manuscriptId:'',revision:0,schoolNavigation:{view:'list' as const,templateId:''},onAnalysis:vi.fn(),onArtifact:vi.fn(),onManuscriptView:vi.fn(),onCandidate:vi.fn(),onPublished:vi.fn(),onSchoolNavigate:vi.fn(),onWritingDelivery:vi.fn()}
 const view=render(<ResearchWorkspace {...props} writingDeliveryId="d1"/>);await waitFor(()=>expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe('d1'))
 view.rerender(<ResearchWorkspace {...props} writingDeliveryId="d2"/>);await waitFor(()=>expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe(''))
})
