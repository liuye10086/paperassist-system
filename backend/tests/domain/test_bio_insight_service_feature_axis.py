"""Service admission uses the same fixed feature axis as the numerical mode."""
import csv
from types import SimpleNamespace
import pytest
from app.domain.bio_insights.contracts import ComparisonConfig
from app.domain.bio_insights.service import BioInsightsService
from app.domain.bio_insights.sources import InsightSourceReader


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def service():
    value=object.__new__(BioInsightsService)
    value.reader=lambda:SimpleNamespace(read_rows=InsightSourceReader.read_rows)
    return value


def source(tmp_path,sid,features,n=6):
    path=tmp_path/(sid+'.tsv')
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,['feature_id','feature_type','kept','total_counts'],delimiter='\t',lineterminator='\n')
        writer.writeheader();writer.writerows(features)
    observations=[dict(processed_version_id=sid,barcode=f'b{i}',retained=True,library_counts=100) for i in range(n)]
    return dict(source_kind='bio_processed_dataset_version',source_id=sid,members={'features':{'path':str(path),'format':'tsv','size_bytes':path.stat().st_size}},
        metadata=dict(canonical_dataset_id='canonical-'+sid,species_taxon_id=9606,namespace='Ensembl',reference_version='v1',
            observations=observations,feature_ids=['metadata_is_not_the_matrix_axis'],common_feature_count=999999))


def configuration(mode='spot_exploratory',n=6,left='p1',right=None):
    right=right or left;split=n//2
    return ComparisonConfig.model_validate(dict(kind='comparison',mode=mode,species_taxon_id=9606,namespace='Ensembl',reference_version='v1',
        contrasts=[dict(contrast_id='c',name='B versus A',
            numerator=dict(label='B',observation_keys=[dict(processed_version_id=left,barcode=f'b{i}') for i in range(split,n)]),
            denominator=dict(label='A',observation_keys=[dict(processed_version_id=right,barcode=f'b{i}') for i in range(split)]))],family_contrast_ids=['c']))


def test_gse_sized_processed_axis_uses_18813_for_spot_and_58735_for_donor(tmp_path):
    features=[dict(feature_id=f'g{i}',feature_type='Gene Expression',kept=str(i<18813),total_counts='100') for i in range(58735)]
    value=source(tmp_path,'p1',features,n=1162)
    spot=service()._design(configuration(n=1162),[value])
    assert spot.resource_estimate.features==18813
    assert spot.resource_estimate.estimated_working_bytes==1162*18813*32+18813*512
    assert spot.executable
    donor=service()._design(configuration(mode='donor_unpaired',n=1162),[value])
    assert donor.resource_estimate.features==58735
    assert not donor.executable  # Missing real donor declarations still block.


def test_cross_source_common_axis_uses_actual_mode_specific_stable_ids(tmp_path):
    def gene(fid,kept=True,kind='Gene Expression'):
        return dict(feature_id=fid,feature_type=kind,kept=str(kept),total_counts='100')
    first=source(tmp_path,'p1',[gene('a'),gene('b',False),gene('c'),gene('protein',True,'Antibody Capture')])
    second=source(tmp_path,'p2',[gene('a'),gene('b'),gene('c',False),gene('d')])
    spot=service()._design(configuration(left='p1',right='p2'),[first,second])
    assert spot.resource_estimate.features==1 and spot.executable
    donor=service()._design(configuration(mode='donor_paired',left='p1',right='p2'),[first,second])
    assert donor.resource_estimate.features==3
