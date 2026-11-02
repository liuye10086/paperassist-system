import {afterEach,expect,it} from 'vitest'
import {cleanup,render,screen,within} from '@testing-library/react'
import {BioChecks} from './BioDetails'
import BioQcSummary from './BioQcSummary'
afterEach(cleanup)
it('labels single-cell spatial checks not applicable and retains Visium checks and cell QC units',()=>{
 const checks=[{code:'positions_count',status:'passed',value:0},{code:'matrix_matches_in_tissue',status:'passed',value:'not_applicable'},{code:'structure',status:'passed'}]
 const view=render(<><BioChecks checks={checks} singleCell/><BioQcSummary summary={{}} observationLabel="cell"/></>)
 expect(screen.getAllByText(/不适用/)).toHaveLength(2)
 expect(within(screen.getByRole('table')).getByText('cell')).toBeTruthy()
 expect(screen.getAllByText(/已通过/)).toHaveLength(1)
 view.rerender(<BioChecks checks={[{code:'matrix_matches_in_tissue',status:'passed',value:true},{code:'positions_count',status:'passed',value:4}]}/>)
 expect(screen.queryByText(/不适用/)).toBeNull()
 expect(screen.getAllByText(/已通过/)).toHaveLength(2)
})
