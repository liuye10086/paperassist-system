import type {Locale} from '../../shared/i18n'
export const kindLabels={boxplot:'箱线图',correlation_heatmap:'相关热力图',scatter:'散点图',line:'折线图',bar:'柱状图',violin:'小提琴图',forest:'效应森林图',roc_curve:'ROC 曲线',kaplan_meier:'Kaplan–Meier 生存曲线'} as const
export type FigureKind=keyof typeof kindLabels
export type ProjectionConfig={x_column?:string;y_column?:string;group_column?:string;category_column?:string;x_type:'numeric'|'datetime'|'ordered';x_order:(string|number|boolean)[];expected_x:(string|number)[];aggregation:'unique'|'mean';bar_stat:'count'|'proportion'|'mean';error_bars:'none'|'sd';missing_group:'block'|'exclude';included_categories:(string|number|boolean)[]}
export type FigureConfig={figure_kind:FigureKind;language:Locale;projection?:ProjectionConfig;style:{title:string;caption:string;aliases:Record<string,string>;palette:'blue'|'colorblind'|'gray';width:number;height:number;font_size:number;display_order:string[]}}
export function defaultConfig(kind:FigureKind,language:Locale):FigureConfig{return {figure_kind:kind,language,projection:{x_type:'numeric',x_order:[],expected_x:[],aggregation:'unique',bar_stat:'count',error_bars:'none',missing_group:'block',included_categories:[]},style:{title:'',caption:'',aliases:{},palette:'colorblind',width:2400,height:1600,font_size:12,display_order:[]}}}
export function configurationIssues(config:FigureConfig):string[]{
 const p=config.projection,issues:string[]=[]
 if(config.figure_kind==='line'){
  if(!p?.x_column)issues.push('请选择横轴字段。')
  if(p?.x_type==='ordered'&&!p.x_order.length)issues.push('请明确有序类别顺序。')
 }
 if(['line','violin'].includes(config.figure_kind)||config.figure_kind==='bar'&&p?.bar_stat==='mean')if(!p?.y_column)issues.push('请选择数值字段。')
 if(config.figure_kind==='bar'&&!p?.category_column)issues.push('请选择类别字段。')
 if(!Number.isInteger(config.style.width)||config.style.width<1600||config.style.width>5000||!Number.isInteger(config.style.height)||config.style.height<1000||config.style.height>4000||!Number.isInteger(config.style.font_size)||config.style.font_size<8||config.style.font_size>24)issues.push('图像尺寸超出支持范围。')
 return issues
}
export function compatibleKinds(resultType:string|undefined,mode:string|undefined,available:FigureKind[]):FigureKind[]{
 const preferred:FigureKind=resultType==='correlation'?(mode==='matrix'?'correlation_heatmap':'scatter'):resultType==='regression'?'forest':resultType==='roc'?'roc_curve':resultType==='survival'?'kaplan_meier':'boxplot'
 return [...available].sort((a,b)=>Number(b===preferred)-Number(a===preferred))
}
