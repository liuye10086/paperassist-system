import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import ts from 'typescript'
import {afterEach,expect,test} from 'vitest'
import {setLocale,translate} from './index'

afterEach(()=>setLocale('zh-CN'))
const source=resolve(process.cwd(),'src/features/research-intake/DeliveryPackagePanel.tsx')

// Every Chinese literal in the panel reaches the screen through t(); keep English complete.
test('translates every Chinese literal in the delivery package panel',()=>{
 setLocale('en')
 const missing:string[]=[]
 const ast=ts.createSourceFile(source,readFileSync(source,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX)
 function visit(node:ts.Node){
  if((ts.isStringLiteral(node)||ts.isNoSubstitutionTemplateLiteral(node))&&/[㐀-鿿]/.test(node.text)&&translate(node.text)===node.text)missing.push(node.text)
  ts.forEachChild(node,visit)
 }
 visit(ast)
 expect([...new Set(missing)]).toEqual([])
})

test('labels earlier anonymized deliveries in American English',()=>{
 setLocale('en')
 expect(translate('盲审交付')).toBe('Earlier anonymized delivery')
 expect(translate('普通交付')).toBe('Standard delivery')
 expect(translate('盲审版')).toBe('Anonymized copy (earlier)')
 expect(translate('署名版')).toBe('Named copy')
})
