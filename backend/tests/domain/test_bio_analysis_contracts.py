"""B02 boundaries are independent of scientific packages and live databases."""
import importlib.util
import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def contracts():
    name = 'app.domain.bioinformatics.analysis_contracts'
    assert importlib.util.find_spec(name) is not None, 'B02 strict analysis contracts are missing'
    return __import__(name, fromlist=['BioRecipeParameters'])


def source():
    return dict(kind='bio_dataset_version',schema_version=1,project_id='project',dataset_id='dataset',
                dataset_version_id='raw-version',version=1,manifest_sha256='a'*64,
                parser_version='visium-v1',source_file_ids=['file'])


def test_recipe_refuses_nonfinite_numbers_unknown_algorithms_and_hidden_filtering():
    module = contracts()
    params = module.BioRecipeParameters()
    assert params.in_tissue_only is False
    assert params.min_counts == 1 and params.min_genes == 1 and params.min_spots == 3
    assert params.mt_rule.kind == 'unknown'
    for bad in ({'resolution': float('nan')}, {'target_sum': float('inf')},
                {'algorithm': 'user-code'}, {'hvg_count': 100001}, {'min_counts': True}):
        with pytest.raises(ValidationError):
            module.BioRecipeParameters.model_validate(bad)


def test_observation_unknown_cannot_carry_invented_value_and_barcodes_are_unique():
    module = contracts()
    with pytest.raises(ValidationError):
        module.BioMappingValue(status='pending', value='invented-donor')
    with pytest.raises(ValidationError):
        module.BioObservationMapRequest.model_validate(dict(name='mapping', raw_source=source(),
            expected_revision=0, rows=[{'barcode':'A'}, {'barcode':'A'}]))


def test_mapping_table_apply_pins_file_hash_and_does_not_save_twenty_preview_rows():
    module=contracts()
    request=module.BioObservationMapRequest.model_validate(dict(name='mapping',raw_source=source(),
        expected_revision=0,table_source=dict(file_id='file',sha256='d'*64,sheet=0,mapping={'barcode':'Barcode'})))
    assert request.table_source.sha256=='d'*64 and request.rows==[]
    with pytest.raises(ValidationError):
        module.BioObservationMapRequest.model_validate({**request.model_dump(),'rows':[{'barcode':'A'}]})


def test_figure_refuses_paths_expressions_invalid_ranges_and_nonfinite_geometry():
    module = contracts()
    for bad in ({'kind':'spatial_gene','gene_ids':['../x']},
                {'kind':'spatial_gene','vmin':2.0,'vmax':1.0},
                {'kind':'spatial_gene','width':5000}, {'kind':'spatial_gene','code':'print(1)'}):
        with pytest.raises(ValidationError):
            module.BioFigureConfig.model_validate(bad)
    with pytest.raises(ValidationError):
        module.BioAnnotationRegion.model_validate(dict(id='r',label_id='a',points=[[float('nan'),0],[0,1],[1,0]]))


def test_embedding_figure_can_select_frozen_mapping_color_without_changing_recipe():
    module=contracts()
    assert module.BioFigureConfig(kind='umap',color_by='section').color_by=='section'
    with pytest.raises(ValidationError):
        module.BioFigureConfig(kind='umap',color_by='inferred_donor')


@pytest.mark.parametrize('kind',['marker_dotplot','marker_heatmap'])
def test_marker_figures_use_the_declared_mean_log1p_layer(kind):
    for layer in ('counts','normalized'):
        with pytest.raises(ValidationError):contracts().BioFigureConfig(kind=kind,layer=layer)
    assert contracts().BioFigureConfig(kind=kind,layer='log1p').layer=='log1p'


def test_figure_panel_preserves_identity_and_rejects_mismatched_kind():
    module=contracts()
    for kind,panel in [('pca','variance'),('qc','mitochondrial'),('qc','section'),('umap','scores')]:
        assert module.BioFigureConfig(kind=kind,panel=panel).panel==panel
    for kind,panel in [('umap','variance'),('marker_dotplot','scatter'),('pca','section'),('qc','scores')]:
        with pytest.raises(ValidationError):module.BioFigureConfig(kind=kind,panel=panel)


