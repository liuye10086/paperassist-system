import {afterEach,expect,it} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import {BioChecks} from './BioDetails'
afterEach(cleanup)
it.each([['identical','全矩阵数值和轴顺序一致'],['order_reindexed_equal','重排轴后全矩阵数值一致'],['mismatch','矩阵不一致，不能确认等价'],['not_comparable','条件不足，尚未完成等价核对']])('shows the actual H5 attestation %s instead of a generic passed badge',(status,label)=>{render(<BioChecks checks={[{code:'representation_equivalence',status:'passed',value:{status,reason:status==='not_comparable'?'alternate_not_requested':null}}]}/>);expect(screen.getByText(new RegExp(label))).toBeTruthy();expect(screen.queryByText(/已通过/)).toBeNull()})
