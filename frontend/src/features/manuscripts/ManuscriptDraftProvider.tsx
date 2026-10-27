import type {ReactNode} from 'react'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {ManuscriptDraftContext} from './manuscriptDraftContext'
export function ManuscriptDraftProvider({register,children}:{register?:RegisterLeaveGuard;children:ReactNode}){
 return <ManuscriptDraftContext.Provider value={register}>{children}</ManuscriptDraftContext.Provider>
}