def test_processed_source_is_frozen_and_never_an_excel_source():
    module = contracts()
    with pytest.raises(ValidationError):
        module.BioProcessedDatasetSourceV1.model_validate({'kind':'dataset_version','file_id':'x'})
    processed=module.BioProcessedDatasetSourceV1(project_id='project',processed_dataset_version_id='processed',
        analysis_run_id='run',raw_source=source(),recipe_version_id='recipe',manifest_sha256='b'*64,environment_digest='c'*64)
    with pytest.raises(ValidationError):
        processed.project_id='other-project'
    with pytest.raises(ValidationError):
        module.BioProcessedDatasetSourceV1.model_validate({**processed.model_dump(),'project_id':'other-project'})


def test_runtime_capability_reads_verified_manifest_and_fails_closed_on_drift(tmp_path, monkeypatch):
    import json
    import hashlib
    name = 'app.domain.bioinformatics.analysis_settings'
    assert importlib.util.find_spec(name) is not None, 'B02 verified runtime identity missing'
    module = __import__(name, fromlist=['runtime_identity'])
    monkeypatch.setenv('PAPERASSIST_BIO_RUNTIME_MANIFEST',str(tmp_path/'missing.json'))
    assert module.runtime_identity()['available'] is False

    monkeypatch.setattr(module,'engine_code_digest',lambda:'a'*64)
    monkeypatch.setattr(module,'engine_lock_digest',lambda:'b'*64)
    path = tmp_path/'runtime.json'
    value = dict(schema_version=1,gate_status='passed',engine_version='visium_explore_v1.0.0',
        environment_digest='c'*64,code_digest='a'*64,lock_sha256='b'*64,
        image_digest='sha256:'+'d'*64,platform='linux/amd64',
        checks=dict(numeric=True,isolation=True,hdf5=True,plots=True),verified_at='2026-10-29T00:00:00Z')
    path.write_text(json.dumps(value),encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_BIO_RUNTIME_MANIFEST',str(path))
    assert module.runtime_identity()['available'] is True
    value['checks']['isolation'] = False
    path.write_text(json.dumps(value),encoding='utf-8')
    assert module.runtime_identity()['available'] is False
    value['code_digest'] = 'a'*64
    value['checks']['isolation'] = True
    value['checks']['numeric'] = 1
    path.write_text(json.dumps(value),encoding='utf-8')
    assert module.runtime_identity()['available'] is False
    value['checks']['numeric'] = True
    value['code_digest'] = 'e'*64
    path.write_text(json.dumps(value),encoding='utf-8')
    assert module.runtime_identity()['available'] is False



def test_mapping_xlsx_reader_supports_20000_rows_without_relaxing_design_defaults():
    import io
    from types import SimpleNamespace
    from openpyxl import Workbook
    from app.adapters.excel import parse_workbook
    from app.core.config import get_excel_settings
    from app.core.exceptions import StorageError
    from app.domain.research_intake.service import _xlsx_sample_text
    workbook=Workbook(write_only=True);sheet=workbook.create_sheet('mapping');sheet.append(['barcode','section'])
    for index in range(20000):sheet.append([f'barcode-{index}','section-'+'x'*110])
    output=io.BytesIO();workbook.save(output);content=output.getvalue()
    preview=parse_workbook(content,'mapping.xlsx',get_excel_settings())
    file={'filename':'mapping.xlsx','preview_json':preview.model_dump_json()}
    store=SimpleNamespace(original=lambda row:content)
    with pytest.raises(StorageError):_xlsx_sample_text(store,file,0)
    text,name=_xlsx_sample_text(store,file,0,max_rows=20000,max_text_bytes=16777216)
    assert name=='mapping' and len(text.splitlines())==20001 and len(text)>2097152
