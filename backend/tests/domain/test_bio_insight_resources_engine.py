import gzip
import hashlib
import importlib
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def engine():
    return importlib.import_module('app.adapters.bio_insights_engine.resources')


OBO = '''format-version: 1.2
data-version: releases/2026-09-01

[Term]
id: GO:0008150
name: biological_process
namespace: biological_process

[Term]
id: GO:0000001
name: parent
namespace: biological_process
is_a: GO:0008150 ! root

[Term]
id: GO:0000002
name: child
namespace: biological_process
alt_id: GO:9999999
relationship: part_of GO:0000001 ! parent
relationship: has_part GO:0000003 ! excluded

[Term]
id: GO:0000003
name: unrelated
namespace: biological_process

[Term]
id: GO:0000004
name: obsolete
namespace: biological_process
is_obsolete: true
replaced_by: GO:0000002
'''


def gaf(gene='P1', term='GO:9999999', qualifier='enables', taxon='taxon:9606', evidence='IDA'):
    return '\t'.join(['UniProtKB', gene, gene, qualifier, term, 'PMID:1', evidence, '', 'P',
                      'name', '', 'protein', taxon, '20260901', 'TEST', '', ''])


def test_go_alt_propagates_only_allowed_relations_and_excludes_roots():
    e = engine(); ontology = e.parse_obo(OBO.splitlines())
    result = e.parse_gaf(['!gaf-version: 2.2', gaf()], ontology, 9606)
    sets = {r['term_id']: r['genes'] for r in result['terms']}
    assert sets['GO:0000002'] == sets['GO:0000001'] == ['P1']
    assert 'GO:0008150' not in sets
    assert sets['GO:0000003'] == []
    assert 'GO:0000004' not in sets
    assert result['stats']['alt_id_resolved'] == 1
    assert result['stats']['accepted_annotations'] == 1


def test_go_not_wrong_species_obsolete_unknown_evidence_and_duplicate_are_counted():
    e = engine(); ontology = e.parse_obo(OBO.splitlines())
    lines = ['!gaf-version: 2.2', gaf(), gaf(), gaf('N',qualifier='NOT|enables'),
             gaf('M',taxon='taxon:10090'), gaf('O',term='GO:0000004'),
             gaf('U',term='GO:5555555'), gaf('E',evidence='IEA')]
    result = e.parse_gaf(lines, ontology, 9606, evidence_codes=['IDA'])
    for name in ['duplicate_annotations','not_qualifier','wrong_species','obsolete_term','unknown_term','evidence_excluded']:
        assert result['stats'][name] == 1
    assert len(result['exclusions']) == 5


@pytest.mark.parametrize('lines', [[], [gaf()], ['!gaf-version: 2.1',gaf()], ['!gaf-version: 2.2','bad\tline']])
def test_gaf_version_or_corrupt_rows_are_refused(lines):
    e=engine()
    with pytest.raises(ValueError):e.parse_gaf(lines,e.parse_obo(OBO.splitlines()),9606)


def test_ontology_cycle_or_conflicting_alt_id_rejected():
    e=engine()
    for suffix in ['\n[Term]\nid: GO:0000005\nname: collision\nalt_id: GO:9999999\n',
                   '\n[Term]\nid: GO:0000006\nname: cycle\nis_a: GO:0000006\n']:
        with pytest.raises(ValueError):e.parse_obo((OBO+suffix).splitlines())


def test_gmt_dedup_and_name_conflict():
    e=engine(); result=e.parse_gmt(['T\tname\tg1\tg1\tg2','T\tname\tg3','Z\tother\tg2'])
    assert result['terms'][0]['genes']==['g1','g2','g3']
    assert result['stats']['duplicate_memberships']==1
    with pytest.raises(ValueError):e.parse_gmt(['T\ta\tg1','T\tb\tg2'])


def test_mapping_never_silently_selects_one_to_many_or_strips_version():
    e=engine(); rows=[{'source_id':'ENSG1.2','target_id':'P1'}, {'source_id':'ENSG1.3','target_id':'P2'},
                       {'source_id':'ENSG2','target_id':'P3'}, {'source_id':'ENSG2','target_id':'P4'},
                       {'source_id':'ENSG3','target_id':'P3'}, {'source_id':'ENSG3','target_id':'P3'}]
    result=e.normalize_mapping(rows)
    assert result['mapping']=={'ENSG1.2':'P1','ENSG1.3':'P2','ENSG3':'P3'}
    assert result['ambiguous_source_ids']==['ENSG2']
    stripped=e.normalize_mapping(rows,strip_ensembl_version=True)
    assert 'ENSG1' not in stripped['mapping']
    assert stripped['transformations'][0]=={'original_id':'ENSG1.2','normalized_id':'ENSG1'}


def test_feature_annotations_preserve_unknown_zero_false_and_units():
    e=engine(); base=dict(feature_id='G',unit='score',source='provided',evidence_status='provided')
    result=e.normalize_annotations([{**base,'field':'numeric','value':'0','value_type':'number'},
        {**base,'field':'flag','value':'false','value_type':'boolean'},
        {**base,'field':'missing','value':'','value_type':'number','evidence_status':'unknown'}])
    assert [r['value'] for r in result['annotations']]==[False,None,0.0]
    assert result['annotations'][1]['evidence_status']=='unknown'
    with pytest.raises(ValueError):e.normalize_annotations([{**base,'field':'bad','value':'NaN','value_type':'number'}])


def test_gzip_stream_expansion_and_hash_are_enforced(tmp_path):
    e=engine(); path=tmp_path/'x.gmt.gz'; path.write_bytes(gzip.compress(b'T\tname\tg1\n'*100))
    member=dict(path=str(path),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError):list(e.text_lines(member,'gmt.gz',64))
    assert len(list(e.text_lines(member,'gmt.gz',4096)))==100
    with pytest.raises(ValueError):list(e.text_lines({**member,'sha256':'0'*64},'gmt.gz',4096))


def test_go_declared_namespace_must_match_gaf_db():
    e=engine()
    with pytest.raises(ValueError,match='gaf_namespace_mismatch'):
        e.parse_gaf(['!gaf-version: 2.2',gaf()],e.parse_obo(OBO.splitlines()),9606,namespace='Ensembl')


def test_normalized_collection_limits_are_applied_to_unique_relations(monkeypatch):
    e=engine();monkeypatch.setattr(e,'MAX_RELATIONS',2)
    with pytest.raises(ValueError,match='resource_relation_limit'):
        e.parse_gmt(['T\tname\ta\tb','U\tother\ta'])


def test_expansion_exact_size_is_not_just_a_declaration(tmp_path):
    e=engine();path=tmp_path/'x.gz';path.write_bytes(gzip.compress(b'abc\n'))
    member=dict(path=str(path),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError,match='resource_expansion_size_mismatch'):
        list(e.text_lines(member,'gaf.gz',100,expected_size=5))


def test_declared_gaf_ontology_release_must_match_obo():
    e=engine()
    with pytest.raises(ValueError,match='gaf_ontology_release_mismatch'):
        e.parse_gaf(['!gaf-version: 2.2','!go-version: http://purl.obolibrary.org/obo/go/releases/2025-01-01/extensions/go-plus.ofn',gaf()],e.parse_obo(OBO.splitlines()),9606)
