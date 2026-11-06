import {expect,it} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import SingleCellQcResult from './SingleCellQcResult'

it('identifies inherited parent quality-model metrics without implying the subset reran capture models',()=>{
 render(<SingleCellQcResult summary={{single_cell_algorithms:{inherited_from_parent:true,parent_processed_source:{processed_dataset_version_id:'parent1'},doublet:{status:'completed',libraries:1,completed_libraries:1,computed_cells:2480,input_cells:2480,predicted_doublets:112,excluded_cells:112},decontx:{status:'completed',libraries:1,completed_libraries:1,computed_cells:2480,input_cells:2480,layer_emitted:true}}}}/>)
 expect(screen.getByText('以下质量模型结果继承父分析，不是在本亚群上重新运行。')).toBeTruthy()
 expect(screen.getByText('预测双细胞：112；实际排除：112')).toBeTruthy()
 expect(screen.getAllByText('状态：已完成；完成文库：1 / 1；已计算细胞：2480 / 2480')).toHaveLength(2)
 cleanup()
})
