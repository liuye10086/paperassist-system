import {translate} from './i18n'

/** Localize the parser's own suffix only, leaving the original filename untouched. */
export function parsedMaterialLabel(source:{kind:string;label:string;version?:number|null}) {
 const parsed=source.kind==='document_version'
 if ((!parsed && source.kind!=='ocr_review_version') || source.version==null) return null
 const suffix=' — '+(parsed?'文档解析 / Parsed document':'人工核对 / Human reviewed')+' v'+source.version
 if (!source.label.endsWith(suffix)) return null
 const name=source.label.slice(0,-suffix.length)
 return translate(parsed?'{name} — 文档解析 v{number}':'{name} — 人工核对 v{number}',{name,number:source.version})
}
