import {act,cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,test} from 'vitest'
import ReportPreview from './ReportPreview'
import backend from '../datasetPreparation/batch07BackendFixture.json'
import {setLocale} from '../../shared/i18n'
import {isDatasetSource} from '../analysis/datasetSource'

afterEach(()=>{cleanup();setLocale('zh-CN')})
const source=backend.published.source
if(!isDatasetSource(source))throw new Error('Invalid backend source fixture')
// The recipe, receipt and parent come from the isolated backend response; the
// manifest reference follows load_processing's frozen collection contract.
const processing={schema_version:2,recipe:backend.published.recipe,receipt:backend.published.summary,base_source:backend.published.base_source,
 manifest:{object_key:`quality-manifests/${source.dataset_id}/${'a'.repeat(64)}.json`,sha256:'a'.repeat(64),size_bytes:1024,entry_count:backend.published.summary.impact_count}}
const sections=[{key:'processing',title:'Processing',content:[processing]},{key:'statistics',title:'Statistics',content:[{check:{row_count:7,valid_count:6,excluded_count:1}}]}]

test('v2 collection preview shows frozen quality counts and policies without internal asset references',()=>{
 render(<ReportPreview ready sections={sections} projectId="p1" source={source}/>)
 expect(screen.getByText('原始区域 10 行 − 累计整理排除 3 行 = 当前整理保留 7 行。')).toBeTruthy()
 expect(screen.getByText('整理后保留记录数')).toBeTruthy()
 expect(screen.getByText('本分析排除记录数')).toBeTruthy()
 for(const item of backend.published.recipe.manual_exclusions)expect(document.body.textContent).toContain(item.reason)
 expect(document.body.textContent).not.toMatch(/quality-manifests|未识别字段|root_record_count|manual_only|exact_duplicate/)
 expect(document.body.textContent).not.toContain(source.dataset_id)
 expect(document.body.textContent).not.toContain('a'.repeat(64))
 expect(screen.getByText('下载完整质量回执').getAttribute('href')).toBe(`/api/v1/projects/p1/files/${source.file_id}/prepared-dataset-versions/${source.dataset_id}/impacts/download`)
 act(()=>setLocale('en'))
 expect(screen.getByText('Original region 10 rows − cumulative preparation exclusions 3 rows = currently retained 7 rows.')).toBeTruthy()
 expect(screen.getByText('Records retained after preparation')).toBeTruthy()
 expect(screen.getByText('Records excluded from this analysis')).toBeTruthy()
 expect(document.body.textContent).not.toMatch(/Unrecognized field|manual_only|root_record_count/)
})

test('v2 system limitations are translated but matching author statements are preserved',()=>{
 const message='统计阶段采用当前整理保留行的共同完整记录，不新增填补、去重或自动剔除。'
 setLocale('en')
 render(<ReportPreview ready sections={[...sections,{key:'methods',title:'Methods',content:{limitations:[message],question:message}}]}/>)
 expect(screen.getByText('Analysis uses common complete cases among retained records, without additional imputation, deduplication or automatic removal.')).toBeTruthy()
 expect(screen.getByText(message)).toBeTruthy()
})

test('an invalid v2 quality receipt does not fall through to exposing its storage reference',()=>{
 render(<ReportPreview ready sections={[{key:'processing',title:'Processing',content:[{...processing,receipt:{...processing.receipt,root_record_count:999}}]}]}/>)
 expect(screen.getByText('完整质量回执读取失败，请重试。')).toBeTruthy()
 expect(document.body.textContent).not.toContain('quality-manifests')
})

test('legacy collection count labels are unchanged',()=>{
 render(<ReportPreview ready sections={[{key:'statistics',title:'Statistics',content:{check:{row_count:10,valid_count:9,excluded_count:1}}}]}/>)
 expect(screen.getByText('原始记录数')).toBeTruthy()
 expect(screen.queryByText('整理后保留记录数')).toBeNull()
})
