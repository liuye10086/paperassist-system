import type {Member} from './contracts'
export function visibleMembers(items:Member[],containsPdf=false){const hasPdf=containsPdf||items.some(m=>m.format.toLowerCase()==='pdf');return items.filter(m=>m.format.toLowerCase()!=='pdf'&&(!hasPdf||m.format.toLowerCase()!=='zip'))}
