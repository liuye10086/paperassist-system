"""Bounded, source-preserving sequence feature extraction."""
from collections import Counter

STANDARD_AMINO_ACIDS = 'ACDEFGHIKLMNPQRSTVWY'
NUCLEOTIDES = {'dna': 'ACGT', 'rna': 'ACGU'}
AMBIGUOUS = {'dna': set('RYSWKMBDHVN'), 'rna': set('RYSWKMBDHVN')}


def extract_fasta(text, sequence_type, resource_version_id, nucleotide_encoding=None):
    """Return extracted records and exclusions; IDs use version and record ordinal.

    Sequence-line ASCII whitespace is ignored and ASCII lowercase is uppercased.
    Original headers remain untouched. Non-IUPAC symbols cause record exclusion.
    """
    if sequence_type not in ('dna', 'rna', 'protein'):
        raise ValueError('explicit_sequence_type_required')
    if nucleotide_encoding is not None and (sequence_type not in ('dna','rna') or nucleotide_encoding not in ('T','U') or sequence_type=='dna' and nucleotide_encoding!='T'):raise ValueError('nucleotide_encoding_mismatch')
    alphabet='ACG'+(nucleotide_encoding or ('U' if sequence_type=='rna' else 'T'))
    records = []
    header = None
    parts = []
    total = 0
    for line in text.split('\n'):
        if line.startswith('>'):
            if header is not None:
                records.append((header, ''.join(parts)))
            header, parts = line[1:], []
            if not header.strip():
                raise ValueError('fasta_empty_header')
            if len(records) >= 10000:
                raise ValueError('fasta_record_limit')
        else:
            if header is None:
                if line.strip(' \t\r\n\v\f'):
                    raise ValueError('fasta_header_required')
                continue
            sequence = ''.join(c for c in line if c not in ' \t\r\n\v\f').translate(
                str.maketrans('abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
            total += len(sequence)
            if total > 10_000_000:
                raise ValueError('fasta_character_limit')
            parts.append(sequence)
    if header is not None:
        records.append((header, ''.join(parts)))
    if not records:
        raise ValueError('fasta_no_records')
    rows, exclusions = [], []
    for ordinal, (header, sequence) in enumerate(records, 1):
        original_id = header.split()[0]
        identity = dict(feature_id=f'{resource_version_id}:{ordinal}', record_ordinal=ordinal,
                        original_id=original_id, original_title=header, sequence_type=sequence_type,nucleotide_encoding=(alphabet[-1] if sequence_type!='protein' else None))
        allowed = set(STANDARD_AMINO_ACIDS + 'BJOUXZ*') if sequence_type == 'protein' else set(alphabet) | AMBIGUOUS[sequence_type]
        invalid = sorted(set(sequence) - allowed)
        if not sequence or invalid:
            exclusions.append({**identity, 'reason': 'empty_sequence' if not sequence else 'invalid_symbol',
                               'invalid_symbols': ''.join(invalid), 'length': len(sequence)})
            continue
        counts = Counter(sequence)
        length = len(sequence)
        row = {**identity, 'length': length}
        if sequence_type == 'protein':
            standard_count = sum(counts[aa] for aa in STANDARD_AMINO_ACIDS)
            row.update(standard_count=standard_count, standard_fraction=standard_count / length,
                       amino_acid_counts={aa: counts[aa] for aa in STANDARD_AMINO_ACIDS},
                       composition={aa: counts[aa] / standard_count if standard_count else None for aa in STANDARD_AMINO_ACIDS},
                       nonstandard_count=sum(counts[aa] for aa in 'BJOUXZ'),
                       nonstandard_counts={aa: counts[aa] for aa in 'BJOUXZ'},
                       stop_count=counts['*'], stop_positions=[i for i, aa in enumerate(sequence, 1) if aa == '*'])
        else:
            valid_count = sum(counts[base] for base in alphabet)
            row.update(valid_count=valid_count, base_counts={base: counts[base] for base in alphabet},
                       ambiguous_count=length-valid_count, ambiguous_fraction=(length-valid_count)/length,
                       gc_fraction=(counts['G']+counts['C'])/valid_count if valid_count else None)
        rows.append(row)
    return rows, exclusions


def _structure_atoms(text, format):
    """Lossless atom-site projection. Missing values remain audited, never dropped.

    PDB fixed columns are read directly; Biopython's strict mmCIF token parser
    reads the entire atom_site loop. We do not use StructureBuilder, whose
    missing occupancy/author residue cases can reject or omit input atoms.
    """
    import io,math
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    from Bio.PDB.Polypeptide import is_aa
    def number(raw):
        try:
            x=float(raw)
            return x if math.isfinite(x) else None
        except (ValueError,TypeError):return None
    atoms=[]
    if format=='pdb':
        modres={}
        model=1;explicit=False;seen_models=set();inside=True
        for line_number,line in enumerate(text.splitlines(),1):
            tag=line[:6].strip()
            if tag=='MODRES':
                # wwPDB fixed columns; preserve the complete author identity.
                parent=line[24:27].strip()
                if line[12:15].strip() and line[18:22].strip() and is_aa(parent,standard=True):
                    modres[(line[16:17],line[18:22].strip(),line[22:23].strip(),line[12:15].strip())]=parent
            elif tag=='MODEL':
                model=int(line[10:14]);explicit=True;inside=True
                if model<1 or model in seen_models:raise ValueError('duplicate_or_invalid_model')
                seen_models.add(model)
            elif tag=='ENDMDL':inside=False
            elif tag in ('ATOM','HETATM'):
                if explicit and not inside:raise ValueError('atom_outside_model')
                if len(line)<54:raise ValueError('truncated_pdb_atom_identity')
                serial=line[6:11].strip();residue=line[22:26].strip()
                if not serial or not residue or not line[12:16].strip() or not line[17:20].strip():raise ValueError('structure_atom_identity_missing')
                atoms.append(dict(input_row=line_number,model_id=model,chain_id=line[21:22],residue_number=residue,
                    insertion_code=line[26:27].strip(),residue_name=line[17:20].strip(),record_type=tag,
                    atom_name=line[12:16].strip(),atom_serial=serial,altloc=line[16:17].strip(),
                    coordinates=[number(line[a:b].strip()) for a,b in ((30,38),(38,46),(46,54))],
                    occupancy=number(line[54:60].strip()),raw_occupancy=line[54:60].strip(),
                    auth_asym_id=line[21:22],auth_seq_id=residue,auth_atom_id=line[12:16].strip(),auth_comp_id=line[17:20].strip(),
                    label_asym_id=None,label_seq_id=None,label_atom_id=None,label_comp_id=None,label_entity_id=None))
    elif format=='mmcif':
        data=MMCIF2Dict(io.StringIO(text));columns={k[11:]:v for k,v in data.items() if k.startswith('_atom_site.')}
        required={'id','group_PDB','label_atom_id','label_comp_id','label_asym_id','label_seq_id','Cartn_x','Cartn_y','Cartn_z','auth_asym_id','auth_seq_id'}
        if not required<=columns.keys():raise ValueError('mmcif_required_identity_columns_missing')
        n=len(columns['id'])
        if any(not isinstance(v,list) or len(v)!=n for v in columns.values()):raise ValueError('mmcif_atom_columns_inconsistent')
        def cell(name,i,default=None):return columns[name][i] if name in columns else default
        def clean(x):return None if x in ('.','?',None) else x
        for i in range(n):
            if cell('group_PDB',i) not in ('ATOM','HETATM'):raise ValueError('unknown_atom_record')
            auth_chain=clean(cell('auth_asym_id',i));auth_seq=clean(cell('auth_seq_id',i))
            label_chain=clean(cell('label_asym_id',i));label_seq=clean(cell('label_seq_id',i))
            # No author/label guessing: unresolved author identity is retained
            # in the complete audit and cannot match an author-chain selection.
            atoms.append(dict(input_row=i+1,model_id=int(cell('pdbx_PDB_model_num',i,'1')),
                chain_id=auth_chain,residue_number=auth_seq,insertion_code=clean(cell('pdbx_PDB_ins_code',i)) or '',
                residue_name=clean(cell('auth_comp_id',i)) or cell('label_comp_id',i),record_type=cell('group_PDB',i),
                atom_name=clean(cell('auth_atom_id',i)) or cell('label_atom_id',i),atom_serial=cell('id',i),
                altloc=clean(cell('label_alt_id',i)) or '',coordinates=[number(cell(k,i)) for k in ('Cartn_x','Cartn_y','Cartn_z')],
                occupancy=number(cell('occupancy',i)),raw_occupancy=cell('occupancy',i),
                auth_asym_id=auth_chain,auth_seq_id=auth_seq,auth_atom_id=clean(cell('auth_atom_id',i)),auth_comp_id=clean(cell('auth_comp_id',i)),
                label_asym_id=label_chain,label_seq_id=label_seq,label_atom_id=cell('label_atom_id',i),label_comp_id=cell('label_comp_id',i),label_entity_id=clean(cell('label_entity_id',i))))
    else:raise ValueError('unsupported_structure_format')
    if not atoms or len(atoms)>100000:raise ValueError('structure_atom_limit_or_empty')
    serials=set();identities=set()
    for atom in atoms:
        serial=(atom['model_id'],atom['atom_serial'])
        key=tuple(atom[k] for k in ('model_id','chain_id','residue_number','insertion_code','residue_name','record_type','atom_name','altloc','label_asym_id','label_seq_id'))
        if serial in serials or key in identities:raise ValueError('duplicate_atom_identity')
        serials.add(serial);identities.add(key)
        atom['water']=atom['residue_name'] in ('HOH','WAT','DOD')
        parent=modres.get(tuple(atom[k] for k in ('chain_id','residue_number','insertion_code','residue_name'))) if format=='pdb' else None
        atom['polymer']=not atom['water'] and (atom['record_type']=='ATOM' or parent is not None if format=='pdb' else atom['label_seq_id'] is not None)
        atom['protein']=atom['polymer'] and (is_aa(atom['residue_name'],standard=False) or parent is not None)
        atom['polymer_basis']=('water' if atom['water'] else 'pdb_ATOM' if atom['record_type']=='ATOM' else 'pdb_MODRES' if parent is not None else 'pdb_HETATM_unproven') if format=='pdb' else ('mmcif_label_seq_id' if atom['polymer'] else 'mmcif_no_label_seq_id')
        atom['modres_standard_residue']=parent
        atom['occupancy_status']='valid' if atom['occupancy'] is not None and 0<=atom['occupancy']<=1 else 'missing' if atom['raw_occupancy'] in ('','?','.',None) else 'invalid'
    return atoms


def extract_structure(text, format, *, model_id, chain_id):
    import math
    from collections import defaultdict
    atoms=_structure_atoms(text,format)
    if not any(a['model_id']==model_id and a['chain_id']==chain_id for a in atoms):raise ValueError('selected_model_or_chain_missing')
    groups=defaultdict(list);residues=defaultdict(list)
    for a in atoms:
        key=tuple(a[k] for k in ('model_id','chain_id','residue_number','insertion_code','residue_name','record_type','label_asym_id','label_seq_id'))
        residues[key].append(a);groups[key+(a['atom_name'],)].append(a)
    def ordering(a):
        alt=a['altloc'];valid=a['occupancy_status']=='valid'
        return (0 if valid else 1,-a['occupancy'] if valid else 0,0 if not alt else 1 if alt=='A' else 2,alt)
    chosen={id(min(values,key=ordering)) for values in groups.values()}
    coordinates=[];warnings=[]
    for a in atoms:
        selected=id(a) in chosen;valid_xyz=all(v is not None for v in a['coordinates'])
        reason=('unselected_model' if a['model_id']!=model_id else 'unselected_chain' if a['chain_id']!=chain_id else
            'missing_author_residue_identity' if a['residue_number'] is None else 'alternate_location_not_selected' if not selected else
            'water' if a['water'] else 'nonpolymer' if not a['polymer'] else 'non_protein' if not a['protein'] else 'invalid_coordinates' if not valid_xyz else 'selected')
        a.update(selected=selected and a['model_id']==model_id and a['chain_id']==chain_id,reason=reason,
            geometry_included=reason=='selected' and a['atom_name']=='CA')
        if a['geometry_included']:coordinates.append(a['coordinates'])
        if a['occupancy_status']!='valid':warnings.append(dict(input_row=a['input_row'],code='occupancy_'+a['occupancy_status']))
        if not valid_xyz:warnings.append(dict(input_row=a['input_row'],code='invalid_coordinates'))
        if a['chain_id'] is None or a['residue_number'] is None:warnings.append(dict(input_row=a['input_row'],code='missing_author_identity'))
    residue_audit=[]
    for values in residues.values():
        first=values[0];in_scope=first['model_id']==model_id and first['chain_id']==chain_id
        n=sum(a['geometry_included'] for a in values)
        reason='unselected_model' if first['model_id']!=model_id else 'unselected_chain' if not in_scope else 'water' if first['water'] else 'nonpolymer' if not first['polymer'] else 'non_protein' if not first['protein'] else 'no_valid_ca' if not n else 'selected'
        residue_audit.append({k:first[k] for k in ('model_id','chain_id','residue_number','insertion_code','residue_name','auth_asym_id','auth_seq_id','label_asym_id','label_seq_id','polymer_basis','modres_standard_residue')}|
            dict(input_atom_count=len(values),selected_atom_count=sum(a['selected'] for a in values),ca_count=n,reason=reason,protein=first['protein'],polymer=first['polymer']))
    scoped=[a for a in atoms if a['selected']];n=len(coordinates)
    centroid=[sum(x[j] for x in coordinates)/n for j in range(3)] if n else None
    rg=math.sqrt(sum(sum((x[j]-centroid[j])**2 for j in range(3)) for x in coordinates)/n) if n else None
    if n<2:warnings.append(dict(input_row=None,code='no_valid_ca' if not n else 'single_ca_geometry_insufficient'))
    return dict(summary=dict(model_id=model_id,chain_id=chain_id,observed_residue_count=sum(r['protein'] and r['reason'] in ('selected','no_valid_ca') for r in residue_audit),
        atom_count=sum(a['protein'] for a in scoped),ca_count=n,water_atom_count=sum(a['water'] for a in scoped),
        nonpolymer_atom_count=sum(not a['polymer'] and not a['water'] for a in scoped),
        other_polymer_atom_count=sum(a['polymer'] and not a['protein'] for a in scoped),input_atom_count=len(atoms),
        centroid=centroid,radius_of_gyration=rg),atom_audit=atoms,residue_audit=residue_audit,warnings=warnings)


def run_feature_extract(payload,writer):
    import hashlib
    from .inputs import document
    from .resources import text_lines
    from .candidates import apply_recipe
    from app.domain.bio_insights.feature_contracts import FeatureExtractConfig
    config=FeatureExtractConfig.model_validate(payload['config']);sources={s['source_id']:s for s in payload['sources']}
    selections={s.resource_source_id:s for s in config.structure_selections}
    rows=[];excluded=[];atoms=[];residues=[];warnings=[];origins=[];total_chars=total_sequences=total_atoms=0
    for sid in config.resource_source_ids:
        source=sources[sid];resource=document(source['members']['resource'])
        if resource['kind'] not in ('sequence','structure'):raise ValueError('feature_input_resource_required')
        if len(resource['input_files'])!=1:raise ValueError('one_feature_file_per_resource')
        spec=resource['input_files'][0];member=source['members'][spec['member_key']]
        if member['sha256']!=spec['sha256']:raise ValueError('feature_input_sha_changed')
        text='\n'.join(text_lines(member,spec['format'],budget=268435456))
        origin=dict(resource_version_id=sid,input_sha256=spec['sha256'],file_id=spec['file_id'],species_taxon_id=resource['species_taxon_id'],namespace=resource['namespace'],reference_version=resource['release'],structure_origin=resource.get('structure_origin'),sequence_type=resource.get('sequence_type'),nucleotide_encoding=resource.get('nucleotide_encoding'),source=resource['source'])
        origins.append(origin)
        if resource['kind']=='sequence':
            if sid in selections:raise ValueError('structure_selection_on_sequence')
            extracted,errors=extract_fasta(text,resource['sequence_type'],sid,resource.get('nucleotide_encoding'))
            total_sequences+=len(extracted)+len(errors);total_chars+=sum(r['length'] for r in extracted+errors)
            for row in extracted:
                for group in ('base_counts','amino_acid_counts','composition','nonstandard_counts'):
                    for key,value in row.pop(group,{}).items():row[group+'_'+key]=value
                rows.append({**origin,**row,'feature_kind':resource['sequence_type']})
            excluded.extend({**origin,**r} for r in errors)
        else:
            if sid not in selections:raise ValueError('explicit_structure_selection_required')
            choice=selections[sid];result=extract_structure(text,spec['format'].removesuffix('.gz'),model_id=choice.model_id,chain_id=choice.chain_id)
            fid=f'{sid}:{choice.model_id}:{choice.chain_id}';summary=result['summary'];centroid=summary.pop('centroid')
            rows.append({**origin,**summary,'feature_id':fid,'original_id':choice.chain_id,'feature_kind':'structure',**{f'centroid_{axis}':centroid[i] if centroid else None for i,axis in enumerate('xyz')}})
            atoms.extend({**origin,'feature_id':fid,**a} for a in result['atom_audit']);residues.extend({**origin,'feature_id':fid,**r} for r in result['residue_audit'])
            warnings.extend({**origin,'feature_id':fid,**w} for w in result['warnings']);total_atoms+=summary['input_atom_count']
            excluded.extend({**origin,'feature_id':fid,**r} for r in result['residue_audit'] if r['reason']!='selected')
        if total_sequences>10000 or total_chars>10000000 or total_atoms>100000:raise ValueError('feature_task_budget_exceeded')
    fields=sorted(set(['length','valid_count','ambiguous_count','ambiguous_fraction','gc_fraction','standard_count','standard_fraction','nonstandard_count','stop_count','observed_residue_count','atom_count','ca_count','water_atom_count','nonpolymer_atom_count','other_polymer_atom_count','input_atom_count','radius_of_gyration','centroid_x','centroid_y','centroid_z']+[f'base_counts_{b}' for b in 'ACGTU']+[f'{group}_{aa}' for group in ('amino_acid_counts','composition') for aa in STANDARD_AMINO_ACIDS]+[f'nonstandard_counts_{aa}' for aa in 'BJOUXZ']))
    annotations={r['feature_id']:{k:{'value':r.get(k)} for k in fields} for r in rows}
    for step in config.steps:
        if step.operation=='annotation' and step.annotation_field not in fields:raise ValueError('unknown_extracted_feature_field')
    if config.rank_field is not None and config.rank_field not in fields:raise ValueError('unknown_extracted_rank_field')
    recipe=apply_recipe({'features':{r['feature_id']:r for r in rows}},[s.model_dump(mode='json') for s in config.steps],annotations)
    selected=set(recipe['selected'])
    def rank(r):
        value=r.get(config.rank_field) if config.rank_field else None
        return (value is None,(-value if config.rank_direction=='descending' else value) if value is not None else 0,r['feature_id'])
    ranked=sorted((r for r in rows if r['feature_id'] in selected),key=rank)
    for i,r in enumerate(ranked,1):r['rank']=i
    for r in rows:r.update(row_key=hashlib.sha256(r['feature_id'].encode()).hexdigest(),selected=r['feature_id'] in selected,extraction_provenance='actual_local_extraction')
    def table(key,items,minimum):
        import json
        for row in items:
            row.setdefault('row_key',hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest())
        writer.table(key,items,list(dict.fromkeys(['row_key']+minimum+sorted({k for r in items for k in r}))))
    table('feature_results',rows,['row_key','feature_id','original_id','feature_kind','selected','rank','extraction_provenance'])
    table('feature_candidates',ranked,['row_key','feature_id','rank'])
    table('feature_exclusions',excluded,['feature_id','reason','resource_version_id','input_sha256'])
    table('feature_atom_audit',atoms,['feature_id','input_row','model_id','chain_id','residue_number','atom_serial','reason','geometry_included','coordinates'])
    table('feature_residue_audit',residues,['feature_id','model_id','chain_id','residue_number','reason'])
    table('feature_warnings',warnings,['feature_id','input_row','code'])
    table('feature_filter_steps',recipe['steps'],['step','operation','before_count','after_count','removed_count','parameters'])
    table('feature_filter_exclusions',recipe['exclusions'],['step','feature_id','reason'])
    table('feature_missing_requested',recipe['missing_requested_features'],['step','feature_id','reason'])
    # Candidate annotations use original IDs only when unique; internal record
    # keys always remain distinct even for duplicated FASTA identifiers.
    from collections import Counter
    counts=Counter((r['namespace'],r['original_id']) for r in rows);bridge=[];bridge_exclusions=[]
    identities={tuple(o[k] for k in ('species_taxon_id','namespace','reference_version')) for o in origins}
    for r in rows:
        if counts[(r['namespace'],r['original_id'])]!=1:
            bridge_exclusions.append(dict(feature_id=r['feature_id'],original_id=r['original_id'],reason='ambiguous_original_id'));continue
        for field in fields:
            if field not in r:continue
            value=r.get(field)
            bridge.append(dict(feature_id=r['original_id'],record_feature_id=r['feature_id'],field=field,value=value,value_type='number',unit='Angstrom' if field.startswith('centroid_') or field=='radius_of_gyration' else '',source=r['resource_version_id'],evidence_status='unknown' if value is None else 'provided',extraction_provenance='actual_local_extraction',input_sha256=r['input_sha256']))
    identity=next(iter(identities)) if len(identities)==1 else (None,None,None)
    writer.json('resource',dict(kind='feature_annotation',species_taxon_id=identity[0],namespace=identity[1],release=identity[2],annotations=bridge,identity_compatible=len(identities)==1,extraction_provenance='actual_local_extraction'))
    table('feature_annotation_exclusions',bridge_exclusions,['feature_id','original_id','reason'])
    writer.json('feature_data',dict(rows=rows,fields=fields,origins=origins))
    methods=dict(recipe=config.model_dump(mode='json'),geometry_definition='equal_weight_protein_CA_Angstrom',geometry_formula='c=sum(x)/n; Rg=sqrt(sum(||x-c||^2)/n)',
        parser='lossless_PDB_fixed_columns_or_Biopython_MMCIF2Dict_atom_site_v1',altloc='highest valid occupancy; missing/invalid last; ties blank,A,lexical',
        pdb_polymer_assignment='ATOM establishes polymer; HETATM requires exact MODRES author chain/residue number/insertion code/residue name with standard amino-acid parent; unmatched HETATM membership unproven and excluded; no chemical or SEQRES inference',
        fasta_normalization='ASCII whitespace removed; ASCII lowercase to uppercase only; non-ASCII retained for invalid-symbol exclusion with original character length; original headers and input bytes preserved',nucleotide_denominator='A/C/G/T or A/C/G/U only; all ambiguous GC=NA',
        protein_denominator='standard 20 residues; nonstandard and stops audited separately',inference='descriptive_features_only_no_P_values_no_structure_prediction',
        rank_unknown='last; stable feature ID tie break',sources=origins,species_taxon_id=identity[0],namespace=identity[1],reference_version=identity[2],annotation_bridge='unique original IDs only; mixed identity requires separate extraction plans for candidate reuse')
    return dict(summary=dict(feature_count=len(rows),selected_count=len(ranked),excluded_count=len(excluded),warning_count=len(warnings),input_sequence_count=total_sequences,input_atom_count=total_atoms,species_taxon_id=identity[0],namespace=identity[1]),methods=methods,inference_scope='derived',provenance='system_computed')
