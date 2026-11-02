from app.adapters.bio_insights_engine.feature_extract import extract_fasta


def test_fasta_preserves_duplicate_ids_and_nucleotide_denominator():
    rows, excluded = extract_fasta('>id first\nACGTNN\n>id second\nNN\n', 'dna', 'v1')
    assert [r['feature_id'] for r in rows] == ['v1:1', 'v1:2']
    assert rows[0]['original_id'] == rows[1]['original_id'] == 'id'
    assert (rows[0]['length'], rows[0]['valid_count'], rows[0]['ambiguous_count'], rows[0]['gc_fraction']) == (6, 4, 2, 0.5)
    assert rows[1]['gc_fraction'] is None
    assert excluded == []


def test_fasta_rna_and_protein_audit():
    rows, _ = extract_fasta('>rna\naCguN\n', 'rna', 'v')
    assert (rows[0]['valid_count'], rows[0]['gc_fraction']) == (4, 0.5)
    rows, excluded = extract_fasta('>p desc\nACX*\n>empty\n', 'protein', 'v')
    assert rows[0]['standard_count'] == 2
    assert rows[0]['composition']['A'] == 0.5
    assert rows[0]['standard_fraction'] == 0.5
    assert rows[0]['nonstandard_count'] == 1
    assert rows[0]['stop_positions'] == [4]
    assert excluded[0]['reason'] == 'empty_sequence'


def test_fasta_rejects_invalid_symbols_without_deleting_them():
    rows, excluded = extract_fasta('>x\nAC-T\n', 'dna', 'v')
    assert rows == []
    assert excluded[0]['reason'] == 'invalid_symbol'
    assert excluded[0]['invalid_symbols'] == '-'


def test_structure_altloc_geometry_and_exclusion_audit():
    from app.adapters.bio_insights_engine.feature_extract import extract_structure
    pdb = (
        'ATOM      1  CA AALA A   1       0.000   0.000   0.000  0.50 20.00           C  \n'
        'ATOM      2  CA BALA A   1       8.000   0.000   0.000  0.50 20.00           C  \n'
        'ATOM      3  CA  GLY A   2A      2.000   0.000   0.000  1.00 20.00           C  \n'
        'HETATM    4  O   HOH A   3       3.000   0.000   0.000  1.00 20.00           O  \n'
        'TER\nEND\n'
    )
    result = extract_structure(pdb, 'pdb', model_id=1, chain_id='A')
    assert result['summary']['centroid'] == [1.0, 0.0, 0.0]
    assert result['summary']['radius_of_gyration'] == 1.0
    assert result['summary']['ca_count'] == 2
    assert result['summary']['water_atom_count'] == 1
    assert any(a['altloc'] == 'B' and a['reason'] == 'alternate_location_not_selected' for a in result['atom_audit'])
    assert any(a['insertion_code'] == 'A' for a in result['atom_audit'])


def test_mmcif_geometry_and_author_label_identity():
    from app.adapters.bio_insights_engine.feature_extract import extract_structure
    cif = '''data_x
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA L 1 1 ? 0 0 0 1 20 10 ALA A CA 1
ATOM 2 C CA . GLY L 1 2 A 2 0 0 1 20 11 GLY A CA 1
#
'''
    result = extract_structure(cif, 'mmcif', model_id=1, chain_id='A')
    assert result['summary']['centroid'] == [1.0, 0.0, 0.0]
    assert result['summary']['radius_of_gyration'] == 1.0
    assert [(a['auth_asym_id'], a['label_asym_id'], a['auth_seq_id'], a['label_seq_id']) for a in result['atom_audit']] == [('A', 'L', '10', '1'), ('A', 'L', '11', '2')]


def test_structure_conserves_all_input_atoms_and_missing_geometry():
    from app.adapters.bio_insights_engine.feature_extract import extract_structure
    text = ('ATOM      1  CA AALA A   1       0.000   0.000   0.000       20.00           C  \n'
            'ATOM      2  CA BALA A   1       2.000   0.000   0.000  0.50 20.00           C  \n'
            'ATOM      3  CA  GLY B   2       8.000   0.000   0.000  1.00 20.00           C  \n'
            'ATOM      4  N   GLY A   2A      3.000   0.000   0.000  1.00 20.00           N  \n')
    result=extract_structure(text,'pdb',model_id=1,chain_id='A')
    assert len(result['atom_audit']) == 4
    assert result['summary']['ca_count']==1
    assert result['summary']['centroid']==[2.,0.,0.]
    assert result['summary']['radius_of_gyration']==0
    assert len(result['residue_audit'])==3
    assert any(a['reason']=='unselected_chain' for a in result['atom_audit'])
    assert any(r['reason']=='no_valid_ca' for r in result['residue_audit'])


