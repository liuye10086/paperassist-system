import {cleanup, fireEvent, render, screen} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import PopulationFilterEditor from './PopulationFilterEditor'
import {isFilterRecipe} from './populationFilterApi'
afterEach(cleanup)
it('edits literal numeric bounds and invalidates the previous preview on every edit',()=>{
 const change=vi.fn();const recipe={conditions:[{column:1,kind:'number' as const,operator:'between' as const,lower:'18',upper:'65'}],reason:'Adults',unit_acknowledged:true}
 render(<PopulationFilterEditor value={recipe} onChange={change}/> )
 fireEvent.change(screen.getByLabelText('下限（含）'),{target:{value:'19'}})
 expect(change).toHaveBeenLastCalledWith({...recipe,conditions:[{...recipe.conditions[0],lower:'19'}]})
})
it('rejects unsupported expressions, empty conditions, nonfinite decimal and overlarge sets',()=>{
 const recipe={conditions:[{column:1,kind:'number',operator:'ge',value:'18'}],reason:'Adults',unit_acknowledged:true}
 expect(isFilterRecipe(recipe)).toBe(true)
 expect(isFilterRecipe({...recipe,conditions:[]})).toBe(false)
 expect(isFilterRecipe({...recipe,conditions:[{...recipe.conditions[0],value:'Infinity'}]})).toBe(false)
 expect(isFilterRecipe({...recipe,conditions:[{...recipe.conditions[0],operator:'sql',value:'1=1'}]})).toBe(false)
 expect(isFilterRecipe({...recipe,conditions:[{column:1,kind:'text',operator:'in',values:Array(21).fill('A')}]})).toBe(false)
})
