import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ModuleViews,{ModuleView} from './ModuleViews'
afterEach(cleanup)
it('shows one module and retains the mounted draft when switching back',()=>{
 render(<ModuleViews label="Views"><ModuleView id="edit" title="Edit"><label>Draft<input defaultValue="original"/></label></ModuleView><ModuleView id="files" title="Files"><a href="/saved">Download saved file</a></ModuleView></ModuleViews>)
 fireEvent.change(screen.getByLabelText('Draft'),{target:{value:'unsaved text'}})
 fireEvent.click(screen.getByRole('button',{name:'Files'}))
 expect(screen.queryByRole('textbox')).toBeNull()
 expect(screen.getByRole('link',{name:'Download saved file'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Edit'}))
 expect(screen.getByRole('textbox')).toHaveProperty('value','unsaved text')
 expect(screen.queryByRole('link')).toBeNull()
 expect(document.querySelector('details,[aria-expanded]')).toBeNull()
})
it('defers unvisited content and keeps it mounted after controlled navigation',()=>{
 const mounted=vi.fn(),changed=vi.fn()
 function Evidence(){mounted();return <label>Evidence<input defaultValue="saved"/></label>}
 const views=<><ModuleView id="main" title="Main">Main content</ModuleView><ModuleView id="evidence" title="Evidence"><Evidence/></ModuleView></>
 const children=views.props.children
 const {rerender}=render(<ModuleViews label="Views" value="main" onChange={changed} lazy>{children}</ModuleViews>)
 expect(mounted).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Evidence'}));expect(changed).toHaveBeenCalledWith('evidence')
 expect(mounted).not.toHaveBeenCalled()
 rerender(<ModuleViews label="Views" value="evidence" onChange={changed} lazy>{children}</ModuleViews>)
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'draft'}})
 rerender(<ModuleViews label="Views" value="main" lazy>{children}</ModuleViews>)
 expect(screen.queryByRole('textbox')).toBeNull()
 rerender(<ModuleViews label="Views" value="evidence" lazy>{children}</ModuleViews>)
 expect(screen.getByRole('textbox')).toHaveProperty('value','draft')
})
