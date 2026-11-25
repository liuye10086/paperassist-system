import {expect, it} from 'vitest'
import {inputFixture} from './manuscriptFixtures'
import {validCandidates} from './manuscriptTypes'
import {paperDraftMaterials} from './paperDraftMaterials'

it('carries requirements for each writable school chapter into the writing input', () => {
  const requirements = [
    ['summary', '摘要', 'abstract'], ['background', '研究背景', 'introduction'],
    ['methods', '研究设计', 'materials_and_methods'], ['results', '主要发现', 'results'],
    ['discussion', '结果解释', 'discussion'], ['conclusion', '总结', 'conclusion'],
    ['legacy-appendix', '附录', 'results'],
  ] as const
  const chapters = [{id:'cover', title:'封面', level:1},
    ...requirements.map(([id, title]) => ({id, title, level:1})), {id:'references', title:'参考文献', level:1}]
  const candidates = {
    project_type:'thesis', items:[], citation_drafts:[], methods_fields:[],
    thesis:{ready:true, confirmation_id:'school1', blocking_reasons:[], chapters, template_source_file_ids:[],
      purposes:requirements.map(([, , purpose]) => purpose),
      profile:{revision:2, bound_confirmation_id:'school1', school:'Example', department:'', major:'', degree_type:'',
        education_level:'硕士', applicable_version:''}},
    paper_plan:{kind:'thesis', token:'a'.repeat(64), omitted_count:0, title:'Thesis', keywords:[], materials:[],
      sections:requirements.map(([chapter_id, label, purpose]) => ({id:`plan-${chapter_id}`, chapter_id, label,
        purpose, text:`Keep the supplied ${chapter_id} wording.`}))},
  }
  const valid = validCandidates(candidates, 'p1')
  expect(valid).toBe(true)
  if (!valid) return
  const {input, chapterQuestions} = paperDraftMaterials(candidates, {...inputFixture, output_language:'zh-CN'},
    {omittedFiles:[], chapterPurposes:{}}, 0)
  expect(chapterQuestions.size).toBe(0)
  expect(input.thesis?.chapter_mappings).toEqual([
    {chapter_id:'cover', purpose:'manual', output_language:'project', result_group_ids:[]},
    ...requirements.map(([chapter_id, , purpose]) => ({chapter_id, purpose, output_language:'project',
      result_group_ids:purpose === 'results' ? [`plan-${chapter_id}`] : []})),
    {chapter_id:'references', purpose:'references', output_language:'project', result_group_ids:[]},
  ])
})
