import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def payload(tmp_path, counts=False):
    content='feature_id,s1,s2,s3\na,1,2,4\nb,2,4,8\nc,3,NA,12\n'
    if counts:content=content.replace('NA','6')
    files=[]
    for key,body in [('m',content),('s','sample_id,condition,biological_unit_id\ns1,A,u1\ns2,A,u2\ns3,B,u3\n')]:
        path=tmp_path/(key+'.csv');path.write_text(body,encoding='utf-8')
        files.append(dict(id=key,path=str(path),filename=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size,role='quantitative_matrix' if key=='m' else 'sample_metadata'))
    return dict(files=files,config=dict(workflow_version='bio_import_v3',file_ids=['m','s'],assay='bulk_rna_counts' if counts else 'proteomics',name='test',expected_dataset_revision=0,
        tables=[dict(file_id='m',role='quantitative_matrix',format='csv'),dict(file_id='s',role='sample_metadata',format='csv')],feature_id_column='feature_id',sample_columns=['s1','s2','s3'],
        scale=dict(kind='raw_counts' if counts else 'intensity',unit='counts' if counts else 'AU',upstream_method='test')),
        identity=dict(engine_version='tabular_quantitative_v1.0.0',code_digest='a'*64,environment_digest='b'*64))


def test_import_preserves_missing_and_real_sample_axis(tmp_path):
    assert importlib.util.find_spec('app.adapters.bio_engine.tabular_assays') is not None
    from app.adapters.bio_engine.tabular_assays import import_tabular
    p=payload(tmp_path);out=tmp_path/'out';out.mkdir();p['output_directory']=str(out)
    r=import_tabular(p);members={m['key']:m for m in r['outputs']}
    assert np.load(members['matrix_values']['path']).shape==(3,3)
    assert np.load(members['matrix_missing']['path']).sum()==1
    assert json.loads(Path(members['samples_index']['path']).read_text())=={'sample_ids':['s1','s2','s3']}
    assert 'barcodes_index' not in members


def test_bulk_matrix_budget_counts_only_numeric_matrix_cells(tmp_path, monkeypatch):
    from app.adapters.bio_engine import tabular_assays

    monkeypatch.setattr(tabular_assays, 'LIMITS', tabular_assays.LIMITS.model_copy(update={'max_bulk_matrix_cells': 9}))
    request = payload(tmp_path, counts=True)
    output = tmp_path / 'out'
    output.mkdir()
    request['output_directory'] = str(output)

    assert tabular_assays.import_tabular(request)['entry_count'] == 9
    monkeypatch.setattr(tabular_assays, 'LIMITS', tabular_assays.LIMITS.model_copy(update={'max_bulk_matrix_cells': 8}))
    with pytest.raises(ValueError, match='tabular_cell_limit'):
        tabular_assays.import_tabular(request)


@pytest.mark.parametrize(('row', 'error'), [
    ({'feature_id': 'a', 's1': '1', 's2': '2', 's3': '3', 'extra': '9'},
     r'matrix_columns_mismatch:file=m\.csv:row=2:columns=extra'),
    ({'feature_id': 'a', 's1': '1', 's2': 'bad', 's3': '3'},
     r'matrix_non_numeric:file=m\.csv:row=2:column=s2:sample_id=s2:feature_id=a'),
])
def test_bulk_rejects_invalid_matrix_row_before_reading_more_rows(tmp_path, monkeypatch, row, error):
    from app.adapters.bio_engine import tabular_assays

    request = payload(tmp_path, counts=True)
    output = tmp_path / 'out'
    output.mkdir()

    original = tabular_assays.iter_table

    def rows(file, **kwargs):
        if file['role'] != 'quantitative_matrix':
            yield from original(file, **kwargs)
            return
        yield 2, row
        pytest.fail('read beyond the first invalid matrix row')

    monkeypatch.setattr(tabular_assays, 'iter_table', rows)
    with pytest.raises(ValueError, match=error):
        tabular_assays.import_tabular(dict(request, output_directory=str(output)))


def test_counts_missing_and_fraction_rejected(tmp_path):
    from app.adapters.bio_engine.tabular_assays import import_tabular
    p=payload(tmp_path);p['config']['assay']='bulk_rna_counts';p['config']['scale']['kind']='raw_counts'
    out=tmp_path/'out';out.mkdir();p['output_directory']=str(out)
    with pytest.raises(ValueError):import_tabular(p)