def test_native_feature_pipeline_and_annotation_only_recipe(tmp_path):
    import hashlib,json
    from app.adapters.bio_insights_engine.pipeline import run
    from app.domain.bio_insights.feature_contracts import FeatureExtractConfig
    raw=tmp_path/'x.fasta';raw.write_text('>same first\nACGTNN\n>same second\nNN\n>bad\nAC-T\n')
    sha=hashlib.sha256(raw.read_bytes()).hexdigest()
    resource={'kind':'sequence','sequence_type':'dna','species_taxon_id':9606,'namespace':'local','release':'v1','source':{'name':'fixture'},'usage':{'redistribution_allowed':True},'input_files':[{'file_id':'f','sha256':sha,'format':'fasta','role':'fasta','member_key':'feature_input_0'}]}
    doc=tmp_path/'resource.json';doc.write_text(json.dumps(resource))
    def member(path,fmt):return {'path':str(path),'format':fmt,'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    cfg=FeatureExtractConfig(resource_source_ids=['r'],steps=[{'operation':'annotation','annotation_field':'gc_fraction','annotation_operator':'ge','annotation_value':0.4}]).model_dump(mode='json')
    out=tmp_path/'out';out.mkdir()
    result=run({'schema_version':1,'kind':'bio_feature_extract','config':cfg,'identity':{'source_digest':'a'*64},'sources':[{'source_id':'r','source_kind':'bio_resource_version','sha256':'b'*64,'metadata':{'kind':'sequence'},'members':{'resource':member(doc,'json'),'feature_input_0':member(raw,'fasta')}}],'output_directory':str(out)})
    assert result['summary']['feature_count']==2
    assert result['summary']['selected_count']==1
    assert result['summary']['excluded_count']==1
    assert not (out/'comparison_results.tsv').exists()
    import csv
    rows=list(csv.DictReader((out/'feature_results.tsv').open(),delimiter='\t'))
    assert len({r['feature_id'] for r in rows})==2
    bridge=json.loads((out/'resource.json').read_text())
    assert bridge['kind']=='feature_annotation'
    assert all(r['extraction_provenance']=='actual_local_extraction' for r in bridge['annotations'])
    assert result['methods']['geometry_definition']=='equal_weight_protein_CA_Angstrom'


def test_rna_t_encoding_retains_rna_identity_and_rejects_mixed_alphabet():
    rows,excluded=extract_fasta('>RefSeq RNA\nACGTNN\n>mixed\nACGU\n','rna','r',nucleotide_encoding='T')
    assert rows[0]['sequence_type']=='rna' and rows[0]['nucleotide_encoding']=='T'
    assert rows[0]['valid_count']==4 and rows[0]['gc_fraction']==.5
    assert excluded[0]['invalid_symbols']=='U'


def test_feature_resource_import_parent_validation_and_frozen_figures(tmp_path):
    import hashlib,json
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from app.domain.bio_insights.contracts import ResourceImportRequest,FigureConfig
    from app.domain.bio_insights.feature_contracts import FeatureExtractConfig
    raw=tmp_path/'rna.fasta';raw.write_text('>rna\nACGTNN\n>ambiguous\nNN\n')
    sha=hashlib.sha256(raw.read_bytes()).hexdigest()
    source={'source_id':'file','source_kind':'original_file','sha256':sha,'metadata':{},'members':{'original_file':dict(path=str(raw),format='fasta',sha256=sha,size_bytes=raw.stat().st_size)}}
    cfg=ResourceImportRequest(kind='sequence',sequence_type='rna',nucleotide_encoding='T',title='rna',species_taxon_id=9606,namespace='refseq',release='v1',source=dict(institution='test',name='RNA source',description='T-encoded RNA'),usage=dict(basis='fixture',redistribution_allowed=True,scope='project'),files=[dict(file_id='file',sha256=sha,format='fasta',role='fasta')])
    def execute(kind,config,sources,name):
        out=tmp_path/name;out.mkdir();payload=dict(schema_version=1,kind=kind,config=config,identity=dict(source_digest='a'*64,resource_version_id='r'),sources=sources,output_directory=str(out))
        result=run(payload);validate_result(result,out,payload)
        return result,payload
    imported,_=execute('bio_resource_import',cfg.model_dump(mode='json'),[source],'import')
    frozen=dict(source_id='r',source_kind='bio_resource_version',sha256='a'*64,metadata=dict(kind='sequence'),members={m['key']:m for m in imported['outputs']})
    extracted,payload=execute('bio_feature_extract',FeatureExtractConfig(resource_source_ids=['r']).model_dump(mode='json'),[frozen],'extract')
    result_source=dict(source_id='result',source_kind='bio_insight_result_version',sha256='b'*64,metadata=dict(kind='feature_extract'),members={m['key']:m for m in extracted['outputs']})
    figure=FigureConfig(result_source_id='result',figure_type='feature_scatter',x_column='length',y_column='gc_fraction',formats=['png'])
    plotted,_=execute('bio_insight_figure',figure.model_dump(mode='json'),[result_source],'figure')
    plot=json.loads(next(m['path'] for m in plotted['outputs'] if m['key']=='plot_data') and (tmp_path/'figure/plot_data.json').read_text())
    assert len(plot['rows'])==2 and sum(r['displayed'] for r in plot['rows'])==1
    assert plot['analysis_recomputed'] is False
    import copy,pytest
    from app.adapters.bio_feature_validation import validate_feature
    broken=copy.deepcopy(extracted);broken['summary']['input_atom_count']=1
    with pytest.raises(ValueError,match='atom_audit_incomplete'):validate_feature(broken,{m['key']:m for m in extracted['outputs']},payload)


def test_structure_missing_coordinates_invalid_occupancy_and_other_model_audit():
    from app.adapters.bio_insights_engine.feature_extract import extract_structure
    text=('MODEL        1\n'
          'ATOM      1  CA AALA A   1       0.000   0.000   0.000 -0.50 20.00           C  \n'
          'ATOM      2  CA BALA A   1       2.000   0.000   0.000  0.25 20.00           C  \n'
          'ATOM      3  CA  GLY A   2               0.000   0.000  1.00 20.00           C  \n'
          'ENDMDL\nMODEL        2\n'
          'ATOM      1  CA  ALA A   1       9.000   0.000   0.000  1.00 20.00           C  \nENDMDL\n')
    result=extract_structure(text,'pdb',model_id=1,chain_id='A')
    assert len(result['atom_audit'])==4
    assert result['summary']['centroid']==[2.,0.,0.]
    assert result['summary']['ca_count']==1
    assert any(a['reason']=='invalid_coordinates' for a in result['atom_audit'])
    assert any(a['reason']=='unselected_model' for a in result['atom_audit'])
    assert any(a['occupancy_status']=='invalid' for a in result['atom_audit'])
    no_ca=extract_structure('ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N  \n','pdb',model_id=1,chain_id='A')
    assert no_ca['summary']['centroid'] is None and no_ca['summary']['radius_of_gyration'] is None


def test_candidate_consumes_native_feature_annotation_result(tmp_path):
    import hashlib,json
    from app.adapters.bio_insights_engine.candidates import run_candidates
    from app.adapters.bio_engine.manifest import Writer
    from app.domain.bio_insights.contracts import CandidateConfig
    comparison=tmp_path/'comparison.tsv';comparison.write_text('row_key\tfeature_id\tcontrast_id\teffect_value\tq_within_contrast\tnumerator\tdenominator\teffect_name\teffect_unit\nrx\tx\tab\t2\t0.01\tA\tB\tlog2fc\tlog2\nry\ty\tab\t1\t0.03\tA\tB\tlog2fc\tlog2\n')
    annotations=tmp_path/'resource.json';annotations.write_text(json.dumps(dict(kind='feature_annotation',identity_compatible=True,species_taxon_id=9606,namespace='local',annotations=[dict(feature_id='x',field='gc_fraction',value=.5,source='sequence',evidence_status='provided',extraction_provenance='actual_local_extraction')])) )
    def member(path,fmt):return dict(path=str(path),format=fmt,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
    cfg=CandidateConfig(result_source_ids=['comparison'],source_contrasts={'comparison':'ab'},primary_result_source_id='comparison',annotation_source_ids=['features'],steps=[dict(operation='annotation',annotation_field='gc_fraction',annotation_operator='ge',annotation_value=.4)])
    sources=[dict(source_id='comparison',metadata=dict(species_taxon_id=9606,namespace='local',reference_version='1',provenance='system_computed'),members={'comparison_results':member(comparison,'tsv')}),dict(source_id='features',metadata={'kind':'feature_extract'},members={'resource':member(annotations,'json')})]
    out=tmp_path/'out';out.mkdir();result=run_candidates(dict(config=cfg.model_dump(mode='json'),sources=sources,identity={'source_digest':'a'*64}),Writer(out))
    assert result['summary']['candidate_count']==1
    assert json.loads((out/'candidate_sets.json').read_text())['selected']==['x']


def test_fasta_non_ascii_symbols_keep_original_length_and_are_excluded():
    for symbol in ('ß', 'ı', 'ſ', '\u0085', '\u2028'):
        rows, excluded = extract_fasta('>x\nA' + symbol + '\n', 'protein', 'v')
        assert rows == []
        assert len(excluded) == 1
        assert excluded[0]['length'] == 2
        assert excluded[0]['reason'] == 'invalid_symbol'
        assert excluded[0]['invalid_symbols'] == symbol
    rows, excluded = extract_fasta('>ascii\na c\tD\r\n', 'protein', 'v')
    assert not excluded and rows[0]['length'] == rows[0]['standard_count'] == 3


def test_pdb_nonpolymer_amino_acid_is_excluded_from_counts_and_geometry():
    from app.adapters.bio_insights_engine.feature_extract import extract_structure
    text = ('ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \n'
            'HETATM    2  CA  ALA A   2      10.000   0.000   0.000  1.00 20.00           C  \n')
    result = extract_structure(text, 'pdb', model_id=1, chain_id='A')
    summary = result['summary']
    assert summary['observed_residue_count'] == summary['atom_count'] == summary['ca_count'] == 1
    assert summary['nonpolymer_atom_count'] == 1
    assert summary['centroid'] == [0., 0., 0.] and summary['radius_of_gyration'] == 0
    assert any(w['code'] == 'single_ca_geometry_insufficient' for w in result['warnings'])
    atom = result['atom_audit'][1]
    residue = result['residue_audit'][1]
    assert atom['polymer'] is atom['protein'] is atom['geometry_included'] is False
    assert atom['reason'] == residue['reason'] == 'nonpolymer'
    assert residue['polymer'] is residue['protein'] is False and residue['ca_count'] == 0


def test_pdb_modres_polymer_assignment_matches_full_author_residue_identity():
    from app.adapters.bio_insights_engine.feature_extract import extract_structure
    # wwPDB MODRES columns: resName 13-15, chain 17, seq 19-22, iCode 23, stdRes 25-27.
    modres = 'MODRES 1ABC MSE A    2A MET  SELENOMETHIONINE\n'
    text = (modres +
            'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \n'
            'HETATM    2  CA  MSE A   2A      2.000   0.000   0.000  1.00 20.00           C  \n'
            'HETATM    3  CA  MSE A   2      10.000   0.000   0.000  1.00 20.00           C  \n'
            'HETATM    4  CA  ALA A   2A     12.000   0.000   0.000  1.00 20.00           C  \n'
            'HETATM    5  CA  MSE A   3A     14.000   0.000   0.000  1.00 20.00           C  \n'
            'HETATM    6  CA  MSE B   2A     16.000   0.000   0.000  1.00 20.00           C  \n')
    result = extract_structure(text, 'pdb', model_id=1, chain_id='A')
    assert result['summary']['ca_count'] == 2
    assert result['summary']['nonpolymer_atom_count'] == 3
    assert result['summary']['centroid'] == [1., 0., 0.] and result['summary']['radius_of_gyration'] == 1.
    atoms = result['atom_audit']
    assert atoms[1]['geometry_included'] and atoms[1]['polymer_basis'] == 'pdb_MODRES'
    assert atoms[1]['modres_standard_residue'] == 'MET'
    assert (atoms[1]['auth_asym_id'], atoms[1]['auth_seq_id'], atoms[1]['insertion_code'], atoms[1]['residue_name']) == ('A', '2', 'A', 'MSE')
    assert all(a['polymer'] is False and not a['geometry_included'] for a in atoms[2:])


def test_parent_rejects_nonpolymer_atom_marked_for_geometry(tmp_path):
    import csv, hashlib, json
    import pytest
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_feature_validation import validate_feature
    from app.domain.bio_insights.feature_contracts import FeatureExtractConfig
    raw = tmp_path/'x.pdb'
    raw.write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \n')
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    resource = dict(kind='structure', structure_origin='experimental', species_taxon_id=9606, namespace='local', release='1', source={'name':'fixture'}, input_files=[dict(file_id='f', sha256=sha, format='pdb', role='pdb', member_key='feature_input_0')])
    doc = tmp_path/'resource.json'; doc.write_text(json.dumps(resource))
    def member(path, fmt):
        return dict(path=str(path), format=fmt, size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    config = FeatureExtractConfig(resource_source_ids=['r'], structure_selections=[dict(resource_source_id='r', model_id=1, chain_id='A')]).model_dump(mode='json')
    out = tmp_path/'out'; out.mkdir()
    payload = dict(schema_version=1, kind='bio_feature_extract', config=config, identity={'source_digest':'a'*64}, sources=[dict(source_id='r', source_kind='bio_resource_version', sha256='b'*64, metadata={'kind':'structure'}, members={'resource':member(doc,'json'), 'feature_input_0':member(raw,'pdb')})], output_directory=str(out))
    result = run(payload); items = {m['key']:m for m in result['outputs']}
    validate_feature(result, items, payload)
    audit = out/'feature_atom_audit.tsv'
    with audit.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle, delimiter='\t'); columns = reader.fieldnames; atoms = list(reader)
    atoms[0]['polymer'] = 'False'
    with audit.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter='\t'); writer.writeheader(); writer.writerows(atoms)
    with pytest.raises(ValueError, match='feature_nonpolymer_geometry'):
        validate_feature(result, items, payload)
    assert 'MODRES' in result['methods']['pdb_polymer_assignment']
