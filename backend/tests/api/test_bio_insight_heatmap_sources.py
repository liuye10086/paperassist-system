"""Real B02 persisted fixture; only metadata lineage is under test, no numeric fit."""
import copy
import pytest
from tests.api.test_projects import client


def test_original_b02_missing_metadata_can_only_inherit_from_exact_canonical_lineage(client,monkeypatch,tmp_path):
    from tests.integration.test_bio_analysis_wait import create,run,confirm
    from app.db.database import database_connection
    from app.core.config import get_data_dir
    from app.adapters.storage import ProjectStore
    from app.domain.bio_insights.sources import InsightSourceReader
    from app.domain.bio_insights.contracts import FigureConfig
    from app.domain.bio_insights.service import inherit_heatmap_metadata
    from app.core.exceptions import StorageError
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    assert run(created['task'],staging)['status']=='waiting_confirmation'
    queued=confirm(client,base,created,client.get(base+'/bio-analysis-runs/'+created['id']).json())
    assert queued.status_code==202,queued.text
    done=run(queued.json(),staging);assert done['status']=='succeeded'
    project=base.rsplit('/',1)[-1];identifier=done['result_bio_processed_dataset_version_id']
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
        sha=db.execute('SELECT manifest_sha256 FROM bio_processed_dataset_versions WHERE id=%s',(identifier,)).fetchone()['manifest_sha256']
    reader=InsightSourceReader(ProjectStore(get_data_dir(),owner_id=owner))
    with reader.store.connection() as db:processed=reader.resolve(db,project,dict(source_kind='bio_processed_dataset_version',source_id=identifier,sha256=sha,role='processed'))
    assert processed['metadata']['species_taxon_id'] is None and processed['metadata']['reference_version'] is None
    # Explicit frozen-result declaration fixture; no claim that a fit was run.
    result=dict(source_kind='bio_insight_result_version',source_id='fixed-comparison',metadata=dict(
        canonical_dataset_ids=[processed['metadata']['canonical_dataset_id']],species_taxon_id=9606,namespace='Ensembl',reference_version='explicit-v1'))
    config=FigureConfig(result_source_id='fixed-comparison',figure_type='heatmap',processed_source_id=identifier,
        expression_groups=[{'label':'A','observation_keys':[{'processed_version_id':identifier,'barcode':'AA-1'}]}])
    untouched=copy.deepcopy(processed)
    inherit_heatmap_metadata(config,[processed,result])
    assert processed['metadata']['reference_metadata_origin']=='linked_frozen_comparison'
    assert processed['metadata']['namespace']=='Ensembl'
    incompatible=copy.deepcopy(untouched);incompatible['metadata']['species_taxon_id']=10090
    with pytest.raises(StorageError):inherit_heatmap_metadata(config,[incompatible,result])
    unrelated=copy.deepcopy(result);unrelated['metadata']['canonical_dataset_ids']=[]
    with pytest.raises(StorageError):inherit_heatmap_metadata(config,[untouched,unrelated])
