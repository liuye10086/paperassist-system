import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import BioAnalysisResult from '../bioinformatics/BioAnalysisResult'
import {processedFixture} from '../bioinformatics/spatialFixtures'
import {setApiSession,clearApiSession} from '../../shared/api/client'
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession()})
it('enters insights from an existing B02 result with its fixed processed identity and performs no reanalysis',async()=>{setApiSession('csrf','owner');const fetch=vi.fn().mockResolvedValue(Response.json(processedFixture));vi.stubGlobal('fetch',fetch);const navigate=vi.fn();render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="methods" onNavigate={navigate}/>);fireEvent.click(await screen.findByRole('button',{name:'差异与功能分析'}));expect(navigate).toHaveBeenCalledWith({view:'bio-insights',fileId:'',processedId:'processed1'});expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)})
