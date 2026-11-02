"""Resumable CR-B05 subpackage-three acceptance; retain completed actions."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE']='3'
sys.path[:0]=[str(ROOT/'script'),str(ROOT/'script/dev'),str(ROOT/'backend')]
import cr_b05_runner as control
from verify_cr_b05_acceptance import Acceptance as PreviousAcceptance
from cr_b04_downstream import Ledger


class Acceptance(PreviousAcceptance):
    def __init__(self):
        import httpx
        self.state=control.read_state();control.configure(self.state)
        self.output=control.RUNTIME/'acceptance';self.output.mkdir(exist_ok=True)
        self.ledger=Ledger(self.output/'receipt.json',dict(schema=self.state['schema'],batch='CR-B05',subpackage=3))
        self.record=self.ledger.record
        self.client=httpx.Client(base_url=self.state['url'],timeout=httpx.Timeout(1200,connect=30),trust_env=False,
            headers={'Origin':self.state['url'],'X-PaperAssist-Client':'web'})
        credential=json.loads((Path(self.state['assets']).parent/'credentials.json').read_text(encoding='utf-8-sig'))['review']
        response=self.check(self.client.post('/api/v1/auth/login',json={k:credential[k] for k in ('email','password')}))
        self.client.headers['X-CSRF-Token']=response.json()['csrf_token'];self.owner=credential['id']

    def import_source(self,label,project,config,expected_shape,expected_entries=None):
        base=self.base(project)
        import_label=label+'-import'+('-identity-fixed' if config['assay']=='microbiome' else '')
        imported=self.post(import_label,base+'/bio-imports',config,project,'import','bio')
        task=self.wait(imported['task']['id'],('waiting_confirmation','succeeded'))
        detail=self.get(base+'/bio-imports/'+imported['id'])
        if task['status']=='waiting_confirmation':
            body=dict(task_revision=detail['task']['revision'],checkpoint_id=detail['checkpoint_id'],wait_id=detail['wait_id'],candidate_sha256=detail['candidate']['sha256'],expected_dataset_revision=detail['expected_dataset_revision'])
            self.post(label+'-import-confirm',base+'/bio-imports/'+imported['id']+'/confirm',body,project,'import_confirmation','bio')
            self.wait(task['id']);detail=self.get(base+'/bio-imports/'+imported['id'])
        raw=detail['result_source'];version_path=base+'/bio-datasets/'+raw['dataset_id']+'/versions/'+raw['dataset_version_id']
        version=self.get(version_path);manifest_bytes=self.check(self.client.get(version_path+'/manifest')).content
        assert hashlib.sha256(manifest_bytes).hexdigest()==raw['manifest_sha256']
        manifest=json.loads(manifest_bytes)
        assert manifest['input_shape']==expected_shape
        if expected_entries is not None:assert manifest['stored_entries']==expected_entries
        members={m['id']:m for m in manifest['members']}
        version={**version,'members':[{**m,'key':members[m['id']]['key'],'format':members[m['id']]['format']} for m in version['members']]}
        self.download(version,label+'-raw')
        return raw

    def process_raw(self,label,project,raw,recipe_body,assay):
        base=self.base(project)
        recipe=self.post(label+('-recipe-with-design' if recipe_body.get('design_version_id') else '-recipe'),base+'/bio-analysis-setups',recipe_body,project,'recipe','bio')
        run=self.post(label+'-analysis',base+'/bio-analysis-runs',dict(raw_source=raw,recipe_version_id=recipe['id'],expected_setup_revision=1),project,'run','bio')
        task=self.wait(run['task']['id'],('waiting_confirmation','succeeded'));detail=self.get(base+'/bio-analysis-runs/'+run['id'])
        if task['status']=='waiting_confirmation':
            body=dict(task_revision=detail['task']['revision'],checkpoint_id=detail['checkpoint_id'],wait_id=detail['wait_id'],candidate_sha256=detail['candidate']['sha256'],expected_setup_revision=1)
            self.post(label+'-analysis-confirm',base+'/bio-analysis-runs/'+run['id']+'/confirm',body,project,'confirmation','bio')
            self.wait(task['id']);detail=self.get(base+'/bio-analysis-runs/'+run['id'])
        source=detail['result_source'];processed=self.get(base+'/bio-processed-datasets/'+source['processed_dataset_version_id'])
        assert processed['manifest']['assay']==assay
        self.download(processed,label+'-processed')
        for figure in processed['figures']:self.download(self.get(base+'/bio-figures/'+figure['id']),label+'-figure-'+figure['id'])
        self.record.setdefault('paths',{})[label]=dict(project_id=project,raw_source=raw,processed_id=processed['id'],setup_id=recipe['setup_id'],analysis_run_id=run['id'],processed_source=source,observation_map_id=recipe_body.get('observation_map_version_id'))
        self.save();return self.record['paths'][label]


    def cell(self):
        label='pbmc3k';project=self.project(label);base=self.base(project)
        original=control.RUNTIME/'materials/original/pbmc3k_filtered_gene_bc_matrices.tar.gz'
        file_id=self.upload(label+'-original',project,original)
        config=dict(workflow_version='bio_import_v4',assay='single_cell',file_ids=[file_id],name='PBMC3k 原始单细胞计数',expected_dataset_revision=0,matrix_representation='mtx',two_column_feature_type='Gene Expression')
        raw=self.import_source(label,project,config,dict(features=32738,observations=2700),2286884)
        source=control.RUNTIME/'materials/derived/pbmc3k'
        barcodes=(source/'barcodes.tsv').read_text().splitlines()
        known=lambda value:dict(status='known',value=value)
        design_path=base+'/research-designs'
        design=self.post(label+'-design-with-source',design_path,dict(expected_revision=1,operation='save',content=dict(schema_version=1,
            experiments=[dict(id='pbmc3k',data_type='single_cell')],groups=[dict(id='source',experiment_id='pbmc3k',name='来源样本（无组间比较）')],
            samples=[dict(id='PBMC3k',experiment_id='pbmc3k',group_id='source',donor=dict(state='known',value='PBMC3k_donor_1'),bio_dataset_version_id=raw['dataset_version_id'])]),material_refs=[dict(bio_dataset_version_id=raw['dataset_version_id'],availability='provided',purpose='raw_data')]),
            recover=lambda entry: self.get(design_path+'/requests/'+entry['key']))
        mapping=self.post(label+'-map-with-design',base+'/bio-observation-maps',dict(name='PBMC3k 单一样本；供体推断不适用',raw_source=raw,expected_revision=0,design_version_id=design['version']['id'],rows=[dict(barcode=b,sample_id=known('PBMC3k'),donor=known('PBMC3k_donor_1')) for b in barcodes]),project,'map','bio')
        mt=[r[0] for r in csv.reader((source/'genes.tsv').open(encoding='utf-8'),delimiter='\t') if r[1].startswith('MT-')]
        params=dict(in_tissue_only=False,min_counts=1,min_genes=200,min_spots=3,max_mt_fraction=0.2,mt_rule=dict(kind='feature_ids',feature_ids=mt,confirmed=True),target_sum=10000.0,hvg_count=2000,pca_components=30,neighbors=15,resolution=0.5,seed=0,marker_top_n=5,output_language='zh-CN',donor_design_confirmed=False)
        return self.process_raw(label,project,raw,dict(recipe_code='single_cell_explore_v1',name='PBMC3k QC与细胞群探索',raw_source=raw,observation_map_version_id=mapping['id'],design_version_id=design['version']['id'],expected_revision=0,params=params),'single_cell')


    def microbiome(self):
        label='enterotype';project=self.project(label);base=self.base(project)
        directory=control.RUNTIME/'materials/derived/enterotype'
        paths={'quantitative_matrix':directory/'abundance-relativefraction-source.tsv','sample_metadata':directory/'samples-source.tsv','feature_metadata':directory/'taxonomy-source.tsv'}
        files={role:self.upload(label+'-'+role,project,path) for role,path in paths.items()}
        with paths['quantitative_matrix'].open(encoding='utf-8') as stream:samples=next(csv.reader(stream,delimiter='\t'))[1:]
        config=dict(workflow_version='bio_import_v3',file_ids=list(files.values()),assay='microbiome',name='enterotype 原始属级相对丰度',expected_dataset_revision=0,
            tables=[dict(file_id=f,role=role,format='tsv') for role,f in files.items()],feature_id_column='feature_id',sample_columns=samples,na_values=['','NA','N/A',r'\N'],
            scale=dict(kind='relative_abundance',unit='fraction',upstream_method='phyloseq enterotype 固定来源相对丰度，原始计数与测序深度未提供；本系统尚未闭合。',namespace='microbial_genus',reference_version='phyloseq_8a6c2350b985afb909428d396081605e9b3e2f0b'))
        raw=self.import_source(label,project,config,dict(features=553,observations=280),553*280)
        return self.process_raw(label,project,raw,dict(recipe_code='tabular_quantitative_v1',name='enterotype 原尺度保留与质量检查',raw_source=raw,expected_revision=0,params=dict(normalization='none',transform='none',scaling='none',pca_components=10,seed=0,output_language='zh-CN')),'microbiome')

    def cell_figure_fix(self):
        record=self.record['paths']['pbmc3k'];base=self.base(record['project_id'])
        processed=self.get(base+'/bio-processed-datasets/'+record['processed_id'])
        original=next(f for f in processed['figures'] if f['config']['kind']=='umap')
        request=dict(processed_source=record['processed_source'],expected_version=0,config=original['config'])
        figure=self.post('pbmc3k-umap-minus-fixed',base+'/bio-figures',request,record['project_id'],'figure','bio')
        self.wait(figure['task']['id']);figure=self.get(base+'/bio-figures/'+figure['id'])
        self.download(figure,'pbmc3k-umap-minus-fixed')
        record['repaired_figure_id']=figure['id'];self.save()
        return dict(id=figure['id'],reused_processed_id=record['processed_id'])

    def microbiome_analysis(self):
        from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig
        label='enterotype';record=self.record['paths'][label];pid=record['processed_id']
        config=MicrobiomeConfig(processed_source_id=pid,abundance_scale='fraction',rounding_tolerance=0.0002,closure_confirmed=True,
            closure_basis='固定源表列和为0.99985602至1.00000014；显式以每列原总和闭合，保留原总和及乘数，不推断偏差原因。',
            measurement_pipeline='公开多队列粪便群落相对丰度；原SeqTech和Project逐样本保留，原始计数不可得。',classification_database='source_genus_labels',classification_version='unknown_in_material',
            host_identity='Homo sapiens，来源元数据；宿主不代表微生物物种',feature_identity='553个来源属级特征；两项未分类保留',taxonomy_columns=['Genus'],aggregate_rank='Genus',
            taxonomy_na_values=['','NA','N/A',r'\N'],design='descriptive',beta_inference=False,permutations=999,seed=0,top_n=10)
        source=dict(source_kind='bio_processed_dataset_version',source_id=pid,sha256=record['processed_source']['manifest_sha256'],role='processed',locator=dict(kind='object'))
        result=self.analyze(label+'-comparison',record['project_id'],config.model_dump(mode='json'),[source])
        return dict(id=result['id'],project_id=record['project_id'])

    def microbiome_figure(self):
        label='enterotype';record=self.record['results'][label+'-comparison'];project=record['project_id']
        source=dict(source_kind='bio_insight_result_version',source_id=record['id'],sha256=record['manifest_sha256'],role='result',locator=dict(kind='object'))
        result_ids={}
        for kind,title in [('composition','属级组成'),('alpha','Shannon样本分布'),('pcoa','Bray–Curtis PCoA')]:
            key=label+'-figure' if kind=='composition' else label+'-'+kind+'-figure'
            config=dict(kind='figure',result_source_id=record['id'],figure_type='microbiome_'+kind,title='enterotype '+title+'（完整表保留）',formats=['png','tiff','svg','pdf'],top_n=10,output_language='zh-CN',width_inches=10.0,height_inches=6.0,
                palette=['#2563eb','#dc2626','#16a34a','#9333ea','#ea580c','#0891b2','#ca8a04','#db2777','#4f46e5','#64748b','#a3a3a3'])
            if kind=='alpha':config['feature_ids']=['shannon']
            result=self.analyze(key,project,config,[source]);result_ids[kind]=result['id']
        return dict(ids=result_ids,project_id=project)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['cell','cell_figure_fix','microbiome','microbiome_analysis','microbiome_figure']);args=parser.parse_args()
    acceptance=Acceptance()
    try:print(json.dumps(getattr(acceptance,args.action)(),ensure_ascii=False))
    finally:acceptance.client.close()


if __name__=='__main__':main()
