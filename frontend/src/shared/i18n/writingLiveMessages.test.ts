import {readFileSync,readdirSync} from 'node:fs'
import {resolve} from 'node:path'
import ts from 'typescript'
import {afterEach,expect,test} from 'vitest'
import {setLocale,translate} from './index'

afterEach(()=>setLocale('zh-CN'))
const directory=resolve(process.cwd(),'src/features/manuscripts')
const files=readdirSync(directory).filter(name=>(/^Writing.*\.tsx$/.test(name)&&!name.endsWith('.test.tsx'))||['FigureLanguagePanel.tsx','useWritingOperation.ts','ManuscriptPreview.tsx'].includes(name))
const sources=files.map(name=>`${directory}/${name}`).concat(['TaskModelUsage.tsx','ProjectModelUsage.tsx'].map(name=>resolve(process.cwd(),'src/features/model-usage',name)))

test('translates controlled writing and billing labels including dynamic decisions and preview titles',()=>{
 setLocale('en')
 const missing:string[]=[]
 for(const path of sources){
  const ast=ts.createSourceFile(path,readFileSync(path,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX)
  function visit(node:ts.Node){
   if(ts.isStringLiteral(node)&&/[\u3400-\u9fff]/.test(node.text)&&translate(node.text)===node.text)missing.push(node.text)
   ts.forEachChild(node,visit)
  }
  visit(ast)
 }
 expect([...new Set(missing)]).toEqual([])
})

test('keeps provenance and unknown-cost meanings distinct in English',()=>{
 setLocale('en')
 expect(translate('离线模拟回执')).toBe('Offline simulated receipt')
 expect(translate('真实供应商调用')).toBe('Live provider call')
 expect(translate('实际费用未知')).toBe('Actual cost unknown')
 expect(translate('标题强度一致')).toBe('Title claim strength matches the reviewed body')
})
