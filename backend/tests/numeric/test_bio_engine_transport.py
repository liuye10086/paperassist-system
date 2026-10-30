import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import numpy as np
from scipy import sparse


def payload_fixture(tmp_path):
    source=tmp_path/'input';source.mkdir();output=tmp_path/'output';output.mkdir()
    matrix=sparse.csr_matrix(np.random.default_rng(22).poisson(4,(24,16)).astype('int64'))
    members={}
    def add(key,value,fmt):
        path=source/(key+'.'+fmt)
        if fmt=='npy':np.save(path,value,allow_pickle=False)
        else:path.write_text(json.dumps(value),encoding='utf8')
        members[key]={'path':str(path),'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'role':key,'format':fmt}
    for key,value in [('matrix_data',matrix.data),('matrix_indices',matrix.indices),('matrix_indptr',matrix.indptr)]:add(key,value,'npy')
    barcodes=['b'+str(i) for i in range(24)]
    add('features_index',{'feature_ids':['g'+str(i) for i in range(16)],'feature_symbols':['symbol']*16,'feature_types':['Gene Expression']*16},'json')
    add('barcodes_index',{'barcodes':barcodes},'json')
    add('positions_index',[{'barcode':b,'in_tissue':1,'pxl_col_in_fullres':i%6*20,'pxl_row_in_fullres':i//6*20} for i,b in enumerate(barcodes)],'json')
    add('observation_map_index',{'schema_version':1,'rows':[{'barcode':b,'section':{'status':'known','value':'section_A' if i<12 else 'section_B'},'donor':{'status':'pending','value':None}} for i,b in enumerate(barcodes)]},'json')
    from PIL import Image
    for key,fmt,color in [('auxiliary','jpeg','red'),('hires','png','white')]:
        path=source/(key+'.'+fmt);Image.new('RGB',(120,80),color).save(path)
        members[key]={'path':str(path),'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'role':'tissue_image','format':fmt,'source_member_name':key+'.'+fmt}
    spatial={'images':[{'source_member_name':'auxiliary.jpeg','scale_field':None},{'source_member_name':'hires.png','scale_field':'tissue_hires_scalef'}],
        'scalefactors':{'tissue_hires_scalef':.5,'spot_diameter_fullres':12.}}
    return {'mode':'compute','raw':{'manifest':{'input_shape':{'observations':24,'features':16},'spatial':spatial},'members':members},'config':{'hvg_count':12,'pca_components':5,'neighbors':5,'seed':13,'target_sum':2000,'resolution':.5,'exclude_barcodes':['b0']},'identity':{'raw_source':{'version':'fixed'},'code_digest':'synthetic','environment_digest':'synthetic'},'output_directory':str(output)},matrix


def child(payload):
    worker=Path(__file__).resolve().parents[2]/'app/adapters/bio_engine/worker.py'
    data=json.dumps(payload).encode()
    result=subprocess.run([sys.executable,'-I','-B',str(worker),str(os.getpid())],input=struct.pack('!I',len(data))+data,capture_output=True,env={},timeout=300)
    assert result.returncode==0,result.stderr.decode()
    assert result.stdout.startswith(b'READY\n')
    if b'"error"' in result.stdout:print(result.stderr.decode(),file=sys.stderr)
    answer=json.loads(result.stdout.split(b'\n',1)[1]);assert 'error' not in answer,(answer,result.stderr.decode())
    return answer['result']


def test_compute_in_real_sandbox_roundtrips_layers_and_hashes(tmp_path):
    payload,raw=payload_fixture(tmp_path)
    result=child(payload)
    assert result['status']=='completed'
    assert result['summary']['pca_components']==5
    assert result['checks']['h5ad_roundtrip']=='verified'
    outputs={m['key']:m for m in result['outputs']}
    assert {'processed','markers','markers_top','observations','features','methods','manifest','pca','umap'}<=set(outputs)
    for member in outputs.values():
        assert hashlib.sha256(Path(member['path']).read_bytes()).hexdigest()==member['sha256']
    import anndata as ad
    obj=ad.read_h5ad(outputs['processed']['path'])
    np.testing.assert_array_equal(obj.layers['counts'].toarray(),raw.toarray()[1:,:])
    assert list(obj.obs_names)==['b'+str(i) for i in range(1,24)]
    assert obj.obs['raw_index'].tolist()==list(range(1,24))
    np.testing.assert_allclose(np.asarray(obj.layers['normalized'].sum(1)).ravel(),2000,rtol=1e-6)
    assert obj.obsm['X_pca'].shape==(23,5)
    assert np.isfinite(obj.obsm['X_umap']).all()
    assert result['summary']['exclusion_union_count']==1
    assert result['summary']['exclusion_reason_counts']=={'explicit_exclusion':1}
    assert 'mapping_strata' in outputs and 'qc_by_section_png' in outputs
    # Original canonical leaf was never written by the child.
    for member in payload['raw']['members'].values():assert hashlib.sha256(Path(member['path']).read_bytes()).hexdigest()==member['sha256']


def test_standalone_figure_keeps_processed_hash_and_cluster_identity(tmp_path):
    payload,_=payload_fixture(tmp_path);processed=child(payload)
    output=tmp_path/'figure';output.mkdir()
    request={**payload,'mode':'figure','processed':{'manifest':processed['manifest'],'members':{m['key']:m for m in processed['outputs']}},'config':{'kind':'spatial_gene','gene_ids':['g1'],'layer':'normalized','palette':'magma','width':1200,'height':1000,'dpi':200,'output_language':'zh-CN','title':'空间基因表达'},'output_directory':str(output)}
    # Published analyses include every preserved figure/table leaf. Exercise
    # distinct files, rather than many keys pointing to one deduplicated inode.
    members=request['processed']['members']
    for index in range(256-len(members)):
        path=tmp_path/('preserved_'+str(index)+'.json');path.write_text(json.dumps({'index':index}))
        members['preserved_'+str(index)]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size_bytes':path.stat().st_size,'role':'table','format':'json'}
    result=child(request)
    assert any(m['format']=='png' for m in result['outputs'])
    grouped=tmp_path/'grouped';grouped.mkdir()
    request.update(output_directory=str(grouped),config={'kind':'pca','color_by':'section','width':1200,'height':1000,'dpi':200})
    grouped_result=child(request)
    plot_data=next(m for m in grouped_result['outputs'] if m['key']=='pca_data')
    labels=json.loads(Path(plot_data['path']).read_bytes())['color_labels']
    assert labels==['section_A']*11+['section_B']*12
    # Frozen default configs retain panel identity when only a title changes.
    for prefix in ['pca_variance','qc_scatter','qc_by_section']:
        original=next(m for m in processed['outputs'] if m['key']==prefix+'_manifest')
        frozen=json.loads(Path(original['path']).read_bytes())['config']
        redrawn=tmp_path/('redraw_'+prefix);redrawn.mkdir()
        config={k:v for k,v in frozen.items() if k in {'kind','panel','palette','layer','gene_ids','color_by','output_language'}}
        config.update(title='Retitled '+prefix,width=1200,height=1000,dpi=200)
        request.update(output_directory=str(redrawn),config=config)
        changed=child(request)
        assert sum(m['format']=='png' for m in changed['outputs'])==1
        before=next(m for m in processed['outputs'] if m['key']==prefix+'_data')
        after=next(m for m in changed['outputs'] if m['key']==prefix+'_data')
        assert json.loads(Path(before['path']).read_bytes())==json.loads(Path(after['path']).read_bytes())
    for member in processed['outputs']:assert hashlib.sha256(Path(member['path']).read_bytes()).hexdigest()==member['sha256']


def test_worker_rejects_member_groups_over_the_fixed_budget(tmp_path):
    worker=Path(__file__).resolve().parents[2]/'app/adapters/bio_engine/worker.py'
    for group,limit in [('raw',256),('processed',256),('annotation',2)]:
        output=tmp_path/group;output.mkdir()
        payload={'mode':'figure','output_directory':str(output),group:{'members':{str(i):{} for i in range(limit+1)}}}
        data=json.dumps(payload).encode()
        result=subprocess.run([sys.executable,'-I','-B',str(worker),str(os.getpid())],input=struct.pack('!I',len(data))+data,capture_output=True,env={},timeout=240)
        assert result.returncode==0,result.stderr.decode()
        assert json.loads(result.stdout.split(b'\n',1)[1])=={'error':{'code':'bio_resource_exceeded'}}
        assert not list(output.iterdir())


def test_qc_candidate_stops_before_normalization(tmp_path):
    payload,_=payload_fixture(tmp_path);payload['mode']='qc'
    result=child(payload)
    outputs={m['key']:m for m in result['outputs']}
    assert 'processed' not in outputs and 'normalized_data' not in outputs
    assert result['summary']['raw_observations']==24 and result['summary']['retained_observations']==23
    assert next(s for s in result['steps'] if s['key']=='umap')['status']=='not_requested'


def test_h5_check_protocol_reads_all_values_and_emits_v1_axes(tmp_path):
    from test_bio_hdf5 import fixture
    source=tmp_path/'h5';fixture(source)
    output=tmp_path/'output';output.mkdir()
    descriptor={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'size_bytes':source.stat().st_size,'role':'alternate_matrix','format':'h5'}
    result=child({'mode':'h5_check','raw':{'members':{'source_003':descriptor}},'h5_member_key':'source_003','output_directory':str(output)})
    members={m['key']:m for m in result['outputs']}
    np.testing.assert_array_equal(np.load(members['matrix_data']['path']),[1,2,3])
    assert np.load(members['matrix_indptr']['path']).dtype==np.int64
    assert result['manifest']['input_shape']=={'features':2,'observations':2}
    assert next(s for s in result['steps'] if s['key']=='h5_read')['status']=='completed'


def test_two_independent_children_are_numerically_and_graphically_deterministic(tmp_path):
    a=tmp_path/'first';b=tmp_path/'second';a.mkdir();b.mkdir()
    first=child(payload_fixture(a)[0]);second=child(payload_fixture(b)[0])
    left={m['key']:m for m in first['outputs']};right={m['key']:m for m in second['outputs']}
    for key in ['counts_data','counts_indices','counts_indptr','observation_mask','feature_mask','hvg_mask']:
        np.testing.assert_array_equal(np.load(left[key]['path']),np.load(right[key]['path']))
    for key in ['normalized_data','log1p_data','pca','umap','pca_loadings']:
        np.testing.assert_allclose(np.load(left[key]['path']),np.load(right[key]['path']),rtol=1e-5,atol=1e-6)
    for key in ['markers','markers_top','embedding','cluster_summary']:
        assert Path(left[key]['path']).read_bytes()==Path(right[key]['path']).read_bytes()
    for key in [key for key,item in left.items() if item['format'] in {'png','pdf'}]:
        assert left[key]['sha256']==right[key]['sha256'],key
