import {readFileSync} from 'node:fs'
import {afterEach,expect,it} from 'vitest'
import {setLocale,translate} from '../../shared/i18n'
import {literatureCitationMessages} from '../../shared/i18n/literatureCitationMessages'
afterEach(()=>setLocale('zh-CN'))
it('translates every citation interface label, including dynamic field and status labels',()=>{
 setLocale('en')
 const files=['CitationWorkspace.tsx','CitationMetadataPanel.tsx','CitationParagraphEditor.tsx','CitationSnapshot.tsx','citationHooks.ts']
 const labels=new Set(Object.keys(literatureCitationMessages))
 for(const file of files){const source=readFileSync(new URL(file,import.meta.url),'utf8');for(const match of source.matchAll(/'([^'\n]*[\u3400-\u9fff][^'\n]*)'/g))labels.add(match[1])}
 const untranslated=[...labels].filter(label=>/[\u3400-\u9fff]/.test(translate(label,{number:1,revision:1,count:1,field:'Title',location:'Page 1'})))
 expect(untranslated).toEqual([])
})
