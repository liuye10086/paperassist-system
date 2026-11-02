import {render,screen,fireEvent} from '@testing-library/react'
import {describe,it,expect,vi} from 'vitest'
import SingleCellSetup from './SingleCellSetup'

describe('single cell evidence',()=>{
 it('keeps unknown labels and explicit donor confirmation independent of exploration',()=>{
  const change=vi.fn()
  render(<SingleCellSetup value={{cell_labels:[],donor_design_confirmed:false,independence_basis:''}} onChange={change}/>)
  expect(screen.queryByText('仅保留组织内 spot')).toBeNull()
  expect(screen.getByText(/cell 仅用于探索/)).toBeTruthy()
  fireEvent.change(screen.getByLabelText('cluster 编号'),{target:{value:'0'}})
  fireEvent.click(screen.getByText('保存此 cluster 标签证据'))
  expect(change).toHaveBeenCalledWith(expect.objectContaining({cell_labels:[expect.objectContaining({cluster:'0',label:'unknown'})]}))
 })
})
