import type {InventoryItem} from './writingLiveTypes'
export type ReviewFigure={id:string;number?:number;title:string;preview_url?:string|null}
// Actual DOCX inventories add one of these output-language prefixes to image locations.
export function imageLocation(location:string){return location.replace(/^(?:en|zh-CN):(?=image:)/,'')}
export function resolveReviewFigure(item:InventoryItem,figures:ReviewFigure[]=[]){const location=imageLocation(item.location);return [...figures].sort((a,b)=>b.id.length-a.id.length).find(f=>location==='image:'+f.id||location.startsWith('image:'+f.id+':'))}
export function unlocatedEmptyImage(item:InventoryItem,figures:ReviewFigure[]=[]){return item.kind==='image'&&!item.text.trim()&&!resolveReviewFigure(item,figures)}
