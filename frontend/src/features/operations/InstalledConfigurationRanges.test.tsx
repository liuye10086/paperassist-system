import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {setLocale} from '../../shared/i18n'
import InstalledConfigurationCapabilities from './InstalledConfigurationCapabilities'
import {testCatalog} from './configurationTestFixtures'

afterEach(()=>{cleanup();setLocale('zh-CN')})

it.each(['zh-CN','en'] as const)('shows the installed renderer4 and explanation5 ranges (%s)',locale=>{
 setLocale(locale)
 const templates=['openai_figure_workbench_v1-v4','figure_explanation_v1-v5']
 render(<InstalledConfigurationCapabilities catalog={{...testCatalog,installed:{...testCatalog.installed,templates}}}/>)
 expect(screen.getByText(locale==='en'?'Figure workbench templates (v1 to v4)':'图表工作台模板（v1至v4）')).toBeTruthy()
 expect(screen.getByText(locale==='en'?'Figure explanation templates (v1 to v5)':'图表解释模板（v1至v5）')).toBeTruthy()
 for(const template of templates)expect(screen.getByText(template)).toBeTruthy()
})

it.each(['zh-CN','en'] as const)('retains labels for historical installed range identifiers (%s)',locale=>{
 setLocale(locale)
 const templates=['openai_figure_workbench_v1-v3','figure_explanation_v1-v4']
 render(<InstalledConfigurationCapabilities catalog={{...testCatalog,installed:{...testCatalog.installed,templates}}}/>)
 expect(screen.getByText(locale==='en'?'Figure workbench templates (v1 to v3)':'图表工作台模板（v1至v3）')).toBeTruthy()
 expect(screen.getByText(locale==='en'?'Figure explanation templates (v1 to v4)':'图表解释模板（v1至v4）')).toBeTruthy()
 for(const template of templates)expect(screen.getByText(template)).toBeTruthy()
})
