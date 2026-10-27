import {useContext} from 'react'
import {ManuscriptDraftContext} from './manuscriptDraftContext'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'

export function useManuscriptDraft(dirty:boolean,pending=false,register?:RegisterLeaveGuard){
 const context=useContext(ManuscriptDraftContext)
 useDraftLeaveGuard(register??context,dirty,pending)
}
