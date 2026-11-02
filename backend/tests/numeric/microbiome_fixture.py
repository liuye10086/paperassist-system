import csv,hashlib,json
from pathlib import Path
from app.adapters.bio_engine.tabular_assays import import_tabular
from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig

def source_fixture(root,scale='counts',vectors=None,taxonomy=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    vectors=vectors or [[10,90],[20,80],[40,60],[60,40],[80,20],[100,0]]
    n=len(vectors);features=['F'+str(j+1) for j in range(len(vectors[0]))];samples=['S'+str(i+1) for i in range(n)]
    rows=[dict(feature_id=f,**{s:None if vectors[i][j] is None else vectors[i][j]/(100 if scale=='fraction' else 1) for i,s in enumerate(samples)}) for j,f in enumerate(features)]
    meta=[dict(sample_id=s,group='A' if i<n//2 else 'B',unit=s,pair='p'+str(i%(n//2))) for i,s in enumerate(samples)]
    taxa=taxonomy or [dict(feature_id=f,Kingdom='Bacteria',Phylum='P',Genus='G'+str(i)) for i,f in enumerate(features)]
    files=[]
    for name,role,records in [('matrix','quantitative_matrix',rows),('samples','sample_metadata',meta),('taxonomy','feature_metadata',taxa)]:
        path=root/(name+'.tsv')
        with path.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]),delimiter='\t');writer.writeheader();writer.writerows(records)
        files.append(dict(id=name,filename=path.name,role=role,path=str(path),format='tsv',size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    config=dict(workflow_version='bio_import_v3',file_ids=[f['id'] for f in files],assay='microbiome',name='synthetic microbiome',expected_dataset_revision=0,tables=[dict(file_id=f['id'],role=f['role'],format='tsv') for f in files],feature_id_column='feature_id',sample_columns=samples,scale=dict(kind='raw_counts' if scale=='counts' else 'relative_abundance',unit=scale,upstream_method='synthetic oracle',namespace='taxonomy',reference_version='fixed'),na_values=['','NA'])
    out=root/'raw';out.mkdir();imported=import_tabular(dict(config=config,files=files,output_directory=str(out)))
    raw=dict(manifest=imported['manifest'],members={m['key']:m for m in imported['outputs']})
    source=dict(source_kind='bio_processed_dataset_version',source_id='processed',role='processed',sha256='a'*64,project_id='synthetic',locator=dict(kind='object'),members={},raw=raw,metadata=dict(assay='microbiome',observations=meta,source_file_ids=['matrix','samples','taxonomy'],raw_dataset_version_id='raw'))
    cfg=MicrobiomeConfig(processed_source_id='processed',abundance_scale=scale,measurement_pipeline='synthetic',classification_database='synthetic',classification_version='1',host_identity='synthetic host',feature_identity='microbial taxa',taxonomy_columns=['Kingdom','Phylum','Genus'],aggregate_rank='Genus',group_column='group',unit_column='unit',closure_confirmed=scale!='counts',closure_basis='explicit synthetic closure' if scale!='counts' else '')
    return source,cfg
