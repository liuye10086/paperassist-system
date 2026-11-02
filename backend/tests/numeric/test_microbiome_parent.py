import csv,json
from pathlib import Path
import pytest
from microbiome_fixture import source_fixture
from app.adapters.bio_insights_engine.pipeline import run
from app.adapters.bio_insights_process import validate_result
from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig

def test_parent_complete_reconciliation_and_missing_audit(tmp_path):
    source,config=source_fixture(tmp_path/'source',vectors=[[None,90],[20,80],[40,60],[60,40],[80,20],[100,0]])
    out=tmp_path/'description';out.mkdir();payload=dict(schema_version=1,kind='bio_comparison',config=config.model_dump(mode='json'),sources=[source],identity=dict(project_id='synthetic',plan_version_id='plan'),output_directory=str(out))
    result=run(payload);validate_result(result,out,payload)
    assert result['summary']['excluded_samples']==1
    source,config=source_fixture(tmp_path/'infer')
    config=MicrobiomeConfig.model_validate({**config.model_dump(),'design':'independent','independence_confirmed':True,'independence_basis':'synthetic','beta_inference':True,'permutations':19})
    out=tmp_path/'inference';out.mkdir();payload.update(config=config.model_dump(mode='json'),sources=[source],output_directory=str(out));result=run(payload);validate_result(result,out,payload)
    with (out/'microbiome_conservation.tsv').open(encoding='utf-8') as stream:
        rows=list(csv.DictReader(stream,delimiter='\t'));assert all(r['conserved']=='True' for r in rows)
