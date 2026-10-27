import {createContext,useContext} from 'react'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
export const ReviewActivityContext=createContext<RegisterLeaveGuard|undefined>(undefined)
export function useReviewDraftGuard(dirty:boolean,pending=false){useDraftLeaveGuard(useContext(ReviewActivityContext),dirty,pending)}
