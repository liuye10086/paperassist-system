export function orderMarkerPngMembers<T extends {key:string}>(members:readonly T[]):T[]{
 const page=(member:T)=>member.key.match(/^(marker_(?:dotplot|heatmap))(?:_page_(\d+))?_png$/)
 const groups=new Map<string,T[]>()
 for(const member of members){const match=page(member);if(match){const group=groups.get(match[1])??[];group.push(member);groups.set(match[1],group)}}
 for(const group of groups.values())group.sort((a,b)=>Number(page(a)?.[2]??1)-Number(page(b)?.[2]??1))
 const offsets=new Map<string,number>()
 return members.map(member=>{const match=page(member);if(!match)return member;const offset=offsets.get(match[1])??0;offsets.set(match[1],offset+1);return groups.get(match[1])![offset]})
}