def test_bulk_import_writes_canonical_sample_mapping_and_quality_report(tmp_path):
    from app.adapters.bio_engine.tabular_assays import import_tabular
    p=payload(tmp_path,counts=True)
    qc=tmp_path/'multiqc.html';qc.write_text('<html>upstream</html>',encoding='utf-8')
    p['files'].append(dict(id='qc',path=str(qc),filename=qc.name,sha256=hashlib.sha256(qc.read_bytes()).hexdigest(),size_bytes=qc.stat().st_size,role='upstream_quality_report'))
    p['config']['file_ids'].append('qc')
    p['config']['quality_reports']=[dict(file_id='qc',source='user_provided',report_type='multiqc')]
    p['config']['scale']['input_origin']='bulk_rna'
    out=tmp_path/'out';out.mkdir();p['output_directory']=str(out)
    result=import_tabular(p);members={m['key']:m for m in result['outputs']}
    mapping=json.loads(Path(members['sample_mapping']['path']).read_text())
    assert mapping['version']=='bulk_sample_mapping_v1'
    assert mapping['sample_ids']==['s1','s2','s3']
    assert mapping['source']['file_id']=='s'
    assert result['manifest']['checks']['quality_reports']==[{'file_id':'qc','source':'user_provided','report_type':'multiqc'}]


def test_bulk_import_reports_sample_metadata_coordinates(tmp_path):
    from app.adapters.bio_engine.tabular_assays import import_tabular
    p=payload(tmp_path,counts=True)
    sample=next(file for file in p['files'] if file['id']=='s')
    Path(sample['path']).write_text('sample_id,condition,biological_unit_id\ns1,A,u1\ns1,A,u2\ns3,B,u3\n',encoding='utf-8')
    sample.update(size_bytes=Path(sample['path']).stat().st_size,sha256=hashlib.sha256(Path(sample['path']).read_bytes()).hexdigest())
    out=tmp_path/'out';out.mkdir();p['output_directory']=str(out)
    with pytest.raises(ValueError,match=r'duplicate_sample_id:.*file=s\.csv:.*row=3:.*sample_id=s1'):
        import_tabular(p)


@pytest.mark.parametrize('mapping,heading,value,error', [
    ({'batch': 'typo'}, 'batch', 'existing', r'sample_metadata_columns_missing:file=s\.csv:columns=typo'),
    (None, 'sample_role', 'Technical', r'sample_metadata_invalid_value:file=s\.csv:row=2:column=sample_role:sample_id=s1'),
])
def test_bulk_sample_mapping_checks_explicit_optional_columns_and_native_roles(tmp_path, mapping, heading, value, error):
    from app.adapters.bio_engine.tabular_assays import import_tabular

    request = payload(tmp_path, counts=True)
    sample = request['files'][1]
    contents = f'sample_id,condition,biological_unit_id,{heading}\ns1,A,u1,{value}\ns2,A,u2,\ns3,B,u3,\n'.encode()
    Path(sample['path']).write_bytes(contents)
    sample.update(size_bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest())
    if mapping:
        request['config']['sample_metadata_mapping'] = mapping
    output = tmp_path / 'out'
    output.mkdir()
    with pytest.raises(ValueError, match=error):
        import_tabular(dict(request, output_directory=str(output)))


def test_non_bulk_import_preserves_unmapped_sample_role_metadata(tmp_path):
    from app.adapters.bio_engine.tabular_assays import _rows, import_tabular

    request = payload(tmp_path)
    sample = request['files'][1]
    contents = b'sample_id,condition,biological_unit_id,sample_role\ns1,A,u1,case\ns2,A,u2,case\ns3,B,u3,control\n'
    Path(sample['path']).write_bytes(contents)
    sample.update(size_bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest())
    output = tmp_path / 'out'
    output.mkdir()
    result = import_tabular(dict(request, output_directory=str(output)))
    member = next(item for item in result['outputs'] if item['key'] == 'samples')
    assert [row['sample_role'] for row in _rows(member)] == ['case', 'case', 'control']


def test_bulk_import_reports_matrix_coordinates_for_invalid_value(tmp_path):
    from app.adapters.bio_engine.tabular_assays import import_tabular
    p=payload(tmp_path,counts=True)
    matrix=next(file for file in p['files'] if file['id']=='m')
    Path(matrix['path']).write_text('feature_id,s1,s2,s3\na,1,bad,4\n',encoding='utf-8')
    matrix.update(size_bytes=Path(matrix['path']).stat().st_size,sha256=hashlib.sha256(Path(matrix['path']).read_bytes()).hexdigest())
    out=tmp_path/'out';out.mkdir();p['output_directory']=str(out)
    with pytest.raises(ValueError,match=r'matrix_non_numeric:.*file=m\.csv:.*row=2:.*column=s2:.*sample_id=s2:.*feature_id=a'):
        import_tabular(p)


