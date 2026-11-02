import {render,screen,cleanup} from '@testing-library/react'
import {afterEach,it,expect} from 'vitest'
import {BioJson,BioSource} from './BioSpatialShared'
import {rawFixture} from './spatialFixtures'
import {DataValue} from '../bio-insights/InsightShared'
import {Notices} from '../research-results/ResearchShared'
afterEach(cleanup)
it('projects frozen provenance and nested methods into readable customer details',()=>{
 const {container}=render(<><BioSource source={rawFixture}/><BioJson value={{methods:{q_threshold:0.05},manifest_sha256:'f'.repeat(64),limitations:['不是独立供体']}}/><DataValue value={{source_id:'private-source',observations:0}}/><Notices title="研究限制" items={[{reason:'仍需生物学验证',sha256:'e'.repeat(64)}]}/></>)
 expect(container.textContent).not.toContain(rawFixture.dataset_version_id+' ·');expect(container.textContent).not.toContain(rawFixture.manifest_sha256);expect(container.textContent).not.toContain('private-source');expect(container.querySelector('pre,code')).toBeNull();expect(screen.getByText('0.05')).toBeTruthy();expect(screen.getByText('不是独立供体')).toBeTruthy();expect(screen.getByText('仍需生物学验证')).toBeTruthy();expect(screen.getByText('0')).toBeTruthy()
})
