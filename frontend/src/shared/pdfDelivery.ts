export function hasPdfPackageMembers(members:unknown):boolean {
 return Array.isArray(members)&&members.some(member=>member!==null&&typeof member==='object'&&'name' in member&&typeof member.name==='string'&&member.name.toLowerCase().endsWith('.pdf'))
}

export function deliveryMemberContainsPdf(member:{format:string;selection:{kind:string};source_metadata?:Record<string,unknown>}):boolean {
 return member.selection.kind==='pdf_export'||member.format.toLowerCase()==='pdf'||member.format.toLowerCase()==='zip'&&hasPdfPackageMembers(member.source_metadata?.inner_members)
}
