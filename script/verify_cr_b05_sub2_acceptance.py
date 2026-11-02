"""Resumable subpackage-two public API acceptance; reuse accepted transport helpers."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE']='2'
sys.path[:0]=[str(ROOT/'script'),str(ROOT/'script/dev'),str(ROOT/'backend')]
import cr_b05_runner as control
from verify_cr_b05_acceptance import Acceptance as PreviousAcceptance
from verify_cr_b04_acceptance import Acceptance as OriginalFileAcceptance
from cr_b04_downstream import Ledger


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream,delimiter='\t'))


def qpcr_config(file_id,parse_id):
    folder=control.RUNTIME/'converted'
    raw=rows(folder/'qpcr-long-all-rows.tsv')
    decisions=rows(folder/'proposed-row-decisions.tsv')
    original=rows(folder/'original-fig2a-relative-values.tsv')
    checks=[]
    for value in original:
        match=next(r for r in raw if r['biological_unit_id']==value['author_biological_n'] and r['condition']==value['condition'] and r['target_id']=='PINK1')
        checks.append(dict(sample_id=match['sample_id'],plate_id=match['plate_id'],target_id='PINK1',metric='relative_quantity',
            original_value=float(value['original_relative_PINK1_mRNA']),unit='fold',tolerance=0.0000005,
            precision_basis='原表保留六位小数，容差为最后一位的一半；不同校准配置造成的差异不视作吻合。',
            original_report_source='Tabular Data.xlsx / Fig 2A / '+value['cell']+'; SHA256 '+value['source_file_sha256']+'; 作者未披露精确校准，原报告为独立两组t检验。'))
    return dict(kind='comparison',schema_version=3,mode='qpcr',recipe='qpcr_relative_quantification_v1',output_language='zh-CN',
        file_source_id=file_id,parse_version_id=parse_id,
        columns={k:k for k in ('plate_id','well','sample_id','biological_unit_id','target_id','cq','detection_status','technical_replicate','condition','pair_id')},
        targets=['PINK1'],references=['UBC'],reference_basis='沿用原作者RT-qPCR方法的UBC；本轮不独立证明内参稳定性。',
        calibrator_conditions=['N2B27'],quantification='delta_delta_cq',equal_efficiency_confirmed=True,
        equal_efficiency_basis='沿用作者2^(-ΔΔCt)方法的等效率假设；原RDML无测定效率，属于明确假设下的探索性计算。',
        cross_plate='separate',design='paired',method='paired_t',paired_plate_policy='within_plate_differences',
        paired_plate_basis='主文Methods及Figure2A：4次独立induction，同一批两培养条件同步分化及检测；每对在同一RDML板。仅合并板内ΔCq差，不合并跨板原Cq或宣称通用跨板校准。',
        independence_confirmed=True,independence_basis='作者标记N1至N4代表4次induction；探索性以induction为配对单位，同源细胞系统而非4名供体。',
        contrasts=[dict(contrast_id='BrainPhys_N2B27',name='BrainPhys / N2B27，同板配对',numerator='BrainPhys',denominator='N2B27')],
        family_contrast_ids=['BrainPhys_N2B27'],detected_values=['reported_cq'],
        excluded_wells=[dict(plate_id=r['plate_id'],well=r['well'],reason=r['decision_reason']) for r in decisions if r['proposed_relative_quantification_use']=='exclude'],
        original_checks=checks,namespace='qPCR_assay_label',reference_version='Figshare_29064815_v1',species_taxon_id=9606)


class Acceptance(PreviousAcceptance):
    upload_original=OriginalFileAcceptance.upload

    def __init__(self):
        import httpx
        self.state=control.read_state();control.configure(self.state)
        self.output=control.RUNTIME/'acceptance';self.output.mkdir(exist_ok=True)
        self.ledger=Ledger(self.output/'receipt.json',dict(schema=self.state['schema'],batch='CR-B05',subpackage=2))
        self.record=self.ledger.record
        self.client=httpx.Client(base_url=self.state['url'],timeout=httpx.Timeout(1200,connect=30),trust_env=False,
            headers={'Origin':self.state['url'],'X-PaperAssist-Client':'web'})
        credential=json.loads((Path(self.state['assets']).parent/'credentials.json').read_text(encoding='utf-8-sig'))['review']
        response=self.check(self.client.post('/api/v1/auth/login',json={k:credential[k] for k in ('email','password')}))
        self.client.headers['X-CSRF-Token']=response.json()['csrf_token'];self.owner=credential['id']

    def qpcr(self):
        label='qpcr';project=self.project(label)
        original=self.upload_original(label+'-original',project,control.RUNTIME/'converted/qpcr-long-all-rows.tsv')
        cfg=qpcr_config(original['file_id'],original['parse_version_id'])
        selection=dict(source_kind='original_file',source_id=original['file_id'],sha256=original['sha256'],role='table',
            locator=dict(kind='object',parse_version_id=original['parse_version_id']))
        self.record.setdefault('paths',{})[label]=dict(project_id=project,original=original);self.save()
        result=self.analyze(label+'-comparison',project,cfg,[selection])
        return dict(id=result['id'],project_id=project)


    def stage(self,label,path,body):
        old=self.record['actions'].get(label)
        return self.post(label,path,old['body'] if old else body())

    def qpcr_figure(self):
        label='qpcr';project=self.record['paths'][label]['project_id'];record=self.record['results']['qpcr-comparison']
        result=self.get(self.base(project)+'/bio-insight-results/'+record['id'])
        config=dict(kind='figure',result_source_id=result['id'],figure_type='qpcr_samples',feature_ids=['PINK1'],
            contrast_id='BrainPhys_N2B27',figure_stratum='within_plate_pairs',formats=['png','tiff','svg','pdf'])
        source=dict(source_kind='bio_insight_result_version',source_id=result['id'],sha256=result['manifest_sha256'],role='result')
        plotted=self.analyze('qpcr-figure',project,config,[source])
        return dict(id=plotted['id'],project_id=project)

    def phenotype(self):
        from uuid import UUID,uuid4
        project=self.project('phenotype');project_base=self.base(project)
        path=control.RUNTIME/'converted/sacurine-phenotype.xlsx';content=path.read_bytes();sha=hashlib.sha256(content).hexdigest()
        def recover_upload(_):
            listed=self.get(project_base+'/files')
            files=listed if isinstance(listed,list) else listed['items']
            matches=[r for r in files if r.get('sha256')==sha and r['filename']==path.name]
            if len(matches)>1:raise ValueError('Ambiguous retained phenotype upload')
            return dict(file=matches[0]) if matches else None
        uploaded=self.ledger.post('phenotype-upload',project_base+'/files',dict(filename=path.name,sha256=sha),
            lambda entry:self.check(self.client.post(project_base+'/files',files={'file':(path.name,content)},headers={'Idempotency-Key':str(UUID(entry['key'].removeprefix('b04-downstream-')))})).json(),recover_upload)
        file=uploaded['file'];base=project_base+'/files/'+file['id']
        structure=self.stage('phenotype-structure',base+'/structure-versions',lambda:dict(expected_latest_version=0))
        self.wait(structure['task']['id'])
        structure=self.get(base+'/structure-versions/'+structure['id']);raw=next(d for d in structure['datasets'] if d['sheet_name']=='Phenotype')
        def preparation_body():
            recipe=self.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults?header_row=1&data_range=A2:D184')['recipe']
            for field in recipe['fields']:field['unit']=dict(status='confirmed',value='')
            return dict(dataset_id=raw['id'],recipe=recipe)
        preparation=self.stage('phenotype-preparation',base+'/dataset-preparations',preparation_body)
        task=self.wait(preparation['id'],('waiting_confirmation','succeeded'))
        route='/api/v1/tasks/'+preparation['id']+'/dataset-preparation'
        view=self.get(route)
        def preparation_decision():
            return dict(operation='approve',wait_id=view['wait']['id'],checkpoint_id=view['checkpoint_id'],
                expected_task_revision=view['task']['revision'],input_version=view['task']['input_version'],recipe=None)
        approved=self.stage('phenotype-preparation-approval',route+'/decision',preparation_decision);self.wait(approved['id'])
        prepared=self.get(route)['result']
        selection=dict(task_type='group_comparison',sheet_name='Phenotype',design='independent',method='welch_t',numeric_column='C',group_column='D',
            groups=[dict(kind='text',value='M'),dict(kind='text',value='F')],pair_id_column=None,before_column=None,after_column=None,unit='',
            missing_policy='complete_cases',posthoc='none',assumptions=dict(independent_units=True,distribution='normal',inference_confirmed=True),
            data_roles=dict(individual_id='A',endpoint='C',group='D',structure='independent',
                dictionary=[dict(column='B',name='age',unit='',unit_status='unknown'),dict(column='C',name='bmi',unit='',unit_status='unknown')],
                test_family='One prespecified exploratory BMI M-F Welch comparison; age not adjusted'))
        request=dict(question='sacurine公开样本元数据中，男性与女性BMI的均值有何差异？预设单项Welch探索比较。',output_language='zh-CN',
            population='ropls 1.44 sacurine已授权元数据的183人，M=100，F=83；单位未独立证实。',study_design='横断面公开数据探索性分析；age保留、不调整；不推断因果或临床决策。',
            observation_unit='每个不同sampleMetadata对应一名参与者；沿用来源身份，未作生物学验证。',observation_structure='independent',relationship_description='',
            output_requirements='完整表、实际n、原P、均值差95%CI、单位未知说明、Methods、图和中文报告。均值近似推断假设显式采用，不能据此声称证实正态性。')
        plan=self.stage('phenotype-plan',base+'/analysis-plans',lambda:dict(schema_version=5,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],
            expected_setup_revision=0,selection=selection,research_request=request,evidence_version_ids=[]))
        self.wait(plan['id'],('waiting_input','waiting_confirmation','succeeded'));plan_route='/api/v1/tasks/'+plan['id']+'/analysis-plan';view=self.get(plan_route)
        def source_decision():
            return dict(**{k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')},expected_task_revision=view['task']['revision'],
                source_resolution=dict(confirmed=True,note='明确将研究问题绑定到此183行sacurine元数据XLSX、Phenotype工作表及冻结prepared版本；仅预设BMI M-F Welch，年龄不调整，原件SHA与转换说明已保存。'))
        resolved=self.stage('phenotype-source-confirmation',plan_route+'/source-decisions',source_decision)
        self.wait(resolved['id'],('waiting_confirmation','succeeded'));view=self.get(plan_route)
        def plan_decision():
            issues=view['check']['data_check']['issues']
            if any(i['severity']=='blocking' for i in issues):raise ValueError('New phenotype plan has blocking issues: '+json.dumps(issues,ensure_ascii=False))
            return dict(operation='approve',expected_task_revision=view['task']['revision'],input_version=view['input_version'],checkpoint_id=view['checkpoint_id'],
                wait_id=view['wait_id'],plan_revision=view['plan_revision'],resolutions={i['id']:i['allowed_resolutions'][0] for i in issues})
        approved=self.stage('phenotype-plan-approval',plan_route+'/decisions',plan_decision);self.wait(approved['id'])
        setup=self.get(base+'/analysis-setup')
        statistics=self.stage('phenotype-statistics',base+'/analysis-runs',lambda:dict(expected_revision=setup['revision'],idempotency_key='b05-sub2-statistics-'+uuid4().hex))
        done=self.wait(statistics['id']);result=self.get(base+'/analysis-runs/'+done['result_analysis_run_id'])
        folder=self.output/'delivery/phenotype-statistics';folder.mkdir(parents=True,exist_ok=True)
        control.worker_stack.private_write(folder/'result-record.json',json.dumps(result,ensure_ascii=False,indent=2))
        assert result['statistics']['sample_sizes']==[100,83]
        self.record.setdefault('paths',{})['phenotype']=dict(project_id=project,file_id=file['id'],dataset_id=prepared['id'])
        self.record.setdefault('results',{})['phenotype-statistics']=dict(project_id=project,file_id=file['id'],id=result['id'],task_id=done['id'])
        self.save();return self.record['results']['phenotype-statistics']


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','qpcr','qpcr_figure','phenotype']);args=parser.parse_args()
    if args.action=='prepare':
        from app.domain.bio_insights.qpcr_contracts import QpcrConfig
        config=QpcrConfig.model_validate(qpcr_config('file','parse'))
        print(json.dumps(dict(excluded_wells=len(config.excluded_wells),original_checks=len(config.original_checks),targets=config.targets,paired_plate_policy=config.paired_plate_policy)))
        return
    print(json.dumps(getattr(Acceptance(),args.action)(),ensure_ascii=False))

if __name__=='__main__':main()
