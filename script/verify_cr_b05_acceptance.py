"""Resumable B05 public-API checks for the four authorized quantitative paths."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script/dev'),str(ROOT/'backend')]
import cr_b05_runner as control
from cr_b04_downstream import Ledger
from cr_b05_evidence import lock_materials,verify_comparison,verify_plot
REFERENCES=control.RUNTIME/'references'


def profiles():
    locked=lock_materials(REFERENCES)
    entries={
        'airway-counts':('airway/derived/airway-counts-material.json',63677,'raw_counts','gene-level read counts','Ensembl',9606,'GRCh37.p13; Ensembl release 75; airway 1.32.0','Packaged airway gene counts; four donor/cell lines, paired dexamethasone treatment'),
        'airway-cpm':('airway/derived/airway-cpm-material.json',63677,'normalized','counts per million full-library gene counts','Ensembl',9606,'GRCh37.p13; Ensembl release 75; airway 1.32.0','Full counts multiplied by 1e6 / full sample library sum; same source as airway counts, not independent evidence'),
        'msstats':('MSstats/derived/MSstats-protein-summed-material.json',6,'intensity','summed peptide-ion intensity (source unit unspecified)','MSstats_DDARawData_label',None,'MSstats 4.20 DDARawData labels','Observed peptide Intensity sum(min_count=1) per protein/run; all missing remains NA; not MSstats TMP; 18 technical runs, biological n=0'),
        'sacurine':('ropls/derived/sacurine-log10-material.json',109,'log10','log10 osmolality-normalized LC-HRMS intensity (absolute unit unspecified)','ropls_sacurine_label',9606,'ropls 1.44 sacurine packaged labels','Upstream drift/batch/osmolality correction then log10; observational gender association, age/BMI retained but not adjusted'),
    }
    result={}
    for label,(relative,features,kind,unit,namespace,taxon,reference,upstream) in entries.items():
        material=json.loads((REFERENCES/relative).read_text(encoding='utf-8'))
        assert {relative,*material['files'].values()}<=locked,'Material input missing from fixed SHA index'
        paths={role:REFERENCES/name for role,name in material['files'].items()}
        sample_rows=list(csv.DictReader(paths['sample_metadata'].open(encoding='utf-8'),delimiter='\t'))
        result[label]=dict(label=label,material=material,paths=paths,features=features,samples=sample_rows,
            scale=dict(kind=kind,unit=unit,namespace=namespace,reference_version=reference,species_taxon_id=taxon,
                upstream_method=upstream,upstream_transforms=['log10'] if kind=='log10' else [],zero_meaning='unknown' if kind in ('intensity','log10') else 'measured_zero'),
            params=dict(normalization=material['recommended_parameters_semantics']['normalization'],transform='log1p' if label=='airway-counts' else 'none',log1p_offset=1,
                scaling='none',exclude_samples=[],exclude_features=[],pca_components=3,seed=0,output_language='zh-CN'))
    return result


def import_body(profile,file_ids):
    material=profile['material'];roles=list(profile['paths'])
    return dict(workflow_version='bio_import_v3',assay=material['assay'],name='CR-B05 '+profile['label'],
        file_ids=[file_ids[r] for r in roles],dataset_id=None,expected_dataset_revision=0,
        tables=[dict(file_id=file_ids[r],role=r,format='tsv',sheet=None,header_row=1,encoding='utf-8-sig',delimiter='\t') for r in roles],
        feature_id_column='feature_id',sample_columns=material['sample_columns'],scale=profile['scale'],na_values=['NA'])


def verify_matrices(profile,raw_folder,processed_folder):
    """Compare full frozen source axes/values/missing masks with formal downloads."""
    import numpy as np
    rows=list(csv.DictReader(profile['paths']['quantitative_matrix'].open(encoding='utf-8'),delimiter='\t'))
    columns=profile['material']['sample_columns'];ids=[r['feature_id'] for r in rows]
    original=np.array([[np.nan if r[c]=='NA' else float(r[c]) for c in columns] for r in rows]).T
    missing=np.isnan(original);values=np.where(missing,0,original)
    assert len(ids)==profile['features'] and len(columns)==len(profile['samples'])
    assert json.loads((raw_folder/'samples_index.json').read_text(encoding='utf-8'))['sample_ids']==columns
    assert json.loads((raw_folder/'features_index.json').read_text(encoding='utf-8'))['feature_ids']==ids
    actual=np.load(raw_folder/'matrix_values.npy',allow_pickle=False)
    np.testing.assert_array_equal(np.load(raw_folder/'matrix_missing.npy',allow_pickle=False),missing)
    np.testing.assert_array_equal(actual,values)
    if profile['material']['assay']=='bulk_rna_counts':assert actual.dtype==np.dtype('int64')
    expected=values.copy();params=profile['params']
    if params['normalization']=='display_library_size':
        totals=expected.sum(axis=1);expected=expected/(totals/np.median(totals))[:,None]
    if params['transform']=='log1p':expected=np.log1p(expected)
    expected[missing]=0
    for layer in ('analysis','display'):
        np.testing.assert_array_equal(np.load(processed_folder/(layer+'_missing.npy'),allow_pickle=False),missing)
        np.testing.assert_allclose(np.load(processed_folder/(layer+'_values.npy'),allow_pickle=False),expected,rtol=1e-13,atol=1e-13)
    axes=json.loads((processed_folder/'raw_axes.json').read_text(encoding='utf-8'))
    assert axes['sample_ids']==columns and axes['feature_ids']==ids
    assert np.load(processed_folder/'feature_mask.npy',allow_pickle=False).all()
    assert np.load(processed_folder/'observation_mask.npy',allow_pickle=False).all()
    return dict(full_features=len(ids),full_samples=len(columns),cells=int(values.size),missing=int(missing.sum()),
        exact_raw_values_and_axes=True,processed_values_tolerance=dict(rtol=1e-13,atol=1e-13),no_downsampling=True,params=params)


class Acceptance:
    def __init__(self,evidence='acceptance'):
        if not re.fullmatch(r'acceptance(?:-[a-z0-9]+)*',evidence):
            raise ValueError('Evidence must be a named acceptance attempt inside this batch')
        lock_materials(REFERENCES)
        import httpx
        self.state=control.read_state();control.configure(self.state)
        self.output=control.RUNTIME/evidence;self.output.mkdir(exist_ok=True)
        self.ledger=Ledger(self.output/'receipt.json',dict(schema=self.state['schema'],batch='CR-B05',subpackage=1))
        self.record=self.ledger.record
        self.client=httpx.Client(base_url=self.state['url'],timeout=httpx.Timeout(1200,connect=30),trust_env=False,
            headers={'Origin':self.state['url'],'X-PaperAssist-Client':'web'})
        credential=json.loads((Path(self.state['assets']).parent/'credentials.json').read_text(encoding='utf-8-sig'))['review']
        response=self.check(self.client.post('/api/v1/auth/login',json={k:credential[k] for k in ('email','password')}))
        self.client.headers['X-CSRF-Token']=response.json()['csrf_token']
        self.owner=credential['id']

    def check(self,response):
        if response.status_code not in (200,201,202):
            path=self.output/('http-failure-'+uuid4().hex+'.json')
            control.worker_stack.private_write(path,json.dumps(dict(url=str(response.url),status=response.status_code,body=response.text[:16000]),ensure_ascii=False,indent=2))
            raise RuntimeError(f'HTTP {response.status_code}; retained {path.name}')
        return response

    def get(self,path):return self.check(self.client.get(path)).json()
    def save(self):self.ledger.save()
    @staticmethod
    def base(project):return '/api/v1/projects/'+project

    def post(self,label,path,body,project=None,kind=None,domain='insight',recover=None):
        def lookup(entry):
            if recover:return recover(entry)
            if project and kind:
                route={'insight':'bio-insight-requests','bio':'bio-requests','research':'research-requests'}[domain]
                response=self.client.get(self.base(project)+'/'+route+'/'+entry['key']+'?kind='+kind)
                if response.status_code==404:return None
                value=self.check(response).json()
                if domain=='bio':
                    if kind=='import':return self.get(self.base(project)+'/bio-imports/'+value['id'])
                    if kind=='run':return self.get(self.base(project)+'/bio-analysis-runs/'+value['id'])
                    if kind=='recipe':return self.get(self.base(project)+'/bio-analysis-setups/'+value['root_id']+'/recipes/'+value['id'])
                    if kind in ('confirmation','import_confirmation'):return value
                if domain=='research':
                    if kind=='finding':return self.get(self.base(project)+'/research-findings/'+value['set_id']+'/versions/'+value['id'])
                    return self.get(self.base(project)+{'figure':'/research-figures/','report':'/research-reports/'}[kind]+value['id'])
                return value
            return None
        return self.ledger.post(label,path,body,
            lambda entry:self.check(self.client.post(path,json=body,headers={'Idempotency-Key':entry['key']})).json(),lookup)

    def project(self,label):
        key=label+'-project';old=self.record['actions'].get(key)
        body=old['body'] if old else dict(name='CR-B05 '+label+' '+uuid4().hex[:8],project_type='sci',research_topic='公开定量材料流程验证；非生物学验证、非生产发布')
        def recover(_):
            found=[p for p in self.get('/api/v1/projects') if p['name']==body['name']]
            if len(found)>1:raise ValueError('Project recovery is ambiguous')
            return found[0] if found else None
        return self.post(key,'/api/v1/projects',body,recover=recover)['id']

    def wait(self,task_id,stops=('succeeded',)):
        start=time.monotonic();last=None
        while time.monotonic()-start<7200:
            task=self.get('/api/v1/tasks/'+task_id)
            if task['status']!=last:print(json.dumps(dict(task_id=task_id,status=task['status']),ensure_ascii=False),flush=True);last=task['status']
            if last in stops:return task
            if last in ('failed','cancelled','waiting_confirmation'):raise RuntimeError('Task stopped: '+str(task.get('error_code') or last))
            time.sleep(3)
        raise RuntimeError('Observation wait expired; original task retained, no repeated POST')

    def upload(self,label,project,path):
        content=path.read_bytes();sha=hashlib.sha256(content).hexdigest();key=label+'-batch';old=self.record['actions'].get(key)
        body=old['body'] if old else {'items':[dict(client_id=str(uuid4()),filename=path.name,size_bytes=len(content))]}
        def recover_batch(_):
            page=1;total=1;ids={i['client_id'] for i in body['items']}
            while (page-1)*5<total:
                result=self.get(self.base(project)+'/bio-upload-batches?page='+str(page));total=result['total']
                for item in result['items']:
                    if {i['id'] for i in item['items']}==ids:return item
                page+=1
            return None
        batch=self.post(key,self.base(project)+'/bio-upload-batches',body,recover=recover_batch)
        identifier=body['items'][0]['client_id'];upload_label=label+'-upload';request=dict(batch_id=batch['id'],client_id=identifier,filename=path.name,size_bytes=len(content),sha256=sha)
        def recover(_):
            current=self.get(self.base(project)+'/bio-upload-batches/'+batch['id'])
            item=next(i for i in current['items'] if i['id']==identifier)
            if item.get('file_id'):return item
            return None
        value=self.ledger.post(upload_label,self.base(project)+'/bio-upload-batches/'+batch['id']+'/items/'+identifier,request,
            lambda _:self.check(self.client.post(self.base(project)+'/bio-upload-batches/'+batch['id']+'/items/'+identifier,files={'file':(path.name,content)})).json(),recover)
        return value['file_id']

    def download(self,value,label):
        folder=self.output/'delivery'/label;folder.mkdir(parents=True,exist_ok=True)
        for member in value.get('members',[]):
            if not member['download_url'].startswith('/api/v1/projects/') or any(not re.fullmatch(r'[A-Za-z0-9_.-]+',member[k]) for k in ('key','format')):
                raise ValueError('Unexpected local member name or download URL')
            path=folder/(member['key']+'.'+member['format'])
            if path.exists():raw=path.read_bytes()
            else:
                raw=self.check(self.client.get(member['download_url'])).content
                if hashlib.sha256(raw).hexdigest()!=member['sha256']:raise ValueError('Download SHA differs')
                path.write_bytes(raw)
            if hashlib.sha256(raw).hexdigest()!=member['sha256']:raise ValueError('Retained member SHA differs')
            if len(raw)!=member['size_bytes']:raise ValueError('Member byte length differs')
        record=folder/'result-record.json'
        if not record.exists():record.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        return folder

    def foundation(self,label):
        profile=profiles()[label];project=self.project(label);base=self.base(project)
        files={role:self.upload(label+'-'+role,project,path) for role,path in profile['paths'].items()}
        imported=self.post(label+'-import',base+'/bio-imports',import_body(profile,files),project,'import','bio')
        task=self.wait(imported['task']['id'],('waiting_confirmation','succeeded'))
        detail=self.get(base+'/bio-imports/'+imported['id'])
        if task['status']=='waiting_confirmation':
            body=dict(task_revision=detail['task']['revision'],checkpoint_id=detail['checkpoint_id'],wait_id=detail['wait_id'],candidate_sha256=detail['candidate']['sha256'],expected_dataset_revision=detail['expected_dataset_revision'])
            self.post(label+'-import-confirm',base+'/bio-imports/'+imported['id']+'/confirm',body,project,'import_confirmation','bio')
            self.wait(task['id']);detail=self.get(base+'/bio-imports/'+imported['id'])
        raw=detail['result_source'];version_path=base+'/bio-datasets/'+raw['dataset_id']+'/versions/'+raw['dataset_version_id'];version=self.get(version_path)
        manifest_bytes=self.check(self.client.get(version_path+'/manifest')).content
        if hashlib.sha256(manifest_bytes).hexdigest()!=raw['manifest_sha256']:raise AssertionError('Raw manifest SHA differs')
        manifest=json.loads(manifest_bytes);members={m['id']:m for m in manifest['members']}
        if set(members)!={m['id'] for m in version['members']}:raise AssertionError('Raw public and manifest members differ')
        version={**version,'members':[{**m,'key':members[m['id']]['key'],'format':members[m['id']]['format']} for m in version['members']]}
        raw_folder=self.download(version,label+'-raw')
        recipe=self.post(label+'-recipe',base+'/bio-analysis-setups',dict(recipe_code='tabular_quantitative_v1',name='CR-B05 '+label,raw_source=raw,expected_revision=0,params=profile['params']),project,'recipe','bio')
        run=self.post(label+'-analysis',base+'/bio-analysis-runs',dict(raw_source=raw,recipe_version_id=recipe['id'],expected_setup_revision=1),project,'run','bio')
        task=self.wait(run['task']['id'],('waiting_confirmation','succeeded'));detail=self.get(base+'/bio-analysis-runs/'+run['id'])
        if task['status']=='waiting_confirmation':
            body=dict(task_revision=detail['task']['revision'],checkpoint_id=detail['checkpoint_id'],wait_id=detail['wait_id'],candidate_sha256=detail['candidate']['sha256'],expected_setup_revision=1)
            self.post(label+'-analysis-confirm',base+'/bio-analysis-runs/'+run['id']+'/confirm',body,project,'confirmation','bio')
            self.wait(task['id']);detail=self.get(base+'/bio-analysis-runs/'+run['id'])
        source=detail['result_source'];processed=self.get(base+'/bio-processed-datasets/'+source['processed_dataset_version_id'])
        assert source['assay']==profile['material']['assay'] and source['observation_level']=='sample'
        processed_folder=self.download(processed,label+'-processed')
        matrix_checks=verify_matrices(profile,raw_folder,processed_folder)
        for figure in processed['figures']:
            self.download(self.get(base+'/bio-figures/'+figure['id']),label+'-qc-figure-'+figure['id'])
        self.record.setdefault('paths',{})[label]=dict(project_id=project,raw_source=raw,processed_id=processed['id'],setup_id=recipe['setup_id'],analysis_run_id=run['id'],processed_source=source,features=profile['features'],samples=len(profile['samples']),matrix_checks=matrix_checks)
        self.save();return self.record['paths'][label]

    def analyze(self,label,project,config,sources):
        base=self.base(project);body=dict(name='CR-B05 '+label,kind=config['kind'],decision='confirmed',expected_revision=0,config=config,sources=sources)
        old=self.record['actions'].get(label+'-plan')
        if not old:
            preview=self.check(self.client.post(base+'/bio-insight-plans/preview',json=body)).json()
            control.worker_stack.private_write(self.output/(label+'-design.json'),json.dumps(preview,ensure_ascii=False,indent=2))
            if not preview['executable']:raise RuntimeError('Design blocked; see '+label+'-design.json')
        plan=self.post(label+'-plan',base+'/bio-insight-plans',body,project,'plan')
        run=self.post(label+'-run',base+'/bio-insight-runs',dict(plan_version_id=plan['id'],expected_plan_revision=plan['revision'],source_digest=plan['source_digest']),project,'run')
        task=self.wait(run['task_id']);result=self.get(base+'/bio-insight-results/'+task['result_bio_insight_result_version_id'])
        self.download(result,label);self.record.setdefault('results',{})[label]=dict(project_id=project,id=result['id'],task_id=task['id'],manifest_sha256=result['manifest_sha256'],kind=result['kind'],inference_scope=result['inference_scope']);self.save();return result

    def comparison(self,label):
        record=self.record['paths'][label];profile=profiles()[label];pid=record['processed_id'];counts=label=='airway-counts';paired=label.startswith('airway');technical=label=='msstats'
        conditions=['trt','untrt'] if paired else ['C2','C1'] if technical else ['F','M']
        config=dict(kind='comparison',schema_version=2,mode='bulk_counts' if counts else 'continuous',design='paired' if paired else 'independent',method='deseq2_wald' if counts else 'paired_t' if paired else 'welch_t',analysis_layer='raw_counts' if counts else 'analysis',
            contrasts=[dict(contrast_id='primary',name=conditions[0]+' vs '+conditions[1],groups=[dict(label=c,sample_keys=[dict(processed_version_id=pid,sample_id=s['sample_id']) for s in profile['samples'] if s['condition']==c]) for c in conditions])],family_contrast_ids=['primary'],
            inference_unit='technical' if technical else 'biological',inference_goal='inference' if counts else 'exploratory',independence_confirmed=not technical,independence_basis='' if technical else 'Frozen packaged sample identities; airway cells are paired by donor; sacurine distinct participant IDs are observational units',
            technical_exploration_confirmed=technical,design_basis=profile['scale']['upstream_method'],data_driven_grouping=False,pairing_field='pair_id',batch_adjustment=False,excluded_samples=[],minimum_total_counts=10,size_factor_method='ratio',posthoc='none',missing_policy='complete_cases',
            namespace=profile['scale']['namespace'],reference_version=profile['scale']['reference_version'],species_taxon_id=profile['scale']['species_taxon_id'],output_language='zh-CN')
        source=dict(source_kind='bio_processed_dataset_version',source_id=pid,sha256=record['processed_source']['manifest_sha256'],role='processed',locator={'kind':'object'})
        result=self.analyze(label+'-comparison',record['project_id'],config,[source])
        checks=verify_comparison(profile,self.output/'delivery'/(label+'-comparison'),config,result)
        self.record['results'][label+'-comparison']['comparison_checks']=checks;self.save()
        return result

    def figures(self,label):
        record=self.record['paths'][label];profile=profiles()[label];project=record['project_id'];pid=record['processed_id']
        comparison=self.record['results'][label+'-comparison'];rid=comparison['id']
        result_source=dict(source_kind='bio_insight_result_version',source_id=rid,sha256=comparison['manifest_sha256'],role='result',locator={'kind':'object'})
        processed_source=dict(source_kind='bio_processed_dataset_version',source_id=pid,sha256=record['processed_source']['manifest_sha256'],role='processed',locator={'kind':'object'})
        candidate_config=dict(kind='candidate',result_source_ids=[rid],primary_result_source_id=rid,source_contrasts={rid:'primary'},mapping_source_ids=[],annotation_source_ids=[],steps=[dict(operation='threshold',source_ids=[rid],q_column='q_within_contrast',q_threshold=0.05,minimum_absolute_effect=0.0)],ranking_mode='lexicographic',weights=[],output_language='zh-CN')
        self.analyze(label+'-candidates',project,candidate_config,[result_source])
        selected=['trt','untrt'] if label.startswith('airway') else ['C2','C1'] if label=='msstats' else ['F','M']
        groups=[dict(label=c,sample_keys=[dict(processed_version_id=pid,sample_id=s['sample_id']) for s in profile['samples'] if s['condition']==c]) for c in selected]
        first_feature=next(csv.DictReader(profile['paths']['quantitative_matrix'].open(encoding='utf-8'),delimiter='\t'))['feature_id']
        for kind in ('volcano','heatmap','distribution'):
            config=dict(kind='figure',result_source_id=rid,figure_type=kind,contrast_id='primary',title='CR-B05 '+label+' '+{'volcano':'火山图','heatmap':'样本热图','distribution':'分布图'}[kind],top_n=20,width_inches=7.0,height_inches=5.0,dpi=150,formats=['png','tiff','svg','pdf'],palette=['#2563eb','#dc2626'],output_language='zh-CN')
            sources=[result_source]
            if kind in ('heatmap','distribution'):
                config.update(processed_source_id=pid,sample_groups=groups,expression_groups=[],analysis_layer='analysis',z_score=False,feature_ids=[first_feature] if kind=='distribution' else [])
                sources.append(processed_source)
            result=self.analyze(label+'-'+kind,project,config,sources)
            assert {'png','tiff','svg','pdf'}<={m['format'] for m in result['members']}
            checks=verify_plot(self.output/'delivery'/(label+'-'+kind),self.output/'delivery'/(label+'-comparison'),self.output/'delivery'/(label+'-processed'),config,processed_source)
            self.record['results'][label+'-'+kind]['plot_checks']=checks;self.save()
        return {'id':rid}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','foundation','comparison','figures']);parser.add_argument('--path',choices=list(profiles()));parser.add_argument('--evidence',default='acceptance');args=parser.parse_args()
    if args.action=='prepare':
        from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
        for label,p in profiles().items():
            BioImportRequestV3.model_validate(import_body(p,{r:r for r in p['paths']}))
            print(json.dumps(dict(path=label,features=p['features'],samples=len(p['samples']),files={r:dict(path=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for r,f in p['paths'].items()}),ensure_ascii=False))
        return
    if not args.path:parser.error('--path is required for an explicit execution')
    instance=Acceptance(args.evidence)
    result=getattr(instance,args.action)(args.path)
    print(json.dumps(dict(action=args.action,path=args.path,id=result.get('id',result.get('processed_id'))),ensure_ascii=False))


if __name__=='__main__':main()
