import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import JournalResearchForm from './JournalResearchForm'
import type {ResearchRequest} from './contracts'
afterEach(cleanup)
const config={default_limit:2,max_limit:4,configuration:{status:'bound' as const,version_id:'v2',sha256:'a'.repeat(64)}}
function fill(){fireEvent.change(screen.getByLabelText('研究标题'),{target:{value:'Synthetic local study'}});fireEvent.change(screen.getByLabelText('主题标签（逗号或换行分隔）'),{target:{value:'synthetic'}});fireEvent.change(screen.getByRole('textbox',{name:'文章类型'}),{target:{value:'research'}})}
it('omits default count, sends an explicit count and preserves that choice when configuration refreshes',()=>{
 const create=vi.fn(async(_request:ResearchRequest)=>true);const props={manuscripts:[],materials:[],profiles:[],busy:false,onCreate:create,configuration:config}
 const view=render(<JournalResearchForm {...props}/>);fill();expect(screen.getByText('当前默认 2 条，最多 4 条。')).toBeTruthy();fireEvent.submit(screen.getByRole('form',{name:'研究信息与投稿偏好'}));expect(create.mock.calls[0][0]).not.toHaveProperty('limit')
 fireEvent.click(screen.getByLabelText('明确指定建议数量'));fireEvent.change(screen.getByLabelText('建议数量'),{target:{value:'3'}});fireEvent.submit(screen.getByRole('form',{name:'研究信息与投稿偏好'}));expect(create.mock.calls[1][0]).toHaveProperty('limit',3)
 view.rerender(<JournalResearchForm {...props} configuration={{...config,default_limit:1,max_limit:2}}/>);expect(screen.getByLabelText('建议数量')).toHaveProperty('value','3');expect(screen.getByLabelText('建议数量')).toHaveProperty('max','2')
})
