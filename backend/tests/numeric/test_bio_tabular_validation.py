import hashlib
import json
from pathlib import Path
import pytest
from test_bio_tabular_assays import payload


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def review_payload(tmp_path):
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    p=payload(tmp_path)
    path=tmp_path/'f.csv'
    path.write_text('feature_id,display_name,feature_kind,identification,contaminant\na,Protein A,protein_group,identified,false\nb,Protein B,protein_group,putative,true\nc,Protein C,protein_group,identified,false\n',encoding='utf-8')
    p['files'].append(dict(id='f',path=str(path),filename=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size,role='feature_metadata'))
    p['config']['file_ids'].append('f');p['config']['tables'].append(dict(file_id='f',role='feature_metadata',format='csv'))
    p['config']=BioImportRequestV3(**p['config']).model_dump()
    return p


def review_import(tmp_path,p):
    from app.adapters.bio_engine.tabular_assays import import_tabular
    out=tmp_path/'raw';out.mkdir();p['output_directory']=str(out)
    return import_tabular(p),out


def rehash_result(result,key,body=None):
    leaf=next(m for m in result['outputs'] if m['key']==key)
    path=Path(leaf['path'])
    if body is not None:path.write_text(body,encoding='utf-8')
    leaf.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
    if key!='manifest':
        result['manifest']['members']=[{k:v for k,v in m.items() if k!='path'} for m in result['outputs'] if m['key']!='manifest']
        if any(m['key']=='manifest' for m in result['outputs']):
            rehash_result(result,'manifest',json.dumps(result['manifest']))


@pytest.mark.parametrize('key,old,new',[
    ('samples','\tA\t','\tFORGED\t'),('samples','\tu1\t','\tu99\t'),
    ('samples','\t2\n','\t99\n'),('features','identified','FORGED'),
    ('features','false','true'),('features','Protein A','FORGED'),
    ('features_index','protein_group','gene'),('input_scale','intensity','normalized'),
])
def test_parent_reconciles_all_raw_metadata_with_uploaded_tables(tmp_path,key,old,new):
    from app.adapters.bio_tabular_process import validate_tabular_result
    from app.core.exceptions import StorageError
    p=review_payload(tmp_path);r,out=review_import(tmp_path,p)
    validate_tabular_result(r,out,p,'import_v3')
    leaf=next(m for m in r['outputs'] if m['key']==key)
    original=Path(leaf['path']).read_text(encoding='utf-8');assert old in original
    rehash_result(r,key,original.replace(old,new,1))
    with pytest.raises(StorageError):validate_tabular_result(r,out,p,'import_v3')


@pytest.mark.parametrize('field,value',[('role','FORGED'),('source_file_id','s'),('source_member_name','s.csv')])
def test_parent_reconciles_member_role_dependencies(tmp_path,field,value):
    from app.adapters.bio_tabular_process import validate_tabular_result
    from app.core.exceptions import StorageError
    p=review_payload(tmp_path);r,out=review_import(tmp_path,p)
    leaf=next(m for m in r['outputs'] if m['key']=='features');leaf[field]=value
    rehash_result(r,'features')
    with pytest.raises(StorageError):validate_tabular_result(r,out,p,'import_v3')


def test_parent_reconciles_raw_with_one_reread_per_original_table(tmp_path,monkeypatch):
    from app.adapters.bio_engine import tabular_assays as engine
    from app.adapters.bio_tabular_process import validate_tabular_result
    p=review_payload(tmp_path);r,out=review_import(tmp_path,p)
    seen=[];original=engine.iter_table
    def tracked(file,**kwargs):
        seen.append(file['id'])
        return original(file,**kwargs)
    monkeypatch.setattr(engine,'iter_table',tracked)
    validate_tabular_result(r,out,p,'import_v3')
    assert seen==['m','s','f']


@pytest.mark.parametrize('mode',['qc','compute'])
@pytest.mark.parametrize('changed',[{'transform':'log2'},{'exclude_samples':['s1']},{'exclude_features':['a']},{'normalization':'median'}])
def test_parent_binds_self_consistent_output_to_frozen_recipe(tmp_path,monkeypatch,mode,changed):
    from app.adapters.bio_engine import tabular_assays as engine
    from app.adapters.bio_tabular_process import validate_tabular_result
    from app.core.exceptions import StorageError
    monkeypatch.setattr(engine,'_figure',lambda *args:None)
    p=review_payload(tmp_path);raw,_=review_import(tmp_path,p);out=tmp_path/'processed';out.mkdir()
    request=dict(raw=dict(manifest=raw['manifest'],members={m['key']:m for m in raw['outputs']}),config=changed,identity=p['identity'],mode=mode,output_directory=str(out))
    result=engine.run_tabular(request)
    validate_tabular_result(result,out,request,mode)
    with pytest.raises(StorageError):validate_tabular_result(result,out,{**request,'config':{}},mode)


