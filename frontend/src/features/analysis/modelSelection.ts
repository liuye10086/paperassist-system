import {object,exact,validComparisonGroup,groupIdentity,type ComparisonGroup} from './analysisSelection'

export type ModelMethod='ols'|'logistic'|'roc_auc'|'kaplan_meier'

export const modelMethods:Record<ModelMethod,string>={ols:'OLS 线性回归',logistic:'二元 Logistic 回归',roc_auc:'ROC / AUC',kaplan_meier:'Kaplan–Meier 生存分析'}

type Base={sheet_name:string;missing_policy:'complete_cases';assumptions:{independent_units:boolean;inference_confirmed:boolean}}

export type Covariate={column:string;type:'continuous'|'categorical';unit:string;levels:ComparisonGroup[];reference:ComparisonGroup|null}

export type RegressionSelection=Base&{task_type:'regression';method:'ols'|'logistic';outcome_column:string|null;covariates:Covariate[];outcome_unit:string;positive:ComparisonGroup|null;negative:ComparisonGroup|null;id_column:string|null}

export type RocSelection=Base&{task_type:'roc';method:'roc_auc';outcome_column:string|null;score_column:string|null;positive:ComparisonGroup|null;negative:ComparisonGroup|null;direction:'higher_is_positive'|'lower_is_positive'|null;score_kind:'probability'|'general'|null;score_source:string;score_version:string;formation:string;evaluation_role:'external_validation'|'held_out_validation'|'apparent_exploratory'|'unknown';independence_confirmed:boolean;outcome_time:string}

export type SurvivalSelection=Base&{task_type:'survival';method:'kaplan_meier';id_column:string|null;time_column:string|null;status_column:string|null;group_column:string|null;event:ComparisonGroup|null;censored:ComparisonGroup|null;groups:ComparisonGroup[];time_unit:string;time_origin:string;noninformative_censoring:boolean}

export type ModelSelection=RegressionSelection|RocSelection|SurvivalSelection

export function initialModelSelection(sheet_name:string,method:ModelMethod):ModelSelection{const base:Base={sheet_name,missing_policy:'complete_cases',assumptions:{independent_units:false,inference_confirmed:false}};return method==='ols'||method==='logistic'?{...base,task_type:'regression',method,outcome_column:null,covariates:[],outcome_unit:'',positive:null,negative:null,id_column:null}:method==='roc_auc'?{...base,task_type:'roc',method,outcome_column:null,score_column:null,positive:null,negative:null,direction:null,score_kind:null,score_source:'',score_version:'',formation:'',evaluation_role:'unknown',independence_confirmed:false,outcome_time:''}:{...base,task_type:'survival',method:'kaplan_meier',id_column:null,time_column:null,status_column:null,group_column:null,event:null,censored:null,groups:[],time_unit:'',time_origin:'',noninformative_censoring:false}}

const col=(v:unknown)=>v===null||typeof v==='string'&&/^[A-Z]{1,3}$/.test(v)

const label=(v:unknown,max=80)=>typeof v==='string'&&v.length<=max

const identity=(v:unknown)=>v===null||validComparisonGroup(v)

const groups=(v:unknown,min=0)=>Array.isArray(v)&&v.length>=min&&v.length<=6&&v.every(validComparisonGroup)&&new Set(v.map(groupIdentity)).size===v.length

export function modelColumns(v:ModelSelection):string[]{return (v.task_type==='regression'?[v.outcome_column,...v.covariates.map(c=>c.column),v.id_column]:v.task_type==='roc'?[v.outcome_column,v.score_column]:[v.id_column,v.time_column,v.status_column,v.group_column]).filter((c):c is string=>c!==null)}

