import {useEffect,useLayoutEffect,useRef} from 'react'
/** Consume a completed request once while invoking the current host callback. */
export default function useResearchCompletion<T>(value:T|null|undefined,onComplete:(value:T)=>void){
 const callback=useRef(onComplete)
 useLayoutEffect(()=>{callback.current=onComplete},[onComplete])
 useEffect(()=>{if(value)callback.current(value)},[value])
}
