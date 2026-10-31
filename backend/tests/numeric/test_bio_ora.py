from pathlib import Path
import hashlib
import json
import pytest
from app.adapters.bio_engine.manifest import Writer
from bio_insights_fixtures import rows


def result_source(tmp_path, *, sid='result1', namespace='ensembl', complete=True, statistics=None):
    path=tmp_path/sid;path.mkdir();w=Writer(path)
    values=[]
    for i in range(10 if statistics is None else len(statistics)):
        values.append({'row_key':f'row{i}','feature_id':f'g{i}','symbol':f'G{i}','contrast_id':'c1',
                       'numerator':'B','denominator':'A','effect_value':2 if i<3 else -2,
                       'effect_name':'effect_log2_normalized','effect_unit':'log2 normalized expression ratio',
                       'statistic':None if statistics is None else statistics[i],
                       'p_value':.01,'q_within_contrast':.01 if i<3 else .5,'q_global_family':.02,
                       'tested':True,'test_status':'tested','reason':None,'inference_scope':'spot_exploratory'})
    w.table('comparison_results',values)
    manifest={'kind':'bio_comparison','summary':{'tested_universe_complete':complete},
              'methods':{'name':'synthetic_engine_fixture'},'inference_scope':'spot_exploratory'}
    w.json('manifest',manifest)
    return {'source_kind':'bio_insight_result_version','source_id':sid,'role':'result','sha256':'a'*64,
            'members':{a['key']:a for a in w.artifacts},
            'metadata':{'plan_config':{'kind':'comparison','species_taxon_id':9606,'namespace':namespace,'reference_version':'GRCh38.1'},
                        'species_taxon_id':9606,'namespace':namespace,'reference_version':'GRCh38.1',
                        'summary_json':manifest['summary'],'inference_scope':'spot_exploratory'}}


def resource_source(tmp_path, *, sid='resource1', namespace='ensembl', taxon=9606, terms=None, mapping=None):
    path=tmp_path/sid;path.mkdir();w=Writer(path)
    data={'schema_version':1,'kind':'gene_sets' if mapping is None else 'id_mapping','species_taxon_id':taxon,
          'namespace':namespace,'release':'synthetic-v1','source':{'name':'hand-built fixture'},
          'usage':{'redistribution_allowed':True,'scope':'redistributable','basis':'synthetic fixture'}}
    if mapping is None:data['terms']=terms or [
        {'term_id':'t1','name':'test1','namespace':'BP','genes':['g0','g1','g3','g4']},
        {'term_id':'t0','name':'zero-hit','namespace':'MF','genes':['g7','g8']}]
    else:data.update(mapping)
    w.json('resource',data)
    return {'source_kind':'bio_resource_version','source_id':sid,'role':'gene_sets' if mapping is None else 'id_mapping',
            'sha256':w.artifacts[0]['sha256'],'members':{a['key']:a for a in w.artifacts},'metadata':{}}


def config(**kw):
    return {'kind':'ora','result_source_ids':['result1'],'resource_source_ids':['resource1'],
            'contrast_ids':['c1'],'direction':'both','q_threshold':.05,'minimum_absolute_effect':1.,
            'min_size':1,'max_size':10,**kw}


def execute(tmp_path, cfg, sources, name='out'):
    from app.adapters.bio_insights_engine.enrichment import run_enrichment
    out=tmp_path/name;out.mkdir();w=Writer(out)
    result=run_enrichment({'schema_version':1,'kind':'bio_enrichment','config':cfg,
                           'identity':{'plan_version_id':'ep1'},'sources':sources},w)
    return result,w


def test_ora_exact_manual_probability_complete_zero_hit_and_bh(tmp_path):
    source=result_source(tmp_path);resource=resource_source(tmp_path)
    result,w=execute(tmp_path,config(),[source,resource])
    table={r['term_id']:r for r in rows(w,'enrichment_results')}
    hit=table['t1'];assert [int(hit[k]) for k in ['N','K','n','k']]==[10,4,3,2]
    assert float(hit['p_value'])==pytest.approx(1/3,abs=1e-14)
    assert float(hit['q_value'])==pytest.approx(2/3,abs=1e-14)
    assert table['t0']['p_value']=='1.0' and table['t0']['k']=='0'
    assert result['summary']['row_count']==2 and result['inference_scope']=='derived'


