import pytest
"""File-backed recipe checks with explicit synthetic result lineage."""
import csv
import hashlib
import io
from app.adapters.bio_engine.manifest import Writer
from app.adapters.bio_insights_engine.candidates import run_candidates


def result_source(root,sid,canonical,rows):
    path=root/sid;path.mkdir();writer=Writer(path)
    data=[]
    for feature,effect,q in rows:
        data.append(dict(feature_id=feature,row_key=sid+feature,contrast_id='c',effect_value=effect,q_within_contrast=q,tested=True,
            numerator='A',denominator='B',effect_name='log2fc',effect_unit='log2',inference_scope='spot_exploratory'))
    writer.table('comparison_results',data)
    return dict(source_id=sid,metadata=dict(species_taxon_id=9606,namespace='ensembl',reference_version='fixture',canonical_dataset_ids=[canonical]),
        members={a['key']:a for a in writer.artifacts})


def test_file_recipe_deduplicates_canonical_support_and_preserves_na(tmp_path):
    a=result_source(tmp_path,'a','same',[('g1',2,0),('g2',-2,.03),('g3',None,None)])
    b=result_source(tmp_path,'b','same',[('g1',2,0),('g2',-2,.03)])
    c=result_source(tmp_path,'c','other',[('g1',1,.04),('g2',2,.04)])
    payload=dict(identity={'source_digest':'a'*64},sources=[a,b,c],config=dict(kind='candidate',result_source_ids=['a','b','c'],
        source_contrasts={'a':'c','b':'c','c':'c'},primary_result_source_id='a',
        steps=[dict(operation='union'),dict(operation='include',feature_ids=['g1','g2','g3','absent'])]))
    output=tmp_path/'out';output.mkdir();writer=Writer(output);result=run_candidates(payload,writer)
    def rows(key):return list(csv.DictReader((output/(key+'.tsv')).open(),delimiter='\t'))
    table=rows('candidate_results');byid={r['feature_id']:r for r in table}
    assert table[0]['feature_id']=='g1'
    assert byid['g1']['support_count']=='2' and byid['g1']['support_source_count']=='3'
    assert byid['g1']['same_direction_support_count']=='2'
    assert byid['g2']['conflict_count']=='1' and byid['g2']['same_direction_support_count']=='1'
    assert byid['g3']['primary_q']=='' and byid['g1']['primary_q']=='0.0'
    assert rows('missing_requested_features')[0]['feature_id']=='absent'
    assert result['methods']['dependencies']['independence_verified'] is False


@pytest.mark.parametrize('marker',['NA','NOT_MEASURED'])
def test_candidates_use_frozen_external_na_and_preserve_zero(tmp_path,marker):
    a=result_source(tmp_path,'a','same',[('zero',2,0),('unknown',2,marker)])
    path=__import__('pathlib').Path(a['members']['comparison_results']['path'])
    raw=path.read_bytes().replace(b'q_within_contrast',b'original_q');path.write_bytes(raw)
    a['members']['comparison_results'].update(sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw))
    a['metadata'].update(provenance='external_result',plan_config={'kind':'result_import','na_values':['',marker]})
    payload=dict(identity={'source_digest':'a'*64},sources=[a],config=dict(kind='candidate',result_source_ids=['a'],source_contrasts={'a':'c'},primary_result_source_id='a',steps=[dict(operation='threshold',source_ids=['a'],q_column='original_q',q_threshold=.05)]))
    output=tmp_path/'out';output.mkdir();writer=Writer(output);run_candidates(payload,writer)
    table=list(csv.DictReader((output/'candidate_results.tsv').open(),delimiter='\t'))
    assert [row['feature_id'] for row in table]==['zero'] and table[0]['primary_q']=='0.0'
    assert marker.encode() in path.read_bytes()
