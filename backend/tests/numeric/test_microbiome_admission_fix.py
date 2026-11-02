import csv,hashlib
import pytest
from microbiome_fixture import source_fixture
from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
from app.domain.bio_insights.microbiome_design import prepare_microbiome,validate_microbiome_design
from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig


def test_frozen_microbiome_scale_contract(tmp_path):
    source,cfg=source_fixture(tmp_path/'initial-fraction',scale='fraction')
    request=source['raw']['manifest']['import_config']
    for kind,unit in [('relative_abundance','unknown'),('raw_counts','fraction')]:
        with pytest.raises(ValueError,match='microbiome_scale'):
            BioImportRequestV3.model_validate({**request,'scale':{**request['scale'],'kind':kind,'unit':unit}})
    for scale in ('counts','fraction','percent'):
        src,config=source_fixture(tmp_path/scale,scale=scale)
        prepare_microbiome(config,[src])
        for wrong in set(('counts','fraction','percent'))-{scale}:
            with pytest.raises(ValueError,match='microbiome_scale_mismatch'):
                prepare_microbiome(config.model_copy(update={'abundance_scale':wrong,'closure_confirmed':True,'closure_basis':'explicit'}),[src])
    # Other assays retain their established free-text unit contract.
    other={**request,'assay':'metabolomics','tables':request['tables'][:2],'file_ids':request['file_ids'][:2], 'scale':{**request['scale'],'kind':'concentration','unit':'custom assay unit'}}
    BioImportRequestV3.model_validate(other)


@pytest.mark.parametrize('column,marker,paired',[('group','NA',False),('group','N/A',False),('unit','CUSTOM_MISSING',False),('pair','NA',True),('pair','CUSTOM_MISSING',True)])
def test_frozen_source_na_blocks_inference(tmp_path,column,marker,paired):
    source,cfg=source_fixture(tmp_path/'source')
    source['raw']['manifest']['import_config']['na_values']=['','NA','N/A','CUSTOM_MISSING']
    member=source['raw']['members']['samples'];path=__import__('pathlib').Path(member['path'])
    with path.open(newline='',encoding='utf-8') as stream: rows=list(csv.DictReader(stream,delimiter='\t'))
    indexes=(0,3) if paired else range(3) if column=='group' else (0,)
    for i in indexes:rows[i][column]=marker
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),delimiter='\t');writer.writeheader();writer.writerows(rows)
    member['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();member['size_bytes']=path.stat().st_size
    changes=dict(design='paired' if paired else 'independent',alpha_method='paired_t' if paired else 'welch_t',pair_column='pair' if paired else None,independence_confirmed=True,independence_basis='synthetic',beta_inference=not paired)
    if paired:changes.update(contrasts=[dict(contrast_id='A_B',name='A-B',numerator='A',denominator='B')],family_contrast_ids=['A_B'])
    cfg=MicrobiomeConfig.model_validate({**cfg.model_dump(),**changes})
    assert prepare_microbiome(cfg,[source])['audit'][0]['metadata'][column]==marker
    result=validate_microbiome_design(cfg,[source])
    assert not result.executable
    assert any('metadata_missing' in r.message or 'complete_unique_pairs' in r.message for r in result.blocking_reasons)
