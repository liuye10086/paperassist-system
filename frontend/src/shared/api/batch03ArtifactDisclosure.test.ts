import {expect,test} from 'vitest'
import {isArtifactDisclosure} from './artifactDisclosure'
const preview={version:5,provider:'openai',task_type:'boxplot',source_digest:'safe-digest',has_saved_result:false,source:{filename:'synthetic.xlsx',sheet_name:'Sheet1',dataset_version:2,parent_dataset_version:1,dataset_kind:'prepared'},summary:{valid_count:3,excluded_count:1,group_count:2,figure_kind:'paired_connected',method:'paired_t',mode:null,output_language:'en',variable_count:2,variables:[{column:'B',name:'Before',unit:'kg'},{column:'C',name:'After',unit:'kg'}],design:'paired',paired_direction:'before_minus_after',posthoc:'none',observation_basis:'complete_pairs'},labels:[{key:'field:B',value:'Before'},{key:'unit:B',value:'kg'},{key:'field:C',value:'After'},{key:'unit:C',value:'kg'},{key:'group:0',value:'Before'},{key:'group:1',value:'After'}]}
test('v5 comparison external preview checks role minimum and rejects ID or invalid algorithm routing',()=>{
 expect(isArtifactDisclosure(preview,'boxplot')).toBe(true)
 expect(isArtifactDisclosure({...preview,labels:[...preview.labels,{key:'pair_id',value:'Secret ID'}]},'boxplot')).toBe(false)
 expect(isArtifactDisclosure({...preview,summary:{...preview.summary,paired_direction:'after_minus_before'}},'boxplot')).toBe(false)
 expect(isArtifactDisclosure({...preview,summary:{...preview.summary,method:'pearson'}},'boxplot')).toBe(false)
 expect(isArtifactDisclosure({...preview,summary:{...preview.summary,variables:[...preview.summary.variables,{column:'A',name:'Secret ID',unit:''}],variable_count:3}},'boxplot')).toBe(false)
})
