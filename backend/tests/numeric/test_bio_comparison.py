import copy
import numpy as np
import pytest
from scipy.stats import mannwhitneyu, false_discovery_control
from app.adapters.bio_engine.manifest import Writer
from bio_insights_fixtures import source, config, payload, rows


def execute(tmp_path, value, name):
    from app.adapters.bio_insights_engine.comparison import run_comparison
    out = tmp_path / name; out.mkdir(); writer = Writer(out)
    result = run_comparison(value, writer)
    return result, writer


def test_rank_ties_direction_constant_and_complete_family(tmp_path):
    counts = np.array([[1, 8, 0], [1, 7, 0], [2, 6, 0], [2, 5, 0],
                       [6, 4, 0], [6, 3, 0], [9, 2, 0], [9, 1, 0]])
    s = source(tmp_path, counts); cfg = config(); value = payload(cfg, [s])
    result, w = execute(tmp_path, value, 'out')
    got = rows(w); assert len(got) == 3
    r = got[0]
    n = counts / counts.sum(1)[:, None] * 10000
    expected = mannwhitneyu(np.log1p(n[4:, 0]), np.log1p(n[:4, 0]),
                            alternative='two-sided', method='asymptotic', use_continuity=False)
    assert float(r['p_value']) == pytest.approx(expected.pvalue, abs=1e-14)
    assert float(r['effect_value']) > 0
    assert got[2]['p_value'] == got[2]['q_within_contrast'] == ''
    assert got[2]['reason'] == 'constant_gene'
    expected_q = false_discovery_control([float(got[0]['p_value']), float(got[1]['p_value']), 1])
    assert float(got[0]['q_within_contrast']) == pytest.approx(expected_q[0])
    reverse = copy.deepcopy(value)
    c = reverse['config']['contrasts'][0]; c['numerator'], c['denominator'] = c['denominator'], c['numerator']
    _, rw = execute(tmp_path, reverse, 'reverse')
    reversed_rows = rows(rw)
    assert float(reversed_rows[0]['effect_value']) == pytest.approx(-float(r['effect_value']))
    assert float(reversed_rows[0]['statistic']) == pytest.approx(-float(r['statistic']))
    assert reversed_rows[0]['p_value'] == r['p_value']
    assert result['inference_scope'] == 'spot_exploratory'
    assert result['summary']['family']['by_contrast']['c1']['family_size'] == 3


def test_bh_family_manual_na_and_prefilter():
    from app.adapters.bio_insights_engine.comparison import adjust_families
    items = [{'contrast_id': 'c', 'p_value': p, 'tested': True} for p in [.01, .04, .03, None]]
    items.append({'contrast_id': 'c', 'p_value': None, 'tested': False})
    summary = adjust_families(items, ['c'])
    for row, expected in zip(items, [.04, 4/75, 4/75, None, None]):
        assert row['q_within_contrast'] == pytest.approx(expected) if expected is not None else row['q_within_contrast'] is None
    assert summary['by_contrast']['c'] == {'family_size': 4, 'valid_p_values': 3, 'na_p_values': 1}


def test_float32_processed_layers_keep_float64_effect_and_exact_reversal(tmp_path):
    import hashlib
    from pathlib import Path
    counts=np.array([[1,8,3],[1,7,2],[2,6,1],[2,5,4],[6,4,5],[6,3,2],[9,2,1],[9,1,3]])
    s=source(tmp_path,counts)
    for key in ('normalized_data','log1p_data'):
        member=s['members'][key];path=Path(member['path'])
        np.save(path,np.load(path,allow_pickle=False).astype('float32'))
        member.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
    value=payload(config(),[s]);_,forward=execute(tmp_path,value,'forward32')
    reverse=copy.deepcopy(value);c=reverse['config']['contrasts'][0]
    c['numerator'],c['denominator']=c['denominator'],c['numerator']
    _,backward=execute(tmp_path,reverse,'backward32')
    for a,b in zip(rows(forward),rows(backward)):
        mean_a=float(a['mean_normalized_numerator']);mean_b=float(a['mean_normalized_denominator'])
        expected=np.log2((mean_a+1e-9)/(mean_b+1e-9))
        assert float(a['effect_value'])==pytest.approx(expected,rel=0,abs=1e-12)
        assert float(a['effect_value'])+float(b['effect_value'])==pytest.approx(0,rel=0,abs=1e-12)
        assert [a[k] for k in ('p_value','q_within_contrast','q_global_family')]==[b[k] for k in ('p_value','q_within_contrast','q_global_family')]


def test_global_family_is_independent_of_within_contrast_family():
    from app.adapters.bio_insights_engine.comparison import adjust_families
    items=[{'contrast_id':cid,'p_value':p,'tested':True} for cid,p in [('a',.01),('a',.4),('b',.02),('b',None)]]
    summary=adjust_families(items,['a','b'])
    expected=false_discovery_control([.01,.4,.02,1])
    assert items[0]['q_within_contrast']==pytest.approx(.02)
    assert items[0]['q_global_family']==pytest.approx(expected[0])
    assert summary['global']=={'family_size':4,'valid_p_values':3,'na_p_values':1}


def test_contrast_named_global_is_a_normal_independent_contrast():
    from app.adapters.bio_insights_engine.comparison import adjust_families
    items=[{'contrast_id':cid,'p_value':p,'tested':True} for cid,p in [('global',.01),('other',.5)]]
    adjust_families(items,['global','other'])
    assert items[0]['q_within_contrast']==pytest.approx(.01)
    assert items[0]['q_global_family']==pytest.approx(.02)


def test_member_hash_and_low_normalized_value_mismatch_are_rejected(tmp_path):
    s=source(tmp_path,[[1,1000000000],[1,8],[1,7],[2,6],[3,5],[4,4]])
    member=s['members']['normalized_data']
    values=np.load(member['path'],allow_pickle=False);values[0]=.05
    np.save(member['path'],values)
    with pytest.raises(ValueError,match='hash'):execute(tmp_path,payload(config(6),[s]),'hash')
    import hashlib
    member['sha256']=hashlib.sha256(open(member['path'],'rb').read()).hexdigest()
    with pytest.raises(ValueError,match='normalized_raw_mismatch'):execute(tmp_path,payload(config(6),[s]),'values')


def test_multi_source_barcode_namespace_common_axis_and_canonical(tmp_path):
    s1 = source(tmp_path, [[1,2,3],[2,3,4],[3,4,5]], ids=['g1','g2','only1'])
    s2 = source(tmp_path, [[4,2,1],[5,3,2],[6,4,3]], source_id='p2', canonical='dataset2', ids=['g2','g1','only2'])
    cfg = config(6, source_id='p1', split=3)
    cfg['contrasts'][0]['numerator']['observation_keys'] = [{'processed_version_id':'p2','barcode':f'b{i}'} for i in range(3)]
    result, w = execute(tmp_path, payload(cfg, [s1,s2]), 'out')
    assert {r['feature_id'] for r in rows(w)} == {'g1','g2'}
    assert len(rows(w, 'feature_exclusions')) == 2
    assert result['summary']['actual_units'][0]['spots_numerator'] == 3
    bad = copy.deepcopy(s2); bad['metadata']['canonical_dataset_id'] = 'dataset1'
    with pytest.raises(ValueError, match='duplicate_canonical_dataset'):
        execute(tmp_path, payload(cfg,[s1,bad]), 'bad')
