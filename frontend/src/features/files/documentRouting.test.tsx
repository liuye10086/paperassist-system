import { expect, test } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import AnalysisSetup from '../analysis/AnalysisSetup'
import { validateFile } from './batchUploadApi'
test('mixed upload accepts docx and analysis only includes explicitly typed xlsx', () => {
 expect(validateFile(new File(['word'], 'paper.docx'))).toBeNull()
 render(<AnalysisSetup projectId="p1" files={[
 {id:'x',filename:'data.xlsx',file_type:'xlsx',uploaded_at:'2026-10-12',parse_status:'parsed'},
 {id:'w',filename:'paper.docx',file_type:'docx',uploaded_at:'2026-10-12',parse_status:'parsed'},
 {id:'pdf',filename:'paper.pdf',file_type:'pdf',uploaded_at:'2026-10-12',parse_status:'parsed'},
 {id:'png',filename:'scan.png',file_type:'png',uploaded_at:'2026-10-12',parse_status:'parsed'},
 {id:'jpeg',filename:'scan.jpeg',file_type:'jpeg',uploaded_at:'2026-10-12',parse_status:'parsed'},
 {id:'unknown',filename:'unknown.xlsx',uploaded_at:'2026-10-12',parse_status:'parsed'} as never,
 ]}/> )
 expect(screen.getByRole('option',{name:/data.xlsx/})).toBeTruthy()
 expect(screen.queryByRole('option',{name:/paper.docx/})).toBeNull()
 expect(screen.queryByRole('option',{name:/paper.pdf/})).toBeNull()
 expect(screen.queryByRole('option',{name:/scan.png/})).toBeNull()
 expect(screen.queryByRole('option',{name:/scan.jpeg/})).toBeNull()
 expect(screen.queryByRole('option',{name:/unknown.xlsx/})).toBeNull()
 cleanup()
})