export function isModelSelection(v:unknown):v is ModelSelection{

 if(!object(v)||!['regression','roc','survival'].includes(String(v.task_type))||!object(v.assumptions)||!exact(v.assumptions,['independent_units','inference_confirmed'])||!Object.values(v.assumptions).every(x=>typeof x==='boolean')||typeof v.sheet_name!=='string'||!v.sheet_name||v.missing_policy!=='complete_cases')return false

 const base=['task_type','method','sheet_name','missing_policy','assumptions'];let valid=false

 if(v.task_type==='regression')valid=exact(v,[...base,'outcome_column','covariates','outcome_unit','positive','negative','id_column'])&&['ols','logistic'].includes(String(v.method))&&col(v.outcome_column)&&col(v.id_column)&&label(v.outcome_unit)&&identity(v.positive)&&identity(v.negative)&&Array.isArray(v.covariates)&&v.covariates.length<=8&&v.covariates.every(c=>object(c)&&exact(c,['column','type','unit','levels','reference'])&&c.column!==null&&col(c.column)&&label(c.unit)&&identity(c.reference)&&(c.type==='continuous'?Array.isArray(c.levels)&&!c.levels.length&&c.reference===null:c.type==='categorical'&&groups(c.levels)&&(c.reference===null||(c.levels as ComparisonGroup[]).some(l=>groupIdentity(l)===groupIdentity(c.reference as ComparisonGroup)))))

 if(v.task_type==='roc')valid=exact(v,[...base,'outcome_column','score_column','positive','negative','direction','score_kind','score_source','score_version','formation','evaluation_role','independence_confirmed','outcome_time'])&&v.method==='roc_auc'&&col(v.outcome_column)&&col(v.score_column)&&identity(v.positive)&&identity(v.negative)&&(v.direction===null||['higher_is_positive','lower_is_positive'].includes(String(v.direction)))&&(v.score_kind===null||['probability','general'].includes(String(v.score_kind)))&&['external_validation','held_out_validation','apparent_exploratory','unknown'].includes(String(v.evaluation_role))&&typeof v.independence_confirmed==='boolean'&&label(v.score_source,500)&&label(v.score_version,200)&&label(v.formation,2000)&&label(v.outcome_time,500)

 if(v.task_type==='survival')valid=exact(v,[...base,'id_column','time_column','status_column','group_column','event','censored','groups','time_unit','time_origin','noninformative_censoring'])&&v.method==='kaplan_meier'&&[v.id_column,v.time_column,v.status_column,v.group_column].every(col)&&identity(v.event)&&identity(v.censored)&&groups(v.groups)&&label(v.time_unit)&&label(v.time_origin,500)&&typeof v.noninformative_censoring==='boolean'

 if(!valid)return false
 if(v.task_type==='regression'&&v.method==='ols'&&(v.positive!==null||v.negative!==null))return false
 if((v.task_type==='regression'||v.task_type==='roc')&&v.positive&&v.negative&&groupIdentity(v.positive as ComparisonGroup)===groupIdentity(v.negative as ComparisonGroup))return false
 if(v.task_type==='survival'&&(!v.group_column&&Array.isArray(v.groups)&&v.groups.length||v.event&&v.censored&&groupIdentity(v.event as ComparisonGroup)===groupIdentity(v.censored as ComparisonGroup)))return false

 const columns=modelColumns(v as ModelSelection);return new Set(columns).size===columns.length

}

export function completeModelSelection(v:ModelSelection):boolean{return isModelSelection(v)&&v.assumptions.independent_units&&v.assumptions.inference_confirmed&&(v.task_type==='regression'?!!v.outcome_column&&v.covariates.length>0&&v.covariates.every(c=>c.type==='continuous'||c.levels.length>=2&&!!c.reference)&&(v.method==='ols'||!!v.positive&&!!v.negative&&groupIdentity(v.positive)!==groupIdentity(v.negative)):v.task_type==='roc'?!!v.outcome_column&&!!v.score_column&&!!v.positive&&!!v.negative&&groupIdentity(v.positive)!==groupIdentity(v.negative)&&!!v.direction&&!!v.score_kind&&[v.score_source,v.score_version,v.formation,v.outcome_time].every(s=>!!s.trim())&&(!['external_validation','held_out_validation'].includes(v.evaluation_role)||v.independence_confirmed):!!v.id_column&&!!v.time_column&&!!v.status_column&&!!v.event&&!!v.censored&&groupIdentity(v.event)!==groupIdentity(v.censored)&&!!v.time_unit.trim()&&!!v.time_origin.trim()&&v.noninformative_censoring&&(!v.group_column||v.groups.length>=2))}