@pytest.mark.parametrize('mode',['qc','compute'])
@pytest.mark.parametrize('key,old,new',[('samples','\tA\t','\tFORGED\t'),('features','identified','FORGED'),('features','false','true'),('raw_axes','Protein A','FORGED')])
def test_parent_reconciles_processed_metadata_to_verified_raw(tmp_path,monkeypatch,mode,key,old,new):
    from app.adapters.bio_engine import tabular_assays as engine
    from app.adapters.bio_tabular_process import validate_tabular_result
    from app.core.exceptions import StorageError
    monkeypatch.setattr(engine,'_figure',lambda *args:None)
    p=review_payload(tmp_path);raw,_=review_import(tmp_path,p);out=tmp_path/'processed';out.mkdir()
    request=dict(raw=dict(manifest=raw['manifest'],members={m['key']:m for m in raw['outputs']}),config={},identity=p['identity'],mode=mode,output_directory=str(out))
    result=engine.run_tabular(request);leaf=next(m for m in result['outputs'] if m['key']==key)
    original=Path(leaf['path']).read_text(encoding='utf-8');assert old in original
    rehash_result(result,key,original.replace(old,new,1))
    with pytest.raises(StorageError):validate_tabular_result(result,out,request,mode)


@pytest.mark.parametrize('normalization,counts,scale,unit',[
    ('display_library_size',True,'normalized','library_size_normalized_counts'),
    ('median',False,'normalized','median_normalized(AU)'),
    ('none',True,'raw_counts','counts'),
])
def test_output_layers_describe_effective_scale_and_preview(tmp_path,monkeypatch,normalization,counts,scale,unit):
    from app.adapters.bio_engine import tabular_assays as engine
    from app.adapters.bio_tabular_reads import dense_preview
    monkeypatch.setattr(engine,'_figure',lambda *args:None)
    p=payload(tmp_path,counts);raw,_=review_import(tmp_path,p);out=tmp_path/'processed';out.mkdir()
    result=engine.run_tabular(dict(raw=dict(manifest=raw['manifest'],members={m['key']:m for m in raw['outputs']}),config={'normalization':normalization},identity=p['identity'],mode='compute',output_directory=str(out)))
    for layer in result['manifest']['layers'].values():
        assert layer['scale']==scale and layer['unit']==unit
        assert layer['input_scale']==raw['manifest']['scale']
        assert layer['normalization']==normalization and layer['transform']=='none'
        assert layer['is_raw_integer_counts'] is (counts and normalization=='none')
    class Objects:
        def read(self,m):return Path(m['path']).read_bytes()
    preview=dense_preview(result['manifest'],result['outputs'],Objects(),1,1,'analysis')
    assert preview['scale']==result['manifest']['layers']['analysis']


@pytest.mark.parametrize('target',['effective_params','methods','recipe','layer','manifest_scale','summary','sample_qc','pca_scores','pca_loadings','pca_variance_ratio','sample_clustering'])
def test_parent_rejects_individual_semantic_tampering(tmp_path,monkeypatch,target):
    from app.adapters.bio_engine import tabular_assays as engine
    from app.adapters.bio_tabular_process import validate_tabular_result
    from app.core.exceptions import StorageError
    monkeypatch.setattr(engine,'_figure',lambda *args:None)
    p=review_payload(tmp_path);raw,_=review_import(tmp_path,p);out=tmp_path/'processed';out.mkdir()
    request=dict(raw=dict(manifest=raw['manifest'],members={m['key']:m for m in raw['outputs']}),config={},identity=p['identity'],mode='compute',output_directory=str(out))
    result=engine.run_tabular(request)
    validate_tabular_result(result,out,request,'compute')
    if target=='effective_params':result['effective_params']['transform']='log2'
    elif target=='methods':
        result['manifest']['methods']['params']['transform']='log2'
        rehash_result(result,'methods',json.dumps(result['manifest']['methods']))
    elif target=='recipe':rehash_result(result,'recipe',json.dumps({'transform':'log2'}))
    elif target=='layer':
        result['manifest']['layers']['analysis']['unit']='FORGED'
        rehash_result(result,'manifest',json.dumps(result['manifest']))
    elif target=='manifest_scale':
        result['manifest']['scale']['unit']='FORGED'
        rehash_result(result,'manifest',json.dumps(result['manifest']))
    elif target=='summary':
        result['summary']['retained_features']=999;result['manifest']['summary']=result['summary']
        rehash_result(result,'manifest',json.dumps(result['manifest']))
    else:
        leaf=next(m for m in result['outputs'] if m['key']==target)
        body=Path(leaf['path']).read_text(encoding='utf-8')
        if target in ('sample_qc','pca_scores','sample_clustering'):body=body.replace('s1','FORGED',1)
        elif target=='pca_loadings':body=body.replace('\na\t','\nFORGED\t',1)
        else:
            lines=body.splitlines();parts=lines[1].split('\t');parts[1]='nan';lines[1]='\t'.join(parts);body='\n'.join(lines)+'\n'
        rehash_result(result,target,body)
    with pytest.raises(StorageError):validate_tabular_result(result,out,request,'compute')