@pytest.mark.parametrize('kind',['pca','sample_clustering'])
@pytest.mark.parametrize('language',['en','zh-CN'])
def test_quantitative_figure_sample_identity_feature_ticks_and_units_are_readable(tmp_path,monkeypatch,kind,language):
    import matplotlib
    matplotlib.use('Agg',force=True)
    from matplotlib import pyplot as plt
    from app.adapters.bio_engine import tabular_assays as engine
    p=payload(tmp_path);samples=[f'run_{i:02d}' for i in range(1,19)]
    bodies=['feature_id,'+','.join(samples)+'\nrabbit,'+','.join(str(10+i) for i in range(18))+'\nchicken,'+','.join(str(2+i*i) for i in range(18))+'\n',
        'sample_id,condition,sample_role\n'+''.join(f'{s},A,technical\n' for s in samples)]
    for file,body in zip(p['files'],bodies):
        Path(file['path']).write_bytes(body.encode());file.update(size_bytes=len(body.encode()),sha256=hashlib.sha256(body.encode()).hexdigest())
    p['config']['sample_columns']=samples;p['config']['scale']['unit']='summed intensity (source unit unspecified)'
    rawdir=tmp_path/'raw';rawdir.mkdir();p['output_directory']=str(rawdir);raw=engine.import_tabular(p)
    observed={}
    def capture(writer,key,title,plot,data,params,*_storage_options):
        fig,ax=plt.subplots();plot(ax)
        observed[key]=dict(texts=[t.get_text() for t in ax.texts],legend=[t.get_text() for t in ax.get_legend().get_texts()] if ax.get_legend() else [],
            ticks=[t.get_text() for t in ax.get_xticklabels()],colorbar=fig.axes[-1].get_ylabel(),data=data,xlabel=ax.get_xlabel(),legend_title=ax.get_legend().get_title().get_text() if ax.get_legend() else '')
        plt.close(fig)
    monkeypatch.setattr(engine,'_figure',capture)
    output=tmp_path/'compute';output.mkdir();engine.run_tabular(dict(raw={'manifest':raw['manifest'],'members':{m['key']:m for m in raw['outputs']}},config={'output_language':language},identity=p['identity'],mode='compute',output_directory=str(output)))
    actual=observed[kind]
    if kind=='pca':
        assert not actual['texts']
        assert actual['legend']==samples
        assert actual['legend_title']==('样本身份' if language=='zh-CN' else 'Sample identity')
    else:
        assert actual['ticks']==['rabbit','chicken']
        assert 'summed intensity (source unit unspecified)' in ' '.join(actual['colorbar'].split())
        assert actual['data']['feature_ids']==['rabbit','chicken']
        assert actual['xlabel']==('完整且非恒定特征' if language=='zh-CN' else 'Complete nonconstant features')


def test_compute_keeps_test_matrix_missing_and_pca_complete_feature_mask(tmp_path):
    from app.adapters.bio_engine.tabular_assays import import_tabular, run_tabular
    p=payload(tmp_path);out=tmp_path/'raw';out.mkdir();p['output_directory']=str(out);raw=import_tabular(p)
    dest=tmp_path/'processed';dest.mkdir()
    r=run_tabular(dict(raw=dict(manifest=raw['manifest'],members={m['key']:m for m in raw['outputs']}),config=dict(transform='log2'),identity=p['identity'],mode='compute',output_directory=str(dest)))
    members={m['key']:m for m in r['outputs']}
    missing=np.load(members['analysis_missing']['path']);values=np.load(members['analysis_values']['path'])
    assert missing.sum()==1 and values[0,0]==0 and values[2,0]==2
    assert np.load(members['pca_feature_mask']['path']).tolist()==[True,True,False]
    assert r['manifest']['observation_level']=='sample'
    assert r['manifest']['schema_version']==2
    assert all('spatial' not in m for m in members)


