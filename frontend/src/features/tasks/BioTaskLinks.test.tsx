import {afterEach,expect,it} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import BioTaskLinks from './BioTaskLinks'
import {runFixture} from '../bioinformatics/spatialFixtures'
afterEach(cleanup)
it('uses the fixed run for QC waits and only offers a formal result after publication',()=>{const {rerender}=render(<BioTaskLinks task={runFixture.task}/>);expect(screen.getByRole('link').getAttribute('href')).toContain('view=bio-analysis&run=run1');expect(screen.queryByText('打开固定处理结果')).toBeNull();rerender(<BioTaskLinks task={{...runFixture.task,status:'succeeded',result_bio_processed_dataset_version_id:'processed1'}}/>);expect(screen.getByRole('link',{name:'打开固定处理结果'}).getAttribute('href')).toContain('processed=processed1&tab=qc')})