def test_empty_foreground_is_legal_and_top_table_needs_background(tmp_path):
    source=result_source(tmp_path);resource=resource_source(tmp_path)
    result,w=execute(tmp_path,config(q_threshold=0.),[source,resource])
    assert result['summary']['empty_foregrounds']==1
    assert all(r['n']=='0' and r['p_value']=='1.0' for r in rows(w,'enrichment_results'))
    source['metadata']['summary_json']['tested_universe_complete']=False
    # Change actual frozen manifest as well, not just a caller claim.
    member=source['members']['manifest'];value=json.loads(open(member['path']).read());value['summary']['tested_universe_complete']=False
    content=json.dumps(value).encode();open(member['path'],'wb').write(content);member.update(size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
    with pytest.raises(ValueError,match='background'):execute(tmp_path,config(),[source,resource],'top')


def test_mapping_many_to_one_deduplicates_and_wrong_species_is_blocked(tmp_path):
    source=result_source(tmp_path)
    resource=resource_source(tmp_path,namespace='symbol',terms=[{'term_id':'t','name':'mapped','namespace':'BP','genes':['A','B','C','D']}])
    mapping=resource_source(tmp_path,sid='mapping',namespace='ensembl',mapping={
        'source_namespace':'ensembl','target_namespace':'symbol','mapping':{f'g{i}':('A' if i<2 else chr(64+i)) for i in range(10)},
        'ambiguous_source_ids':[],'many_to_one_target_ids':['A'],'strip_ensembl_version':False})
    _,w=execute(tmp_path,config(mapping_source_ids=['mapping']),[source,resource,mapping])
    record=rows(w,'enrichment_results')[0]
    assert int(record['n'])==2 and int(record['N'])==9
    bad=resource_source(tmp_path,sid='mouse',taxon=10090)
    with pytest.raises(ValueError,match='species'):execute(tmp_path,config(resource_source_ids=['mouse']),[source,bad],'wrong')


def test_foreground_outside_background_is_blocked(tmp_path):
    source=result_source(tmp_path);resource=resource_source(tmp_path)
    path=tmp_path/'foreground.tsv';path.write_text('feature_id\ng99\n')
    source['members']['foreground']={'path':str(path),'size_bytes':path.stat().st_size,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'format':'tsv','role':'foreground'}
    with pytest.raises(ValueError,match='subset'):execute(tmp_path,config(foreground_member_key='foreground'),[source,resource])


def test_two_collections_freeze_separate_or_joint_bh_and_avoid_term_collision(tmp_path):
    source=result_source(tmp_path);r1=resource_source(tmp_path)
    r2=resource_source(tmp_path,sid='resource2',terms=[{'term_id':'t1','name':'second','namespace':'BP','genes':['g0']}])
    _,w=execute(tmp_path,config(resource_source_ids=['resource1','resource2']),[source,r1,r2])
    separate={r['collection_term_id']:r for r in rows(w,'enrichment_results')}
    _,joint=execute(tmp_path,config(resource_source_ids=['resource1','resource2'],merge_collections=True),[source,r1,r2],'joint')
    merged={r['collection_term_id']:r for r in rows(joint,'enrichment_results')}
    assert len(separate)==3
    assert float(separate['resource2::t1']['q_value'])==pytest.approx(.3)
    assert float(merged['resource2::t1']['q_value'])==pytest.approx(.5)


def test_empty_explicit_background_is_blocked_and_explicit_top_background_is_allowed(tmp_path):
    source=result_source(tmp_path,complete=False);resource=resource_source(tmp_path)
    path=tmp_path/'background.json';path.write_text(json.dumps({'feature_ids':[f'g{i}' for i in range(10)]}))
    member={'path':str(path),'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'format':'json','role':'background'}
    background={'source_kind':'original_file','source_id':'background','role':'background','sha256':member['sha256'],
                'members':{'ids':member},'metadata':{}}
    _,w=execute(tmp_path,config(background_source_id='background',background_member_key='ids'),[source,resource,background])
    assert len(rows(w,'enrichment_results'))==2
    path.write_text('{"feature_ids":[]}');member.update(size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError,match='empty_background'):
        execute(tmp_path,config(background_source_id='background',background_member_key='ids'),[source,resource,background],'empty')


@pytest.mark.parametrize('marker',['NA','NOT_MEASURED'])
def test_external_q_missing_markers_are_excluded_without_losing_universe(tmp_path,marker):
    source=result_source(tmp_path)
    path=Path(source['members']['comparison_results']['path'])
    text=path.read_text().replace('q_within_contrast','original_q')
    lines=text.splitlines();header=lines[0].split('\t');q=header.index('original_q')
    cells=lines[2].split('\t');cells[q]=marker;lines[2]='\t'.join(cells)
    raw=('\n'.join(lines)+'\n').encode();path.write_bytes(raw)
    source['members']['comparison_results'].update(sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw))
    source['metadata']['plan_config'].update(kind='result_import',na_values=['',marker])
    result,w=execute(tmp_path,config(q_column='original_q'),[source,resource_source(tmp_path)])
    table=rows(w,'enrichment_results')
    assert all(int(row['N'])==10 and int(row['n'])==2 for row in table)
    assert marker.encode() in path.read_bytes()
