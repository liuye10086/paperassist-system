import {createContext} from 'react'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
export const ManuscriptDraftContext=createContext<RegisterLeaveGuard|undefined>(undefined)
