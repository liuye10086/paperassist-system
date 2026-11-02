import json,math
from pathlib import Path
import numpy as np
import pytest
from microbiome_fixture import source_fixture
from app.adapters.bio_engine.manifest import Writer
from app.adapters.bio_insights_engine.microbiome import diversity,distances_ordination,beta_tests,run_microbiome
from app.domain.bio_insights.microbiome_design import prepare_microbiome,validate_microbiome_design
from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig

REFERENCE=json.loads((Path(__file__).with_name('microbiome_reference.json')).read_text())

def test_oracle_and_exact_allocations():
    p=np.array([[.1,.9],[.2,.8],[.4,.6],[.6,.4],[.8,.2],[1.,0.]])
    alpha=diversity(p)
    assert np.allclose(alpha['shannon'],[.3250829733914482,.5004024235381879,.6730116670092565,.6730116670092565,.5004024235381879,0],atol=1e-12)
    assert np.allclose(alpha['simpson'],[.18,.32,.48,.48,.32,0],atol=1e-12)
    assert alpha['observed_features'].tolist()==[2,2,2,2,2,1]
    distance,eig,coords,positive,total,negative=distances_ordination(p)
    assert np.allclose(distance,abs(p[:,0,None]-p[:,0]),atol=1e-12)
    assert np.allclose(np.linalg.norm(coords[:,None]-coords[None,:],axis=2),distance,atol=1e-12)
    assert not negative
    from itertools import combinations
    from fractions import Fraction as Q
    x=list(map(Q,['.1','.2','.4','.6','.8','1']))
    def f(v,a):
        gs=[[v[i] for i in range(6) if (i in a)==b] for b in (True,False)];grand=sum(v)/6
        return sum(3*(sum(g)/3-grand)**2 for g in gs)/(sum(sum((z-sum(g)/3)**2 for z in g) for g in gs)/4)
    for a in combinations(range(6),3):
        centers=[sorted(x[i] for i in range(6) if (i in a)==b)[1] for b in (True,False)]
        z=[abs(x[i]-centers[0 if i in a else 1]) for i in range(6)]
        result=beta_tests(distance,['A' if i in a else 'B' for i in range(6)],permutations=0)
        assert result[0]['statistic']==pytest.approx(float(f(x,a)),abs=1e-10)
        assert result[1]['statistic']==pytest.approx(float(f(z,a)),abs=1e-5)
    assert beta_tests(distance,['A']*3+['B']*3,permutations=19,seed=4)==beta_tests(distance,['A']*3+['B']*3,permutations=19,seed=4)

def test_scale_audit_taxonomy_and_alpha_bridge(tmp_path):
    for scale in ('counts','fraction','percent'):
        source,cfg=source_fixture(tmp_path/scale,scale=scale)
        data=prepare_microbiome(cfg,[source]);assert np.allclose(data['relative'][0],[.1,.9])
        for design,method in [('independent','welch_t'),('paired','paired_t')]:
            config=cfg.model_copy(update=dict(design=design,alpha_method=method,pair_column='pair',independence_confirmed=True,independence_basis='synthetic',contrasts=[dict(contrast_id='A_B',name='A-B',numerator='A',denominator='B')],family_contrast_ids=['A_B']))
            config=MicrobiomeConfig.model_validate(config.model_dump());out=tmp_path/(scale+design);out.mkdir()
            result=run_microbiome(dict(config=config.model_dump(),sources=[source]),Writer(out));assert result['summary']['row_count']==3
    source,cfg=source_fixture(tmp_path/'zero',vectors=[[0,0],[10,90],[20,80],[30,70]])
    data=prepare_microbiome(cfg,[source]);assert data['audit'][0]['reason']=='all_zero_sample';assert len(data['included'])==3
    taxonomy=[dict(feature_id='F1',Kingdom='Bacteria',Phylum='P1',Genus='Same'),dict(feature_id='F2',Kingdom='Bacteria',Phylum='P2',Genus='Same')]
    source,cfg=source_fixture(tmp_path/'tax',taxonomy=taxonomy);assert len(set(prepare_microbiome(cfg,[source])['paths']))==2

def test_invalid_scale_and_negative_eigenvalues(tmp_path):
    source,cfg=source_fixture(tmp_path/'fraction',scale='fraction',vectors=[[11,90],[20,80],[40,60],[60,40],[80,20],[100,0]])
    with pytest.raises(ValueError,match='closure'):prepare_microbiome(cfg.model_copy(update=dict(closure_confirmed=False)),[source])
    with pytest.raises(ValueError,match='independent_exchangeable'):MicrobiomeConfig.model_validate({**cfg.model_dump(),'design':'paired','beta_inference':True})
    # Non-Euclidean Bray-Curtis example; full signed spectrum remains available.
    p=np.array([[1,0,0],[0,1,0],[0,0,1],[.5,.5,0],[0,.5,.5]])
    d,e,c,pos,total,negative=distances_ordination(p);assert negative and np.any(e<0)
