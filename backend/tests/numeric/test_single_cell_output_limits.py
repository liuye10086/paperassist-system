from pathlib import Path
import pytest
from app.adapters.bio_engine.manifest import Writer


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('budget,prior,accepted',[(512*1024**2,512*1024**2,False),(1024**3,512*1024**2,True),(1024**3,1024**3-2,True),(1024**3,1024**3-1,False)])
def test_writer_enforces_selected_aggregate_boundary_with_declared_prior_artifacts(tmp_path,existing,budget,prior,accepted):
    # Prior registered metadata exercises exact byte accounting without allocating
    # a half-gigabyte fixture. The newly written member is real and hash-checked.
    writer=Writer(tmp_path,max_output_bytes=budget)
    writer.artifacts=[dict(size_bytes=prior)]
    if existing:
        path=tmp_path/'new.txt';path.write_bytes(b'ok')
        action=lambda:writer.existing('new',path,'txt')
    else:action=lambda:writer.add('new',b'ok','txt')
    if accepted:
        item=action();assert item['size_bytes']==2 and Path(item['path']).read_bytes()==b'ok'
    else:
        with pytest.raises(ValueError,match='output_budget_exceeded'):action()


def test_expanded_aggregate_does_not_expand_single_member_limit(tmp_path):
    writer=Writer(tmp_path,max_output_bytes=1024**3)
    class OversizedMember:
        def __len__(self):return 256*1024**2+1
    with pytest.raises(ValueError,match='output_budget_exceeded'):
        writer.add('oversized',OversizedMember(),'txt')
