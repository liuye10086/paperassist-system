import { expect,test } from 'vitest'
import { isArtifactDisclosure } from './artifactDisclosure'
export const disclosure={version:4,provider:'openai',task_type:'boxplot',source_digest:'digest',has_saved_result:false,source:{filename:'synthetic.xlsx',sheet_name:'Sheet1',dataset_version:1,parent_dataset_version:1,dataset_kind:'prepared'},summary:{valid_count:4,excluded_count:0,group_count:0,figure_kind:'scatter',method:'pearson',mode:'pair',output_language:'en',variable_count:2,variables:[{column:'C',name:'weight',unit:'kg'},{column:'D',name:'height',unit:'cm'}]},labels:[{key:'field:C',value:'weight'},{key:'unit:C',value:'kg'},{key:'field:D',value:'height'},{key:'unit:D',value:'cm'}]}
test('validates exact modern external labels and rejects matrix or field spoofing',()=>{
 expect(isArtifactDisclosure(disclosure,'boxplot')).toBe(true)
 expect(isArtifactDisclosure({...disclosure,labels:disclosure.labels.slice(1)},'boxplot')).toBe(false)
 expect(isArtifactDisclosure({...disclosure,summary:{...disclosure.summary,figure_kind:'correlation_heatmap'}},'boxplot')).toBe(false)
 const explanation={...disclosure,task_type:'explanation',labels:[...disclosure.labels,{key:'figure_title',value:'Figure 1'},{key:'research_summary',value:''}]}
 expect(isArtifactDisclosure(explanation,'explanation')).toBe(true)
})
