import {Children,isValidElement,useId,useState,type ReactNode} from 'react'
import './moduleViews.css'

type ViewProps={id:string;title:string;children:ReactNode}
export function ModuleView({children}:ViewProps){return <>{children}</>}

/** Switch layout without unmounting drafts, pending operations or read position. */
export default function ModuleViews({label,children,lazy=false,value,onChange}:{label:string;children:ReactNode;lazy?:boolean;value?:string;onChange?:(id:string)=>void}){
 const views=Children.toArray(children).filter(child=>isValidElement<ViewProps>(child)&&child.type===ModuleView)
 const [chosen,setChosen]=useState(''),[visited,setVisited]=useState<string[]>([]),uid=useId()
 const requested=value??chosen
 const current=views.some(view=>isValidElement<ViewProps>(view)&&view.props.id===requested)?requested:(isValidElement<ViewProps>(views[0])?views[0].props.id:'')
 if(current&&!visited.includes(current))setVisited([...visited,current])
 return <div className="module-views"><nav aria-label={label}>{views.map(view=>isValidElement<ViewProps>(view)&&<button key={view.props.id} type="button" aria-pressed={current===view.props.id} aria-controls={`${uid}-${view.props.id}`} onClick={()=>{setChosen(view.props.id);onChange?.(view.props.id)}}>{view.props.title}</button>)}</nav>{views.map(view=>isValidElement<ViewProps>(view)&&<section key={view.props.id} id={`${uid}-${view.props.id}`} aria-label={view.props.title} className="module-view-content" hidden={current!==view.props.id}>{(!lazy||current===view.props.id||visited.includes(view.props.id))&&view}</section>)}</div>
}
