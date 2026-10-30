import {useState,type ReactNode} from 'react'
import type {AnalysisSelection} from './manuscriptTypes'
import {AnalysisWritingTransferContext as Context} from './analysisWritingTransfer'
export function AnalysisWritingProvider({projectId,projectType,onOpenWriting,children}:{projectId:string;projectType:'sci'|'thesis';onOpenWriting:()=>void;children:ReactNode}){
 const [pending,setPending]=useState<AnalysisSelection|null>(null)
 return <Context.Provider value={{projectId,projectType,pending,send(selection){if(selection.project_id!==projectId||selection.project_type!==projectType)return;setPending(selection);onOpenWriting()}}}>{children}</Context.Provider>
}
