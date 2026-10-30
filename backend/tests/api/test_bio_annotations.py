import importlib.util
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_annotation_polygon_boundary_and_overlap_never_invent_donor_replicates():
    module_name = 'app.adapters.bio_annotation_store'
    assert importlib.util.find_spec(module_name) is not None, 'Persistent B02 annotations missing'
    module = __import__(module_name, fromlist=['assign_regions'])
    points = [{'barcode':'corner','x':0.0,'y':0.0}, {'barcode':'overlap','x':1.5,'y':1.5},
              {'barcode':'outside','x':10.0,'y':10.0}]
    regions = [dict(id='a',label_id='la',points=[[0,0],[2,0],[2,2],[0,2]],priority=1),
               dict(id='b',label_id='lb',points=[[1,1],[3,1],[3,3],[1,3]],priority=2)]
    rows = module.assign_regions(points, regions, 'ambiguity')
    assert rows[0]['label_id']=='la'
    assert rows[1]['label_id'] is None and rows[1]['status']=='ambiguous'
    assert rows[2]['label_id'] is None and rows[2]['status']=='unknown'
    assert all('donor' not in row for row in rows)
    assert module.assign_regions(points, regions, 'priority')[1]['label_id']=='lb'


def test_annotation_cluster_assignments_and_conflicting_region_remain_explicit():
    from app.adapters.bio_annotation_store import assign_regions
    points=[dict(barcode='known',x=1,y=1,cluster='0'),dict(barcode='other',x=4,y=4,cluster='1')]
    labels=[dict(id='cluster-label',cluster_ids=['0'])]
    rows=assign_regions(points,[], 'ambiguity',labels)
    assert rows[0]['label_id']=='cluster-label' and rows[1]['status']=='unknown'
    regions=[dict(id='r',label_id='different',points=[[0,0],[2,0],[2,2],[0,2]],priority=1)]
    assert assign_regions(points,regions,'ambiguity',labels)[0]['status']=='ambiguous'
    assert assign_regions(points,regions,'priority',labels)[0]['label_id']=='different'


def test_annotation_rejects_self_crossing_polygon_with_nonzero_signed_area():
    from app.adapters.bio_annotation_store import valid_polygon
    assert valid_polygon([[0,0],[2,0],[2,2],[0,2]])
    assert not valid_polygon([[0,0],[3,3],[0,3],[2,0]])
