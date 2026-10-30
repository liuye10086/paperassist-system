import {createContext,useContext} from 'react'
import type {AnalysisSelection} from './manuscriptTypes'

type Transfer={projectId:string;projectType:'sci'|'thesis';pending:AnalysisSelection|null;send:(selection:AnalysisSelection)=>void}
export const AnalysisWritingTransferContext=createContext<Transfer|null>(null)
export const useAnalysisWritingTransfer=()=>useContext(AnalysisWritingTransferContext)
