from pathlib import Path
from app.adapters.bio_insights_engine.worker import actual_identity,warm_render_environment,warm_microbiome_environment
from threadpoolctl import threadpool_info


def test_identity_stable_across_tabular_and_microbiome_warmup(tmp_path):
    warm_render_environment(tmp_path)
    tabular=actual_identity()
    warm_microbiome_environment()
    microbiome=actual_identity()
    assert tabular==microbiome
    assert any('scikit_bio.libs' in item['filepath'] for item in threadpool_info())
