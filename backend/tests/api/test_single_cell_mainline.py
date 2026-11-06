"""Opt-in real Linux science + isolated test DB; synthetic samples, no cloud.

Set PAPERASSIST_SC_NUMERIC_TEST_IMAGE to an existing local bio worker image.
The runtime capability receipt is injected; this is not a deployment probe.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
import tarfile

import numpy as np
import pytest
from docx import Document

from tests.api.test_projects import client,create_project


def _bundle(counts):
    body = io.BytesIO()
    with tarfile.open(fileobj=body,mode='w:gz') as archive:
        entries = [(gene+1,cell+1,int(value)) for cell,row in enumerate(counts) for gene,value in enumerate(row) if value]
        matrix = f'%%MatrixMarket matrix coordinate integer general\n{counts.shape[1]} {counts.shape[0]} {len(entries)}\n'
        matrix += ''.join(f'{gene} {cell} {value}\n' for gene,cell,value in entries)
        for filename,text in [('matrix.mtx',matrix),('features.tsv',''.join(f'g{i}\tg{i}\tGene Expression\n' for i in range(counts.shape[1]))),
                              ('barcodes.tsv',''.join(f'cell{i}\n' for i in range(counts.shape[0])))]:
            content=text.encode();item=tarfile.TarInfo(filename);item.size=len(content)
            archive.addfile(item,io.BytesIO(content))
    return body.getvalue()


def _linux_science(tmp_path,payload,output,mode,image):
    root = Path(__file__).resolve().parents[2]
    def translate(value,reverse=False):
        if isinstance(value,dict):return {k:translate(v,reverse) for k,v in value.items()}
        if isinstance(value,list):return [translate(v,reverse) for v in value]
        if isinstance(value,str):
            if reverse and value.startswith('/data/'):return str(tmp_path / value[6:])
            if not reverse:
                try:return '/data/'+Path(value).relative_to(tmp_path).as_posix()
                except (ValueError,OSError):pass
        return value
    request = tmp_path / (mode+'-request.json')
    receipt = tmp_path / (mode+'-receipt.json')
    request.write_text(json.dumps(translate({**payload,'mode':mode,'output_directory':str(output)})),encoding='utf-8')
    module = 'single_cell' if mode=='import_single_cell' else 'pipeline'
    entry = 'import_counts' if mode=='import_single_cell' else 'run'
    code = f"import json; from pathlib import Path; from app.adapters.bio_engine.{module} import {entry}; p=json.loads(Path('/data/{request.name}').read_text()); r={entry}(p); Path('/data/{receipt.name}').write_text(json.dumps(r,allow_nan=False))"
    subprocess.run(['docker','run','--rm','--network','none','--mount',f'type=bind,source={root},target=/workspace,readonly',
                    '--mount',f'type=bind,source={tmp_path},target=/data','--workdir','/workspace','--env','PYTHONPATH=/workspace',
                    '--entrypoint','/opt/paperassist-bio/bin/python',image,'-c',code],check=True,capture_output=True,text=True,timeout=180)
    result = translate(json.loads(receipt.read_text()),True)
    from app.adapters.bio_analysis_process import validate_artifacts
    validate_artifacts(result['outputs'],output,formats={'npy','json','tsv','mtx','txt'} if mode=='import_single_cell' else None)
    return result


@pytest.mark.skipif(not os.environ.get('PAPERASSIST_SC_NUMERIC_TEST_IMAGE'),reason='Requires explicitly selected local Linux science image')
def test_matrix_to_direct_analysis_figures_and_word(client,monkeypatch,tmp_path):
    from app.domain.bioinformatics import single_cell_settings
    from app.domain.bioinformatics.analysis_settings import engine_code_digest
    from app.domain.bioinformatics.execution import run_bio_import_task
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    image = os.environ['PAPERASSIST_SC_NUMERIC_TEST_IMAGE']
    runtime = dict(available=True,blockers=[],engine_version='visium_explore_v1.0.0',environment_digest='b'*64,code_digest=engine_code_digest())
    monkeypatch.setattr(single_cell_settings,'runtime_identity',lambda:runtime)
    staging = tmp_path / 'staging'
    monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR',str(staging))
    base = '/api/v1/projects/'+create_project(client)['id']
    counts = np.random.default_rng(9).poisson(3,(48,24)).astype('int64')
    counts[:24,:8] += 6;counts[24:,8:16] += 6
    file_ids=[];samples=[]
    for index in range(2):
        body = _bundle(counts[index*24:(index+1)*24]);item=str(uuid4());filename=f'library{index}.tar.gz'
        batch=client.post(base+'/bio-upload-batches',headers={'Idempotency-Key':f'upload-{index}'},json={'items':[dict(client_id=item,filename=filename,size_bytes=len(body))]})
        assert batch.status_code==201,batch.text
        upload=client.post(base+f"/bio-upload-batches/{batch.json()['id']}/items/{item}",files={'file':(filename,body)})
        assert upload.status_code==202,upload.text
        file_ids.append(upload.json()['file_id'])
        samples.append(dict(sample_id=f'S{index}',library_id=f'L{index}',donor=f'D{index}',group='control' if index==0 else 'treated',file_ids=[file_ids[-1]]))
    response=client.post(base+'/bio-imports',headers={'Idempotency-Key':'real-import'},json=dict(workflow_version='bio_import_v4',assay='single_cell',file_ids=file_ids,
                         samples=samples,name='Synthetic two-library matrix',expected_dataset_revision=0,matrix_representation='mtx'))
    assert response.status_code==202,response.text
    imported=response.json();task=imported['task']
    def parser(frozen,output,settings):return _linux_science(tmp_path,{**frozen,'settings':settings},output,'import_single_cell',image)
    waiting=run_bio_import_task(task['id'],task['revision'],parser=parser,staging_directory=staging)
    assert waiting['status']=='waiting_confirmation',waiting
    review=client.get(base+'/bio-imports/'+imported['id']).json()
    confirmed=client.post(base+'/bio-imports/'+imported['id']+'/confirm',headers={'Idempotency-Key':'import-confirm'},json=dict(
        task_revision=review['task']['revision'],checkpoint_id=review['checkpoint_id'],wait_id=review['wait_id'],candidate_sha256=review['candidate']['sha256'],expected_dataset_revision=review['expected_dataset_revision']))
    assert confirmed.status_code==202,confirmed.text
    done=run_bio_import_task(task['id'],confirmed.json()['revision'],parser=parser,staging_directory=staging)
    assert done['status']=='succeeded',done
    source=client.get(base+'/bio-imports/'+imported['id']).json()['result_source']
    request=dict(name='Single cell mainline',raw_source=source,params=dict(min_counts=1,min_genes=1,min_spots=1,hvg_count=16,pca_components=5,neighbors=5,resolution=0.8,seed=9))
    started=client.post(base+'/single-cell-analysis-runs',headers={'Idempotency-Key':'direct'},json=request)
    assert started.status_code==202,started.text
    replay=client.post(base+'/single-cell-analysis-runs',headers={'Idempotency-Key':'direct'},json=request)
    assert replay.status_code==202 and replay.json()['id']==started.json()['id'],replay.text
    task=started.json()['task']
    def engine(payload,output,mode):
        assert mode=='compute'
        return _linux_science(tmp_path,payload,output,mode,image)
    done=run_bio_analysis_task(task['id'],task['revision'],engine=engine,staging_directory=staging)
    assert done['status']=='succeeded',done
    identifier=done['result_bio_processed_dataset_version_id']
    result=client.get(base+'/bio-processed-datasets/'+identifier)
    assert result.status_code==200,result.text
    result=result.json()
    assert result['shape']['raw_observations']==result['shape']['retained_observations']==48
    assert result['figures'] and all(m['format']!='pdf' for f in result['figures'] for m in f['members'])
    assert any(m['format']=='h5ad' for m in result['members'])
    for figure in result['figures']:
        member=next(m for m in figure['members'] if m['format']=='png')
        download=client.get(member['download_url'])
        assert download.status_code==200 and hashlib.sha256(download.content).hexdigest()==member['sha256']
    report=client.get(base+'/bio-processed-datasets/'+identifier+'/report.docx')
    assert report.status_code==200,report.text
    assert report.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    document=Document(io.BytesIO(report.content))
    assert len(document.inline_shapes)==len(result['figures'])
    texts='\n'.join(p.text for p in document.paragraphs)+'\n'+'\n'.join(c.text for t in document.tables for row in t.rows for c in row.cells)
    assert all(value in texts for value in ('48','S0','S1','D0','D1','library0.tar.gz'))
    other='/api/v1/projects/'+create_project(client)['id']
    assert client.get(other+'/bio-processed-datasets/'+identifier+'/report.docx').status_code==404
    evidence=os.environ.get('PAPERASSIST_SC_EVIDENCE_DIR')
    if evidence:
        destination=Path(evidence);destination.mkdir(parents=True,exist_ok=True)
        (destination/'synthetic-single-cell-analysis.docx').write_bytes(report.content)
        (destination/'summary.json').write_text(json.dumps(dict(input='synthetic 48 cells x 24 genes, 2 libraries',
            runtime_gate='injected test capability, not production attestation',science_image=image,shape=result['shape'],
            steps=result['steps'],figure_count=len(result['figures']),formats=sorted({m['format'] for m in result['members']})),indent=2),encoding='utf-8')
