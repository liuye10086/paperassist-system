"""Offline synthetic import/processing gate through the actual isolated child."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3,ENGINE_VERSION
from app.domain.bioinformatics.tabular_settings import engine_code_digest
from app.adapters.bio_insights_engine.worker import actual_identity,warm_render_environment
from app.adapters.bio_insights_engine.probe_transport import monitored_run


def exercise(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    warm=root/'warm';warm.mkdir();warm_render_environment(warm)
    runtime=actual_identity();runtime.update(engine_version=ENGINE_VERSION,code_digest=engine_code_digest(),blockers=[])
    files=[]
    for key,text,role in [('matrix','feature_id,s1,s2,s3\nf1,2,4,8\nf2,4,8,16\nf3,3,NA,12\n','quantitative_matrix'),
        ('samples','sample_id,condition,biological_unit_id\ns1,A,b1\ns2,A,b2\ns3,B,b3\n','sample_metadata')]:
        path=root/(key+'.csv');path.write_text(text,encoding='utf-8')
        files.append(dict(id=key,filename=path.name,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size,role=role))
    config=BioImportRequestV3(workflow_version='bio_import_v3',file_ids=['matrix','samples'],assay='proteomics',name='gate',expected_dataset_revision=0,
        tables=[dict(file_id=f['id'],role=f['role'],format='csv') for f in files],feature_id_column='feature_id',sample_columns=['s1','s2','s3'],
        scale=dict(kind='intensity',unit='AU',upstream_method='offline synthetic')).model_dump()
    identity={k:runtime[k] for k in ('engine_version','environment_digest','code_digest')}
    def child(payload,mode,name):
        directory=root/name;directory.mkdir()
        request={**payload,'mode':mode,'output_directory':str(directory),'_runtime_identity':runtime}
        body=json.dumps(request,allow_nan=False).encode()
        process=monitored_run([sys.executable,'-I','-B',str(Path(__file__).with_name('tabular_worker.py')),str(os.getpid())],
            struct.pack('!I',len(body))+body,timeout=1380)
        (root/(name+'-stderr.txt')).write_bytes(process.stderr)
        if process.returncode or not process.stdout.startswith(b'READY\n'):raise RuntimeError('tabular child transport failed')
        result=json.loads(process.stdout[6:])
        if 'result' not in result:raise RuntimeError('tabular child failed: '+json.dumps(result))
        from app.adapters.bio_tabular_process import validate_tabular_result
        return validate_tabular_result(result['result'],directory,request,mode)
    imported=child(dict(files=files,config=config,identity=identity),'import_v3','import')
    raw=dict(manifest=imported['manifest'],members={m['key']:m for m in imported['outputs']})
    processed=child(dict(raw=raw,config={'transform':'log2'},identity=identity),'compute','compute')
    import numpy as np
    members={m['key']:m for m in processed['outputs']}
    values=np.load(members['analysis_values']['path'],allow_pickle=False);missing=np.load(members['analysis_missing']['path'],allow_pickle=False)
    assert missing.sum()==1 and values[0,0]==1 and values[2,0]==3
    assert np.load(members['pca_feature_mask']['path']).tolist()==[True,True,False]
    assert processed['summary']['pca_components']==2
    return {'tabular_code_digest':engine_code_digest(),'checks':{'tabular_import':True,'tabular_compute':True},'engine_version':ENGINE_VERSION,'runtime_identity':runtime}


if __name__=='__main__':
    result=exercise(Path(sys.argv[1]).absolute())
    print(json.dumps(result,sort_keys=True))
