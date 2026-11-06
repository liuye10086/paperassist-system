"""Complete manifests captured from real tools on synthetic count matrices.

Fixtures retain all pipeline summary/steps/params, not handcrafted report stubs.
The R fixture was produced by the isolated pinned Harmony worker; these are not
biological validation data. No computation, service, DB or R runtime is needed.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import io
import json

from docx import Document
import pytest


@pytest.mark.parametrize('fixture',['batch3_covariates_complete_manifest.json','batch3_harmony_complete_manifest.json'])
@pytest.mark.parametrize('language',['zh-CN','en'])
def test_complete_scientific_manifest_builds_word_and_retains_covariate_method(fixture,language):
    from app.adapters.single_cell_report import build_single_cell_report
    from app.domain.research_results.bio_projection import project_bio_facts
    from app.domain.research_results.contracts import FrozenResearchSource
    body=(Path(__file__).resolve().parents[1]/'fixtures'/'single_cell'/fixture).read_bytes()
    manifest=json.loads(body);before=deepcopy(manifest)
    source=FrozenResearchSource(project_id='p',source_kind='bio_processed_dataset_version',source_id='i',
        sha256=hashlib.sha256(body).hexdigest(),title='Synthetic counts / real tools',provenance='system_computed',content=manifest)
    catalog=project_bio_facts(source)
    step_number=next(i for i,step in enumerate(manifest['steps']) if step['key']=='technical_covariates')
    method=next(m for m in catalog.methods if m.source.locator.field_path==f'steps[{step_number}]')
    assert method.parameters=={'columns':['log1p_total_counts']} and method.executed is True
    result=build_single_cell_report('p','i',source.sha256,manifest,{},[],language)
    doc=Document(io.BytesIO(result));text='\n'.join(p.text for p in doc.paragraphs)
    assert 'Harmony' in text and 'log1p_total_counts' in text and 'X_pca' in text
    assert manifest==before and source.content==before
