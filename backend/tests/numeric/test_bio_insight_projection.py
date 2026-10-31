"""Same frozen numerical inputs yield identical full/projected pipeline bytes."""
import copy
from pathlib import Path
from bio_insights_fixtures import source,config,payload


def test_full_and_projected_pipeline_have_identical_registered_outputs(tmp_path):
    from app.adapters.bio_insights_engine.transport import project_transport_payload
    from app.adapters.bio_insights_engine.pipeline import run
    from app.domain.bio_insights.contracts import ComparisonConfig
    s=source(tmp_path,[[1,9],[2,8],[3,7],[7,3],[8,2],[9,1]])
    s['metadata'].update(feature_ids=['wrong_redundant_axis'],manifest={'not':'numerical input'},shape={'wrong':'redundant'})
    s['raw']['manifest']['source_note']='unread provenance; raw axis members remain authoritative'
    cfg=ComparisonConfig.model_validate(config(6)).model_dump(mode='json');value=payload(cfg,[s]);before=copy.deepcopy(value)
    first=tmp_path/'first';second=tmp_path/'second';first.mkdir();second.mkdir()
    left=run({**value,'output_directory':str(first)})
    right=run({**project_transport_payload(value),'output_directory':str(second)})
    assert value==before
    assert left['summary']==right['summary'] and left['methods']==right['methods']
    assert left['manifest']==right['manifest']
    assert {m['key']:Path(m['path']).read_bytes() for m in left['outputs']}=={m['key']:Path(m['path']).read_bytes() for m in right['outputs']}