@pytest.mark.parametrize('format',['tsv','xlsx'])
def test_table_representations_keep_exact_values(tmp_path,format):
    from app.adapters.bio_engine.tabular_assays import import_tabular
    p=payload(tmp_path,counts=True)
    for file,spec in zip(p['files'],p['config']['tables']):
        rows=[line.split(',') for line in Path(file['path']).read_text().splitlines()]
        dest=tmp_path/(file['id']+'.'+format)
        if format=='xlsx':
            from openpyxl import Workbook
            workbook=Workbook();sheet=workbook.active;sheet.title='Data'
            for row in rows:sheet.append(row)
            workbook.save(dest);spec['sheet']='Data'
        else:dest.write_text('\n'.join('\t'.join(row) for row in rows)+'\n',encoding='utf-8')
        file.update(path=str(dest),filename=dest.name,size_bytes=dest.stat().st_size,sha256=hashlib.sha256(dest.read_bytes()).hexdigest());spec['format']=format
    out=tmp_path/'out';out.mkdir();p['output_directory']=str(out)
    r=import_tabular(p);values=np.load(next(m['path'] for m in r['outputs'] if m['key']=='matrix_values'))
    assert values.tolist()==[[1,2,3],[2,4,6],[4,8,12]] and values.dtype==np.dtype('int64')


def test_median_normalization_and_missing_do_not_impute():
    from app.adapters.bio_engine.tabular_assays import transformed
    values=np.array([[2.,4.,0.],[4.,8.,12.]]);missing=np.array([[False,False,True],[False,False,False]])
    actual,factors=transformed(values,missing,{'normalization':'median'},{'assay':'proteomics','scale':{'kind':'intensity'}})
    assert np.allclose(factors,[3/5.5,8/5.5])
    assert actual[0,2]==0 and np.isclose(actual[1,0],2.75)


def test_explicit_counts_log1p_preserves_zero_and_never_changes_raw():
    from app.adapters.bio_engine.tabular_assays import transformed,layer_scale
    raw=np.array([[0,2,4],[1,3,5]],dtype='int64');original=raw.copy();mask=np.zeros(raw.shape,dtype=bool)
    manifest={'assay':'bulk_rna_counts','scale':{'kind':'raw_counts','unit':'counts'}}
    actual,_=transformed(raw,mask,{'transform':'log1p'},manifest)
    assert np.array_equal(raw,original) and np.allclose(actual,np.log1p(raw)) and actual[0,0]==0
    scale=layer_scale({'transform':'log1p'},manifest)
    assert scale['scale']=='log1p' and scale['transform_offset']==1 and scale['is_raw_integer_counts'] is False
    with pytest.raises(ValueError):transformed(raw,mask,{'transform':'log1p'},{'assay':'proteomics','scale':{'kind':'intensity'}})


def test_parent_rejects_altered_raw_values_even_with_recomputed_leaf_digest(tmp_path):
    from app.adapters.bio_engine.tabular_assays import import_tabular
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    from app.adapters.bio_tabular_process import validate_tabular_result
    from app.core.exceptions import StorageError
    p=payload(tmp_path,counts=True);p['config']=BioImportRequestV3(**p['config']).model_dump()
    out=tmp_path/'out';out.mkdir();p['output_directory']=str(out);r=import_tabular(p)
    leaf=next(m for m in r['outputs'] if m['key']=='matrix_values');values=np.load(leaf['path']);values[0,0]=999;np.save(leaf['path'],values,allow_pickle=False)
    leaf.update(sha256=hashlib.sha256(Path(leaf['path']).read_bytes()).hexdigest(),size_bytes=Path(leaf['path']).stat().st_size)
    r['manifest']['members']=[{k:v for k,v in m.items() if k!='path'} for m in r['outputs']]
    with pytest.raises(StorageError):validate_tabular_result(r,out,p,'import_v3')


def test_insufficient_pca_does_not_discard_qc_or_missing_data(tmp_path):
    from app.adapters.bio_engine.tabular_assays import import_tabular,run_tabular
    p=payload(tmp_path);out=tmp_path/'raw';out.mkdir();p['output_directory']=str(out);raw=import_tabular(p)
    dest=tmp_path/'processed';dest.mkdir()
    r=run_tabular(dict(raw=dict(manifest=raw['manifest'],members={m['key']:m for m in raw['outputs']}),config={'exclude_features':['a','b']},identity=p['identity'],mode='compute',output_directory=str(dest)))
    assert next(s for s in r['steps'] if s['key']=='pca')['status']=='not_computable'
    assert next(t for t in r['manifest']['tables'] if t['key']=='pca_scores')['status']=='not_computable'
    assert r['summary']['retained_features']==1
    assert 'sample_qc' in {m['key'] for m in r['outputs']}
