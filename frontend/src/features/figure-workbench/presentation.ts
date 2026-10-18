import {object,text} from './contracts'
export type Presentation={schema_version:1|2;axes:{x:{label:string;unit:string};y:{label:string;unit:string}};legend:{title:string;entries:{label:string;color:string}[]};color_scale:null|{label:string;min:number;max:number;center:number|null;ticks:number[];palette:string[]};abbreviations:{term:string;definition:string}[];statistical_notes:string[]}
const exact=(v:Record<string,unknown>,keys:string[])=>Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k))
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
const axis=(v:unknown)=>object(v)&&exact(v,['label','unit'])&&text(v.label)&&text(v.unit)
export function isPresentation(v:unknown):v is Presentation{
 if(!object(v)||!exact(v,['schema_version','axes','legend','color_scale','abbreviations','statistical_notes'])||![1,2].includes(Number(v.schema_version))||typeof v.schema_version!=='number'||!object(v.axes)||!exact(v.axes,['x','y'])||!axis(v.axes.x)||!axis(v.axes.y)||!object(v.legend)||!exact(v.legend,['title','entries'])||!text(v.legend.title)||!Array.isArray(v.legend.entries)||!v.legend.entries.every(e=>object(e)&&exact(e,['label','color'])&&text(e.label)&&text(e.color)&&/^#[a-fA-F0-9]{6}$/.test(e.color)))return false
 const c=v.color_scale
 if(c!==null&&(!object(c)||!exact(c,['label','min','max','center','ticks','palette'])||!text(c.label)||!finite(c.min)||!finite(c.max)||c.min>=c.max||!(c.center===null||finite(c.center)&&c.center>=c.min&&c.center<=c.max)||!Array.isArray(c.ticks)||!c.ticks.every(n=>finite(n)&&n>=Number(c.min)&&n<=Number(c.max))||(!Array.isArray(c.palette)||c.palette.length<2||!c.palette.every(color=>text(color)&&/^#[a-fA-F0-9]{6}$/.test(color)))))return false
 return Array.isArray(v.abbreviations)&&v.abbreviations.every(a=>object(a)&&exact(a,['term','definition'])&&text(a.term)&&text(a.definition))&&Array.isArray(v.statistical_notes)&&v.statistical_notes.every(text)
}
