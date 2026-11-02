import pytest
from pydantic import ValidationError


def test_single_cell_import_requires_explicit_h5ad_axes_and_layer():
    from app.domain.bioinformatics.single_cell_contracts import SingleCellImportRequest
    base=dict(workflow_version='bio_import_v4',assay='single_cell',file_ids=['a'],name='cells',expected_dataset_revision=0,matrix_representation='h5ad')
    with pytest.raises(ValidationError):SingleCellImportRequest(**base)
    value=SingleCellImportRequest(**base,h5ad=dict(matrix='raw.X',obs_index='_index',var_index='gene_id',symbol_column='symbol'))
    assert value.h5ad.matrix=='raw.X'


def test_single_cell_setup_rejects_tissue_filter_and_preserves_label_evidence():
    from app.domain.bioinformatics.single_cell_contracts import SingleCellParameters,CellLabel
    with pytest.raises(ValidationError):SingleCellParameters(in_tissue_only=True)
    with pytest.raises(ValidationError):CellLabel(cluster='0',label='T cell')
    assert CellLabel(cluster='0',label='unknown').label=='unknown'
    label=CellLabel(cluster='0',label='T cell',marker_ids=['CD3D'],decided_by='reviewer',basis='Marker review')
    assert label.marker_ids==['CD3D']


def test_cell_processed_source_enters_existing_donor_plan_with_technical_cells_not_n(monkeypatch):
    from app.domain.bio_insights.service import BioInsightsService
    from app.domain.bio_insights.contracts import ComparisonConfig
    from tests.domain.test_bio_insight_design import fixture
    config,observations,_=fixture()
    # Every selected key belongs to the explicitly chosen cell group in one
    # fixed processed source. A second technical sample reuses the same donor.
    for row in observations:row['sample']=row['barcode'];row['canonical_dataset_id']='cell-dataset'
    technical={**observations[0],'barcode':'extra-cell','sample':'technical-sample'}
    observations.append(technical)
    config['contrasts'][0]['numerator']['observation_keys'].append({'processed_version_id':'p','barcode':'extra-cell'})
    source=dict(source_kind='bio_processed_dataset_version',source_id='p',members={'features':{}},metadata=dict(assay='single_cell',observation_level='cell',canonical_dataset_id='cell-dataset',species_taxon_id=9606,namespace='ensembl_gene',reference_version='v1',observations=observations))
    class Reader:
        def read_rows(self,member):return [dict(feature_id='g1',feature_type='Gene Expression',total_counts='100',kept='True')]
    service=BioInsightsService.__new__(BioInsightsService)
    monkeypatch.setattr(service,'reader',lambda:Reader())
    preview=service._design(ComparisonConfig.model_validate(config),[source])
    assert preview.executable
    assert preview.actual_units[0].observation_level=='donor'
    assert preview.actual_units[0].n_numerator==3 and preview.actual_units[0].spots_numerator==4
    assert preview.actual_units[0].n_denominator==3
    exploratory=service._design(ComparisonConfig.model_validate({**config,'mode':'spot_exploratory'}),[source])
    assert not exploratory.executable and 'single_cell_requires_donor_contrast' in {r.code for r in exploratory.blocking_reasons}
    observations[0]['donor']=None
    blocked=service._design(ComparisonConfig.model_validate(config),[source])
    assert not blocked.executable and 'donor_missing' in {r.code for r in blocked.blocking_reasons}
