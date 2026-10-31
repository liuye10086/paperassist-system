"""Explicit, resumable B04 public-API acceptance. Default verifies receipts only."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script/dev'),str(ROOT/'backend')]
import cr_b04_runner as control
GSE_PROJECT='e8ba52c6-0e85-42ac-8205-dd70f1851f03'
GSE_PROCESSED='f88123c7-b269-5c43-8974-dd36c62ecd46'
SYNTH_PROJECT='6e81ff7a-5ed5-420d-b3e1-7bd6e1cce4c0'
SYNTH_PROCESSED='5a0a21b1-7c5e-54d1-bd34-220163da5cfa'


class Acceptance:
    def __init__(self,wait_seconds=14400):
        if type(wait_seconds) is not int or not 60<=wait_seconds<=14400:raise ValueError('Wait must be between 60 and 14400 seconds')
        self.wait_seconds=wait_seconds
        import httpx
        self.state=control.read_state();control.configure(self.state)
        self.path=control.RUNTIME/'science-acceptance.json'
        self.record=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else dict(schema=self.state['schema'],actions={},results={},
            real_model_calls=0,user_acceptance='pending',real_donor_validation='not_performed',biological_validation='not_performed',real_kegg='not_configured')
        if self.record['schema']!=self.state['schema']:raise ValueError('Wrong retained schema')
        self.client=httpx.Client(base_url=self.state['url'],timeout=1200,trust_env=False,
            headers={'Origin':self.state['url'],'X-PaperAssist-Client':'web'})
        credential=json.loads((Path(self.state['assets']).parent/'credentials.json').read_text(encoding='utf-8'))['review']
        response=self.check(self.client.post('/api/v1/auth/login',json={k:credential[k] for k in ('email','password')},
            timeout=httpx.Timeout(7200,connect=30)))
        self.client.headers['X-CSRF-Token']=response.json()['csrf_token']

    def check(self,response):
        if response.status_code not in (200,201,202):
            receipt=control.RUNTIME/'tasks'/('http-failure-'+uuid4().hex+'.json')
            control.worker_stack.private_write(receipt,json.dumps(dict(status=response.status_code,url=str(response.url),body=response.text[:8000]),indent=2))
            raise RuntimeError(f'HTTP {response.status_code}; retained {receipt.name}')
        return response

    def save(self):control.worker_stack.private_write(self.path,json.dumps(self.record,ensure_ascii=False,indent=2))
    def get(self,path):return self.check(self.client.get(path)).json()
    def current_label(self,label):return self.record.get('label_aliases',{}).get(label,label)
    @staticmethod
    def base(project):return '/api/v1/projects/'+project

    def post(self,label,project,path,body,kind=None):
        hashed=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        old=self.record['actions'].get(label)
        if old:
            if old['digest']!=hashed or old['path']!=path:raise RuntimeError('Retained intent differs; create a reviewed new label')
            if 'response' in old:return old['response']
            if kind is None:raise RuntimeError('Unknown submission: inspect original request; no blind retry')
            value=self.get(self.base(project)+'/bio-insight-requests/'+old['key']+'?kind='+kind)
        else:
            old=dict(key='b04-'+uuid4().hex,path=path,digest=hashed,body=body,status='submitting')
            self.record['actions'][label]=old;self.save()
            response=self.client.post(path,json=body,headers={'Idempotency-Key':old['key']})
            if response.status_code>=400:
                old['error_status']=response.status_code;old['error_body']=response.text;self.save()
            value=self.check(response).json()
        old.update(response=value,status='returned');self.save();return value

    def wait(self,task_id):
        started=time.monotonic();prior=None
        while time.monotonic()-started<self.wait_seconds:
            task=self.get('/api/v1/tasks/'+task_id);status=task['status']
            if status!=prior:print(json.dumps(dict(task_id=task_id,status=status)),flush=True);prior=status
            if status=='succeeded':return task
            if status in ('failed','cancelled','waiting_confirmation'):raise RuntimeError('Task stopped: '+str(task.get('error_code') or status))
            time.sleep(3)
        raise RuntimeError('Wait ended; original task retained, do not resubmit')

    def download(self,value,label):
        directory=control.RUNTIME/'delivery'/label;directory.mkdir(parents=True,exist_ok=True)
        for member in value['members']:
            if member['role']=='input_snapshot':continue
            path=directory/(member['key']+'.'+member['format'])
            if path.is_file():
                if hashlib.sha256(path.read_bytes()).hexdigest()!=member['sha256']:raise ValueError('Retained download differs')
                continue
            content=self.check(self.client.get(member['download_url'])).content
            if hashlib.sha256(content).hexdigest()!=member['sha256']:raise ValueError('Downloaded SHA mismatch')
            path.write_bytes(content)
        control.worker_stack.private_write(directory/'result-record.json',json.dumps(value,ensure_ascii=False,indent=2))
        return directory

    def source(self,project,processed):
        from app.db.database import database_connection
        from app.adapters.storage import ProjectStore
        from app.domain.bio_insights.sources import InsightSourceReader
        with database_connection() as db:
            owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
            row=db.execute('SELECT * FROM bio_processed_dataset_versions WHERE id=%s AND project_id=%s',(processed,project)).fetchone()
            if not row:raise ValueError('Expected copied processed source is missing')
            return InsightSourceReader(ProjectStore(Path(self.state['assets']),owner_id=owner)).resolve(db,project,
                dict(source_kind='bio_processed_dataset_version',source_id=processed,role='processed',sha256=row['manifest_sha256']))

    @staticmethod
    def selection(source):return {k:source[k] for k in ('source_kind','source_id','role','sha256')}

    def analyze(self,label,project,config,sources):
        label=self.current_label(label)
        existing=self.record['results'].get(label)
        if existing:
            value=self.get(self.base(project)+'/bio-insight-results/'+existing['id']);self.download(value,label);return value
        body=dict(name='CR-B04 '+label,kind=config['kind'],decision='confirmed',expected_revision=0,config=config,sources=sources)
        from app.domain.bio_insights.contracts import InsightPlanRequest
        InsightPlanRequest.model_validate(body)
        plan=self.post(label+'-plan',project,self.base(project)+'/bio-insight-plans',body,kind='plan')
        run=self.post(label+'-run',project,self.base(project)+'/bio-insight-runs',dict(plan_version_id=plan['id'],
            expected_plan_revision=plan['revision'],source_digest=plan['source_digest']),kind='run')
        task=self.wait(run['task_id']);rid=task['result_bio_insight_result_version_id']
        value=self.get(self.base(project)+'/bio-insight-results/'+rid)
        self.record['results'][label]=dict(id=rid,project_id=project,task_id=task['id'],plan_id=plan['plan_id'],plan_version_id=plan['id'],run_id=run['id'],
            manifest_sha256=value['manifest_sha256'],inference_scope=value['inference_scope'],summary=value['summary'])
        self.save();self.download(value,label);return value

    def comparisons(self):
        from app.domain.bio_insights.sources import InsightSourceReader
        source=self.source(GSE_PROJECT,GSE_PROCESSED)
        observations=list(InsightSourceReader.read_rows(source['members']['observations']))
        if 'cluster' not in observations[0]:raise ValueError('Expected frozen cluster column missing: '+','.join(observations[0]))
        clusters=sorted({r['cluster'] for r in observations if r['kept'].lower()=='true'})
        first=clusters[0]
        group=lambda label,values:dict(label=label,observation_keys=[dict(processed_version_id=GSE_PROCESSED,barcode=r['barcode']) for r in values])
        a=group('cluster '+first,[r for r in observations if r['kept'].lower()=='true' and r['cluster']==first])
        b=group('other fixed clusters',[r for r in observations if r['kept'].lower()=='true' and r['cluster']!=first])
        config=dict(kind='comparison',mode='spot_exploratory',species_taxon_id=9606,namespace='Ensembl',reference_version='GRCh38_release95',
            contrasts=[dict(contrast_id='cluster_vs_rest',name='fixed cluster '+first+' vs remaining clusters',numerator=a,denominator=b)],
            family_contrast_ids=['cluster_vs_rest'],data_driven_grouping=True)
        sources=[self.selection(source)]
        blocked=dict(name='CR-B04 donor mapping missing (real GSE)',kind='comparison',decision='draft',expected_revision=0,sources=sources,
            config={**config,'mode':'donor_unpaired'})
        preview=self.check(self.client.post(self.base(GSE_PROJECT)+'/bio-insight-plans/preview',json=blocked)).json()
        if preview['executable']:raise AssertionError('Real GSE lacking donors unexpectedly admitted')
        self.record['donor_block']=preview;self.save()
        forward=self.analyze('gse-forward',GSE_PROJECT,config,sources)
        reverse={**config,'contrasts':[{**config['contrasts'][0],'numerator':b,'denominator':a}]}
        backward=self.analyze('gse-reverse',GSE_PROJECT,reverse,sources)
        table=lambda label:list(csv.DictReader((control.RUNTIME/'delivery'/self.current_label(label)/'comparison_results.tsv').open(encoding='utf-8'),delimiter='\t'))
        f=table('gse-forward');r=table('gse-reverse');assert len(f)==len(r)>10000
        mismatches=[]
        for left,right in zip(f,r):
            assert left['feature_id']==right['feature_id']
            for key in ('p_value','q_within_contrast','q_global_family'):
                if left[key]!=right[key]:mismatches.append((left['feature_id'],key))
            if left['effect_value'] and abs(float(left['effect_value'])+float(right['effect_value']))>1e-10:mismatches.append((left['feature_id'],'direction'))
        if mismatches:raise AssertionError('Forward/reverse disagreement: '+repr(mismatches[:5]))
        self.record['gse_comparison_checks']=dict(full_rows=len(f),direction_reversal=True,p_q_identical=True,
            inference_scope='spot_exploratory',reference_evidence='original GSE262082_series_matrix.txt: SpaceRanger 2.0.0 GRCh38_release95',
            numerator_spots=len(a['observation_keys']),denominator_spots=len(b['observation_keys']),clusters=clusters)
        self.save()

    def gse_same_input(self):
        source=self.source(GSE_PROJECT,'a87f36a9-6fea-5348-ad39-e1fc3a0f891d')
        original=self.source(GSE_PROJECT,GSE_PROCESSED)
        if source['metadata']['canonical_dataset_id']!=original['metadata']['canonical_dataset_id']:
            raise ValueError('Alternate representation is not the same canonical data')
        body=json.loads(json.dumps(self.record['actions']['gse-forward-plan']['body']))
        for contrast in body['config']['contrasts']:
            for group in (contrast['numerator'],contrast['denominator']):
                for key in group['observation_keys']:key['processed_version_id']=source['source_id']
        self.analyze('gse-same-input',GSE_PROJECT,body['config'],[self.selection(source)])

    def synthetic_donors(self):
        source=self.source(SYNTH_PROJECT,SYNTH_PROCESSED);observations=source['metadata']['observations']
        if len(observations)!=60 or not all(r['barcode'].startswith('SYNTH_') for r in observations):raise ValueError('Synthetic source differs from retained engineering fixture')
        for mode in ('donor_unpaired','donor_paired'):
            rows=[]
            for i,item in enumerate(observations):
                known=lambda value:dict(status='known',value=value)
                donor=i//10 if mode=='donor_unpaired' else (i%30)//10
                rows.append(dict(barcode=item['barcode'],donor=known('synthetic_donor_'+str(donor)),group=known('A' if i<30 else 'B'),
                    batch=known('synthetic_batch'),sample_id=dict(status='not_applicable',value=None)))
            mapping=self.post(mode+'-mapping',SYNTH_PROJECT,self.base(SYNTH_PROJECT)+'/bio-observation-maps',
                dict(name='CR-B04 synthetic '+mode,raw_source=source['metadata']['raw_source'],expected_revision=0,rows=rows))
            from app.db.database import database_connection
            with database_connection() as db:
                sha=db.execute('SELECT mapping_sha256 FROM bio_observation_map_versions WHERE id=%s AND project_id=%s',
                    (mapping['id'],SYNTH_PROJECT)).fetchone()['mapping_sha256']
            selection=dict(source_kind='bio_observation_map_version',source_id=mapping['id'],role='observation_map',sha256=sha)
            group=lambda label,start,end:dict(label=label,observation_keys=[dict(processed_version_id=SYNTH_PROCESSED,barcode=r['barcode']) for r in observations[start:end] if r['retained']])
            config=dict(kind='comparison',mode=mode,species_taxon_id=9606,namespace='synthetic_gene_id',reference_version='synthetic-B02-fixture',
                contrasts=[dict(contrast_id='synthetic_B_vs_A',name='Synthetic engineering B vs A',numerator=group('B',30,60),denominator=group('A',0,30))],
                family_contrast_ids=['synthetic_B_vs_A'],mapping_confirmed=True,independence_confirmed=True,
                independence_basis='Explicitly synthetic engineering fixture, not customer donors or biological validation',minimum_total_counts=10,data_driven_grouping=False)
            value=self.analyze('synthetic-'+mode,SYNTH_PROJECT,config,[self.selection(source),selection])
            self.record['results']['synthetic-'+mode]['synthetic']=True;self.save()
            if mode=='donor_paired':
                broken=json.loads(json.dumps(config))
                broken['contrasts'][0]['numerator']['observation_keys']=broken['contrasts'][0]['numerator']['observation_keys'][:20]
                preview=self.check(self.client.post(self.base(SYNTH_PROJECT)+'/bio-insight-plans/preview',json=dict(
                    name='CR-B04 incomplete synthetic pair rejection',kind='comparison',decision='draft',expected_revision=0,
                    config=broken,sources=[self.selection(source),selection]))).json()
                assert preview['executable'] is False
                self.record['synthetic_invalid_pair_preview']=preview;self.save()

    def upload(self,label,project,path):
        path=Path(path);sha=hashlib.sha256(path.read_bytes()).hexdigest();old=self.record['actions'].get(label)
        endpoint=self.base(project)+'/bio-resource-files'
        if old:
            if old['sha256']!=sha or old['filename']!=path.name:raise ValueError('Original upload intent changed')
            if 'response' in old:return old['response']
            value=self.get(endpoint+'/requests/'+old['key'])
        else:
            old=dict(key='b04-'+uuid4().hex,path=endpoint,sha256=sha,filename=path.name,status='submitting')
            self.record['actions'][label]=old;self.save()
            with path.open('rb') as stream:
                value=self.check(self.client.post(endpoint,files={'file':(path.name,stream)},headers={'Idempotency-Key':old['key']})).json()
        if value['sha256']!=sha:raise ValueError('Uploaded source SHA mismatch')
        old.update(response=value,status='returned');self.save();return value

    def resource(self,label,project,config):
        self.record.setdefault('resources',{})
        value=self.post(label+'-resource',project,self.base(project)+'/bio-resources',config,kind='resource')
        self.wait(value['task_id']);value=self.get(self.base(project)+'/bio-resources/'+value['id'])
        self.record['resources'][label]=dict(id=value['id'],project_id=project,manifest_sha256=value['manifest_sha256'],task_id=value['task_id'])
        self.save();self.download(value,label);return value

    def resources_final(self):
        # Preserve successful earlier-engine resources; create fresh immutable
        # resource versions for the final code closure and its reproduction.
        self.resources(label_suffix='-final')

    def resources(self,label_suffix=''):
        from cr_b04_references import CACHE,BASE
        cache=CACHE;mapping=cache/'ensembl-to-uniprot.tsv'
        if not mapping.is_file():raise ValueError('Verified fixed-release GPI mapping has not been prepared')
        specs=[]
        for filename,role,fmt in [('go-basic.obo','obo','obo'),('HUMAN-UniProtKB-only.gaf.gz','gaf','gaf.gz')]:
            uploaded=self.upload('go-'+role+'-file',GSE_PROJECT,cache/filename)
            specs.append(dict(file_id=uploaded['file_id'],sha256=uploaded['sha256'],role=role,format=fmt,max_uncompressed_bytes=512*1024**2))
        derivation=json.loads((cache/'gaf-namespace-slice.json').read_text(encoding='utf-8'))
        source=dict(institution='EMBL-EBI / Gene Ontology Consortium',name='GO exchange fixed archive, human UniProtKB namespace',
            description='Matched GO-basic OBO and GAF (ontology releases/2026-06-15) from fixed EBI path 2026-06-16. Explicit DB=UniProtKB and taxon=9606 slice; full original GAF retained, SHA256 '+derivation['input_sha256']+'. Preparation: script/dev/cr_b04_references.py; no customer identifiers used.',
            url=BASE,release_date='2026-06-16')
        usage=dict(basis='Gene Ontology data CC BY 4.0; cite GO Consortium, EBI GOA and the exact release.',redistribution_allowed=True,scope='redistributable')
        self.resource('go-human'+label_suffix,GSE_PROJECT,dict(kind='gene_sets',title='GO human fixed EBI 2026-06-16',species_taxon_id=9606,namespace='UniProtKB',
            release='EBI-GOEX-2026-06-16',source=source,usage=usage,files=specs))
        uploaded=self.upload('go-map-file',GSE_PROJECT,mapping)
        map_source={**source,'name':'GPI explicit Ensembl gene cross references',
            'description':'Derived only from explicit Ensembl gene cross-references in fixed HUMAN GPI. No customer gene list sent; no symbol inference. Assembly reference of analysis remains GRCh38_release95; absent/ambiguous mappings are reported.'}
        self.resource('go-id-mapping'+label_suffix,GSE_PROJECT,dict(kind='id_mapping',title='Ensembl gene to UniProtKB explicit GPI mapping',species_taxon_id=9606,
            namespace='Ensembl',mapping_source_namespace='Ensembl',mapping_target_namespace='UniProtKB',strip_ensembl_version=True,release='EBI-GOEX-2026-06-16',
            source=map_source,usage=usage,files=[dict(file_id=uploaded['file_id'],sha256=uploaded['sha256'],role='id_mapping',format='tsv',
                parse_version_id=uploaded.get('parse_version_id'),columns=dict(source_id='source_id',target_id='target_id'))]))

    def result_source(self,label,role='result'):
        item=self.record['results'][self.current_label(label)]
        return dict(source_kind='bio_insight_result_version',source_id=item['id'],sha256=item['manifest_sha256'],role=role)

    def resource_source(self,label,role):
        item=self.record['resources'].get(label+'-final',self.record['resources'][label])
        return dict(source_kind='bio_resource_version',source_id=item['id'],sha256=item['manifest_sha256'],role=role)

    def enrichments(self):
        result=self.result_source('gse-forward');resource=self.resource_source('go-human','gene_sets');mapping=self.resource_source('go-id-mapping','id_mapping')
        sources=[result,resource,mapping]
        ora=dict(kind='ora',result_source_ids=[result['source_id']],resource_source_ids=[resource['source_id']],mapping_source_ids=[mapping['source_id']],
            contrast_ids=['cluster_vs_rest'],direction='up',q_column='q_within_contrast',q_threshold=.05,minimum_absolute_effect=1.0,min_size=15,max_size=500)
        self.analyze('gse-go-ora',GSE_PROJECT,ora,sources)
        self.analyze('gse-go-ora-empty',GSE_PROJECT,{**ora,'q_threshold':0.,'minimum_absolute_effect':1000000.0},sources)
        gsea=dict(kind='gsea_prerank',result_source_id=result['source_id'],resource_source_ids=[resource['source_id']],mapping_source_ids=[mapping['source_id']],
            contrast_id='cluster_vs_rest',ranking_column='statistic',complete_ranking=True,signed_ranking=True,min_size=15,max_size=500,permutation_num=1000,weight=1.0,seed=0)
        self.analyze('gse-go-gsea',GSE_PROJECT,gsea,sources)

    def candidates(self):
        self.gse_same_input()
        a=self.result_source('gse-forward');b=self.result_source('gse-same-input');ids=[a['source_id'],b['source_id']]
        recipe=dict(kind='candidate',result_source_ids=ids,source_contrasts={sid:'cluster_vs_rest' for sid in ids},primary_result_source_id=ids[0],
            steps=[dict(operation='threshold',source_ids=ids,q_column='q_within_contrast',q_threshold=.05,minimum_absolute_effect=1.),
                   dict(operation='intersection',source_ids=ids),dict(operation='same_direction',source_ids=ids)])
        result=self.analyze('gse-candidates',GSE_PROJECT,recipe,[a,b])
        directory=control.RUNTIME/'delivery/gse-candidates'
        rows=list(csv.DictReader((directory/'candidate_results.tsv').open(encoding='utf-8'),delimiter='\t'))
        assert rows and all(r['support_source_count']=='2' and r['support_count']=='1' and r['same_direction_support_count']=='1' for r in rows)
        self.record['canonical_support_check']=dict(candidate_rows=len(rows),sources=2,dependency_groups=1,biological_independence_verified=False);self.save()
        self.analyze('gse-candidates-empty',GSE_PROJECT,{**recipe,'steps':recipe['steps']+[dict(operation='include',feature_ids=['ABSENT_ENGINEERING_TEST_ID'])]},[a,b])

    def external_and_annotations(self):
        directory=control.RUNTIME/'synthetic-inputs';directory.mkdir(exist_ok=True)
        paths=[]
        for name,text in [('a','gene,effect,p,q\ng1,2,0,0\ng2,-2,1e-320,0.01\ng3,NA,NA,NA\n'),
                          ('b','gene,effect,p,q\ng1,1,0.01,0.02\ng2,2,0.02,0.04\ng4,-1,0.03,0.05\n')]:
            path=directory/('synthetic-external-'+name+'.csv')
            if not path.exists():path.write_text(text,encoding='utf-8')
            original=self.upload('synthetic-external-'+name+'-file',SYNTH_PROJECT,path)
            cfg=dict(kind='result_import',file_source_id=original['file_id'],parse_version_id=original['parse_version_id'],species_taxon_id=9606,
                namespace='synthetic_gene_id',reference_version='synthetic-B04-fixture',columns=dict(feature_id='gene',effect='effect',p_value='p',q_value='q'),
                contrast_id='synthetic_B_vs_A',numerator='B',denominator='A',effect_name='declared_log2fc',effect_unit='log2',
                observation_level='unknown',original_method='Synthetic engineering table; not a customer experiment',original_correction_scope='synthetic declared q; no system recomputation',
                complete_tested_universe=False,recompute_q=False)
            self.analyze('synthetic-external-'+name,SYNTH_PROJECT,cfg,[dict(source_kind='original_file',source_id=original['file_id'],role='table',sha256=original['sha256'])])
        path=directory/'synthetic-feature-annotations.tsv'
        if not path.exists():path.write_text('feature_id\tfield\tvalue\tvalue_type\tunit\tsource\tevidence_status\n'+
            'g1\tflag\tfalse\tboolean\tboolean\tsynthetic engineering input\tprovided\n'+
            'g2\tflag\ttrue\tboolean\tboolean\tsynthetic engineering input\tprovided\n'+
            'g3\tflag\t\tboolean\tboolean\tsynthetic engineering input\tunknown\n'+
            'g1\tscore\t0\tnumber\tarbitrary fixture units\tsynthetic engineering input\tprovided\n',encoding='utf-8')
        uploaded=self.upload('synthetic-annotations-file',SYNTH_PROJECT,path)
        fields=['feature_id','field','value','value_type','unit','source','evidence_status']
        self.resource('synthetic-annotations',SYNTH_PROJECT,dict(kind='feature_annotation',title='Synthetic 0 / false / unknown engineering annotations',
            species_taxon_id=9606,namespace='synthetic_gene_id',release='engineering-v1',
            source=dict(institution='Local engineering fixture',name='Synthetic annotations',description='Not customer sequence/structure measurements; no prediction was performed.'),
            usage=dict(basis='Locally authored synthetic engineering fixture',redistribution_allowed=True,scope='redistributable'),
            files=[dict(file_id=uploaded['file_id'],sha256=uploaded['sha256'],parse_version_id=uploaded['parse_version_id'],role='feature_annotation',format='tsv',columns={k:k for k in fields})]))
        a=self.result_source('synthetic-external-a');b=self.result_source('synthetic-external-b');annotation=self.resource_source('synthetic-annotations','feature_annotation')
        ids=[a['source_id'],b['source_id']]
        config=dict(kind='candidate',result_source_ids=ids,source_contrasts={sid:'synthetic_B_vs_A' for sid in ids},primary_result_source_id=ids[0],
            annotation_source_ids=[annotation['source_id']],steps=[dict(operation='union'),dict(operation='annotation',annotation_field='flag',annotation_operator='eq',annotation_value=False)],
            ranking_mode='weighted',weights=[dict(item='support_fraction',weight=.5,required=True),dict(item='primary_significance',weight=.5,required=False)])
        self.analyze('synthetic-annotated-candidates',SYNTH_PROJECT,config,[a,b,annotation])

    def figures(self):
        result=self.result_source('gse-forward');candidate=self.result_source('gse-candidates');ora=self.result_source('gse-go-ora');gsea=self.result_source('gse-go-gsea')
        def render(label,source,kind,**extra):
            other=extra.pop('sources',[])
            return self.analyze(label,GSE_PROJECT,dict(kind='figure',figure_type=kind,result_source_id=source['source_id'],
                title='CR-B04 '+label,formats=['png','tiff','svg','pdf'],width_inches=7.,height_inches=5.,dpi=300,**extra),[source,*other])
        render('figure-volcano',result,'volcano',contrast_id='cluster_vs_rest',q_column='q_within_contrast')
        source=self.source(GSE_PROJECT,GSE_PROCESSED)
        contrast=self.record['actions']['gse-forward-plan']['body']['config']['contrasts'][0]
        render('figure-heatmap',result,'heatmap',contrast_id='cluster_vs_rest',processed_source_id=GSE_PROCESSED,
            expression_groups=[contrast['numerator'],contrast['denominator']],top_n=20,sources=[self.selection(source)])
        render('figure-enrichment',ora,'enrichment',contrast_id='cluster_vs_rest',top_n=12)
        render('figure-enrichment-bar',ora,'enrichment',contrast_id='cluster_vs_rest',top_n=12,enrichment_style='bar')
        curves=json.loads((control.RUNTIME/'delivery/gse-go-gsea/gsea_curves.json').read_text(encoding='utf-8'))
        if not curves['terms']:raise ValueError('GSEA has no computable curve; retain and report')
        term=max(curves['terms'],key=lambda t:abs(t['nes']))
        render('figure-gsea',gsea,'gsea',term_row_key=term['row_key'])
        same=self.result_source('gse-same-input');reverse=self.result_source('gse-reverse')
        selections=[dict(result_source_id=s['source_id'],contrast_id='cluster_vs_rest',label=label,q_column='q_within_contrast',
            q_threshold=.05,minimum_absolute_effect=1.,direction='up') for s,label in [(result,'forward'),(same,'same-input'),(reverse,'reverse')]]
        render('figure-venn',result,'venn',result_source_ids=[s['result_source_id'] for s in selections],selected_sets=selections,intersection_mode='exclusive',sources=[same,reverse])
        render('figure-upset',result,'upset',result_source_ids=[s['result_source_id'] for s in selections],selected_sets=selections,intersection_mode='all',sources=[same,reverse])
        render('figure-candidate-evidence',candidate,'candidate_evidence',top_n=20)
        render('figure-volcano-recolored',result,'volcano',contrast_id='cluster_vs_rest',q_column='q_within_contrast',
            palette=['#6d28d9','#ea580c'],output_language='en')


def verify():
    state=control.read_state();path=control.RUNTIME/'science-acceptance.json'
    if not path.is_file():raise RuntimeError('Missing actual B04 acceptance receipt')
    value=json.loads(path.read_text(encoding='utf-8'));assert value['schema']==state['schema'] and value['real_model_calls']==0
    required=['gse-forward','gse-reverse','gse-same-input','synthetic-donor_unpaired','synthetic-donor_paired',
        'gse-go-ora','gse-go-ora-empty','gse-go-gsea','gse-candidates','gse-candidates-empty',
        'synthetic-external-a','synthetic-external-b','synthetic-annotated-candidates',
        'figure-volcano','figure-heatmap','figure-enrichment','figure-enrichment-bar','figure-gsea',
        'figure-venn','figure-upset','figure-candidate-evidence','figure-volcano-recolored']
    missing=[label for label in required if value.get('label_aliases',{}).get(label,label) not in value['results']]
    if missing:raise RuntimeError('Acceptance incomplete: '+','.join(missing))
    for label in ('go-human-final','go-id-mapping-final','synthetic-annotations'):
        if label not in value.get('resources',{}):raise RuntimeError('Acceptance resource incomplete: '+label)
    assert value['donor_block']['executable'] is False
    assert value['gse_comparison_checks']['direction_reversal'] and value['gse_comparison_checks']['p_q_identical']
    assert value['canonical_support_check']['dependency_groups']==1
    for label,result in {**value['results'],**value['resources']}.items():
        directory=control.RUNTIME/'delivery'/label
        saved=json.loads((directory/'result-record.json').read_text(encoding='utf-8'))
        assert saved['id']==result['id']
        for member in saved['members']:
            if member['role']=='input_snapshot':continue
            path=directory/(member['key']+'.'+member['format'])
            assert path.stat().st_size==member['size_bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==member['sha256']
    print(json.dumps(dict(status='verified_recorded_science_outputs',result_count=len(value['results']),user_acceptance='pending')))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',choices=['comparisons','synthetic_donors','resources','resources_final','enrichments','candidates','external_and_annotations','figures'])
    parser.add_argument('--wait-seconds',type=int,default=14400,help='Per-task observation window, 60..14400 seconds; expiry never cancels or resubmits a task')
    args=parser.parse_args()
    if not 60<=args.wait_seconds<=14400:parser.error('--wait-seconds must be between 60 and 14400')
    if args.execute:getattr(Acceptance(wait_seconds=args.wait_seconds),args.execute)()
    else:verify()
