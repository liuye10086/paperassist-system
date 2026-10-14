import { expect, it } from 'vitest'
import { validateSelection, uploadQueue, mergeBatch } from './batchUploadApi'
it('accepts one or ten items including duplicate names and rejects eleven', () => {
 const file = new File(['a'], 'same.xlsx')
 expect(validateSelection([file])).toBeNull()
 expect(validateSelection(Array(10).fill(file))).toBeNull()
 expect(validateSelection(Array(11).fill(file))).toBe('每批最多选择 10 个文件。')
})
it('uses only two transfers and continues after a failed item', async () => {
 let live=0, peak=0; const completed:number[]=[]
 await uploadQueue([0,1,2,3,4], new AbortController().signal, async item => {
 live++; peak=Math.max(peak,live); await new Promise(resolve=>setTimeout(resolve,5)); live--; completed.push(item); if(item===1) throw new Error('failure')
 })
 expect(peak).toBe(2); expect(completed).toHaveLength(5)
})
it('never replaces a newer batch with a late response',()=>{
 const current={id:'b',revision:8};expect(mergeBatch({id:'b',revision:2},current)).toEqual(current)
})
