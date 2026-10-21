// Match Python str length/slicing at the frozen layout API boundary.
export const codePointLength=(value:string)=>Array.from(value).length
export const limitCodePoints=(value:string,maximum:number)=>Array.from(value).slice(0,maximum).join('')
