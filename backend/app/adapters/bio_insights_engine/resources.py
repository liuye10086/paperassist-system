"""Offline, versioned biological resources. Input bytes never execute code."""
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import io
import math
from pathlib import Path
import re

ROOT_TERMS = {'GO:0008150', 'GO:0003674', 'GO:0005575'}
MAX_ROWS = 10_000_000
MAX_TERMS = 50_000
MAX_GENES = 100_000
MAX_RELATIONS = 5_000_000


def text_lines(member, fmt, budget=536870912, *, expected_size=None, totals=None):
    path = Path(member['path'])
    if path.is_symlink() or not path.is_file() or path.stat().st_size != member['size_bytes']:
        raise ValueError('resource_file_identity_changed')
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):sha.update(chunk)
    if sha.hexdigest() != member['sha256']:raise ValueError('resource_file_identity_changed')
    opener = gzip.open if fmt.endswith('.gz') else open
    total = 0
    with opener(path, 'rb') as stream:
        for number in range(MAX_ROWS + 1):
            raw = stream.readline(1024**2 + 1)
            if not raw:break
            total += len(raw)
            if totals is not None:
                totals[0]+=len(raw)
                if totals[0]>2*1024**3:raise ValueError('resource_total_expansion_budget_exceeded')
            if number == MAX_ROWS or len(raw) > 1024**2 or total > budget:
                raise ValueError('resource_expansion_budget_exceeded')
            line = raw.decode('utf-8-sig' if number == 0 else 'utf-8').rstrip('\r\n')
            if '\x00' in line:raise ValueError('resource_nul_byte')
            yield line
    if expected_size is not None and total!=expected_size:raise ValueError('resource_expansion_size_mismatch')


def _identifier(value):
    if not isinstance(value, str) or not value or len(value)>200 or re.search(r'[\x00-\x20]',value):
        raise ValueError('invalid_resource_identifier')
    return value


def parse_obo(lines):
    terms, aliases, header = {}, {}, {}
    stanza, current = None, {}
    def save():
        if stanza != 'Term':return
        identifier = _identifier(current.get('id'))
        if identifier in terms or len(terms)>=100_000:raise ValueError('duplicate_or_excess_terms')
        terms[identifier] = dict(term_id=identifier, name=current.get('name',identifier),
            namespace=current.get('namespace','unknown'), obsolete=current.get('is_obsolete')=='true',
            parents=current.get('parents',[]), alt_ids=current.get('alt_ids',[]),
            subsets=current.get('subsets',[]))
    for line in lines:
        line=line.strip()
        if not line or line.startswith('!'):continue
        if line.startswith('[') and line.endswith(']'):
            save(); stanza=line[1:-1];current={};continue
        if ': ' not in line:raise ValueError('invalid_obo_line')
        key,value=line.split(': ',1)
        if stanza is None:header[key]=value;continue
        if stanza!='Term':continue
        if key=='is_a':current.setdefault('parents',[]).append(('is_a',value.split()[0]))
        elif key=='relationship':
            parts=value.split()
            if len(parts)<2:raise ValueError('invalid_obo_relationship')
            if parts[0] in ('is_a','part_of'):current.setdefault('parents',[]).append((parts[0],parts[1]))
        elif key=='alt_id':current.setdefault('alt_ids',[]).append(value)
        elif key=='subset':current.setdefault('subsets',[]).append(value)
        elif key in ('id','name','namespace','is_obsolete'):
            if key in current and current[key]!=value:raise ValueError('conflicting_obo_field')
            current[key]=value
    save()
    if not terms or header.get('format-version') not in ('1.2','1.4'):
        raise ValueError('invalid_obo_header')
    for identifier,term in terms.items():
        for alt in term['alt_ids']:
            _identifier(alt)
            if alt in terms or alt in aliases and aliases[alt]!=identifier:raise ValueError('conflicting_obo_alt_id')
            aliases[alt]=identifier
    # Validate the only propagation graph we support, even for unused terms.
    visiting, visited = set(), set()
    def visit(identifier, depth=0):
        if identifier in visiting or depth>256:raise ValueError('ontology_cycle_or_depth')
        if identifier in visited:return
        visiting.add(identifier)
        for _,parent in terms[identifier]['parents']:
            parent=aliases.get(parent,parent)
            if parent not in terms:raise ValueError('ontology_parent_missing')
            visit(parent,depth+1)
        visiting.remove(identifier);visited.add(identifier)
    for identifier in terms:visit(identifier)
    return dict(terms=terms,aliases=aliases,header=header)


def parse_gaf(lines, ontology, species_taxon_id, evidence_codes=None, relations=('is_a','part_of'), namespace=None):
    if not set(relations)<={'is_a','part_of'}:raise ValueError('unsupported_propagation_relation')
    terms,aliases=ontology['terms'],ontology['aliases']
    memberships={key:set() for key,term in terms.items() if not term['obsolete'] and key not in ROOT_TERMS}
    if len(memberships)>MAX_TERMS:raise ValueError('term_count_limit')
    stats=Counter();exclusions=[];seen=set();ancestors={};header={};version=None;genes=set();relation_count=0
    def closure(identifier):
        if identifier not in ancestors:
            result={identifier}
            for relation,parent in terms[identifier]['parents']:
                parent=aliases.get(parent,parent)
                if relation in relations and not terms[parent]['obsolete']:result.update(closure(parent))
            ancestors[identifier]=result
        return ancestors[identifier]
    for number,line in enumerate(lines,1):
        if not line:continue
        if line.startswith('!'):
            if ': ' in line:
                key,value=line[1:].split(': ',1);header[key]=value
                if key=='gaf-version':
                    if value!='2.2' or version and version!=value:raise ValueError('unsupported_gaf_version')
                    version=value
            continue
        if version!='2.2':raise ValueError('gaf_header_required')
        cells=line.split('\t')
        if len(cells)!=17:raise ValueError('invalid_gaf_column_count')
        db,gene,_,qualifier,original,_,evidence,_,_,_,_,_,taxon,_,_,_,_=cells
        _identifier(gene);_identifier(original)
        stats['input_annotations']+=1
        term=aliases.get(original,original)
        reason=None
        if 'NOT' in qualifier.split('|'):reason='not_qualifier'
        # The first taxon is the annotated entity; a second interacting taxon
        # never turns a different organism into a matching entity.
        elif taxon.split('|')[0] != 'taxon:'+str(species_taxon_id):reason='wrong_species'
        elif term not in terms:reason='unknown_term'
        elif terms[term]['obsolete']:reason='obsolete_term'
        elif evidence_codes and evidence not in evidence_codes:reason='evidence_excluded'
        if reason:
            stats[reason]+=1;exclusions.append(dict(row_number=number,feature_id=gene,term_id=original,reason=reason));continue
        if namespace is not None and db!=namespace:raise ValueError('gaf_namespace_mismatch')
        genes.add(gene)
        if len(genes)>MAX_GENES:raise ValueError('resource_gene_limit')
        if original!=term:stats['alt_id_resolved']+=1
        key=(db,gene,term)
        if key in seen:stats['duplicate_annotations']+=1;continue
        seen.add(key);stats['accepted_annotations']+=1
        for ancestor in closure(term):
            if ancestor in memberships and gene not in memberships[ancestor]:
                memberships[ancestor].add(gene);relation_count+=1
                if relation_count>MAX_RELATIONS:raise ValueError('resource_relation_limit')
    if version!='2.2':raise ValueError('gaf_header_required')
    declared=re.search(r'releases/(\d{4}-\d{2}-\d{2})',header.get('go-version',''))
    ontology_release=re.search(r'releases/(\d{4}-\d{2}-\d{2})',ontology['header'].get('data-version',''))
    if declared and (not ontology_release or declared.group(1)!=ontology_release.group(1)):
        raise ValueError('gaf_ontology_release_mismatch')
    result=[dict(term_id=key,name=terms[key]['name'],namespace=terms[key]['namespace'],
                 subsets=terms[key]['subsets'],genes=sorted(values)) for key,values in sorted(memberships.items())]
    return dict(terms=result,stats=dict(stats),exclusions=exclusions,header=header,
                ontology_header=ontology['header'],gene_identifier='GAF DB Object ID')


def _term_rows(rows):
    terms={};stats=Counter();genes=set();relations=0
    for row in rows:
        term=_identifier(row['term_id']);gene=_identifier(row['feature_id']);name=row.get('term_name') or term
        if len(name)>4000:raise ValueError('term_name_too_long')
        if term in terms and terms[term]['name']!=name:raise ValueError('term_name_conflict')
        value=terms.setdefault(term,dict(term_id=term,name=name,namespace='custom',genes=set()))
        if len(terms)>MAX_TERMS:raise ValueError('term_count_limit')
        stats['input_memberships']+=1
        if gene in value['genes']:stats['duplicate_memberships']+=1
        else:relations+=1
        genes.add(gene)
        if relations>MAX_RELATIONS:raise ValueError('resource_relation_limit')
        if len(genes)>MAX_GENES:raise ValueError('resource_gene_limit')
        value['genes'].add(gene)
    return dict(terms=[{**value,'genes':sorted(value['genes'])} for _,value in sorted(terms.items())],stats=dict(stats),exclusions=[])


def parse_gmt(lines):
    def rows():
        for line in lines:
            if not line or line.startswith('#'):continue
            cells=line.split('\t')
            if len(cells)<3:raise ValueError('invalid_gmt_row')
            for gene in cells[2:]:yield dict(term_id=cells[0],term_name=cells[1] or cells[0],feature_id=gene)
    return _term_rows(rows())


def normalize_mapping(rows,strip_ensembl_version=False):
    mapping=defaultdict(set);originals=[];transformations=[];seen=set();duplicates=0
    for number,row in enumerate(rows,1):
        source=_identifier(row['source_id']);target=_identifier(row['target_id']);original=source
        if strip_ensembl_version:
            source=re.sub(r'^(ENS[A-Z]*[GTP]\d+)\.\d+$',r'\1',source)
        if source!=original:transformations.append(dict(original_id=original,normalized_id=source))
        key=(original,target)
        if key in seen:duplicates+=1
        seen.add(key);mapping[source].add(target)
        originals.append(dict(row_number=number,original_id=original,source_id=source,target_id=target))
    accepted={key:next(iter(values)) for key,values in sorted(mapping.items()) if len(values)==1}
    ambiguous=sorted(key for key,values in mapping.items() if len(values)>1)
    targets=Counter(accepted.values())
    return dict(mapping=accepted,rows=originals,ambiguous_source_ids=ambiguous,
        many_to_one_target_ids=sorted(k for k,v in targets.items() if v>1),transformations=transformations,
        stats=dict(input_rows=len(originals),accepted_source_ids=len(accepted),ambiguous_source_ids=len(ambiguous),
                   duplicate_rows=duplicates,strip_ensembl_version=strip_ensembl_version))


def normalize_annotations(rows):
    result={}
    for row in rows:
        item=dict(row);feature=_identifier(item['feature_id']);field=_identifier(item['field'])
        kind=item['value_type'];raw=item['value'];status=item['evidence_status']
        if kind not in ('number','integer','boolean','string'):raise ValueError('unknown_annotation_value_type')
        if not item.get('source') or status not in ('provided','validated','predicted','unknown','absent'):
            raise ValueError('annotation_provenance_required')
        item['raw_value']=raw
        if status=='unknown':
            if raw not in ('',None):raise ValueError('unknown_annotation_has_value')
            value=None
        elif kind in ('number','integer'):
            value=float(raw)
            if not math.isfinite(value) or kind=='integer' and not value.is_integer():raise ValueError('invalid_annotation_number')
            if kind=='integer':value=int(value)
        elif kind=='boolean':
            if str(raw).lower() not in ('true','false','1','0'):raise ValueError('invalid_annotation_boolean')
            value=str(raw).lower() in ('true','1')
        else:
            if raw is None or len(raw)>10000:raise ValueError('invalid_annotation_text')
            value=raw
        item['value']=value;key=(feature,field)
        if key in result and result[key]!=item:raise ValueError('conflicting_annotation')
        result[key]=item
    return dict(annotations=[value for _,value in sorted(result.items())],stats=dict(annotation_count=len(result)))


def run_resource_import(payload,writer):
    from app.adapters.bio_insights_engine.inputs import iter_table
    if payload['config']['kind'] in ('sample_correspondence','object_correspondence'):
        from .integration import run_correspondence_import
        return run_correspondence_import(payload,writer)
    if payload['config']['kind'] in ('sequence','structure'):
        return run_feature_resource_import(payload,writer)
    config=payload['config'];sources={s['source_id']:s for s in payload['sources']}
    originals=[];ontology=None;gafs=[];term_results=[];tabular=[];totals=[0]
    if sum(sources[spec['file_id']]['members']['original_file']['size_bytes'] for spec in config['files'])>512*1024**2:
        raise ValueError('resource_total_raw_budget_exceeded')
    for spec in config['files']:
        source=sources[spec['file_id']];member=source['members']['original_file']
        if member['sha256']!=spec['sha256']:raise ValueError('resource_source_digest_changed')
        originals.append(dict(file_id=spec['file_id'],sha256=member['sha256'],format=spec['format'],role=spec['role']))
        lines=lambda:text_lines(member,spec['format'],spec['max_uncompressed_bytes'],expected_size=spec.get('expected_uncompressed_size_bytes'),totals=totals)
        if spec['role']=='obo':
            if ontology is not None:raise ValueError('one_ontology_required')
            ontology=parse_obo(lines())
        elif spec['role']=='gaf':gafs.append((member,spec))
        elif spec['role']=='gmt':term_results.append(parse_gmt(lines()))
        else:
            if spec['format'].endswith('.gz'):
                delimiter='\t'
                rows=enumerate(csv.DictReader(lines(),delimiter=delimiter),2)
            else:
                if spec['format']=='xlsx':
                    from zipfile import ZipFile
                    with ZipFile(member['path']) as archive:expanded=sum(i.file_size for i in archive.infolist())
                else:expanded=member['size_bytes']
                totals[0]+=expanded
                if totals[0]>2*1024**3:raise ValueError('resource_total_expansion_budget_exceeded')
                if spec.get('expected_uncompressed_size_bytes') is not None and expanded!=spec['expected_uncompressed_size_bytes']:
                    raise ValueError('resource_expansion_size_mismatch')
                rows=iter_table(member,format=spec['format'],sheet=spec.get('sheet'),max_uncompressed_bytes=spec['max_uncompressed_bytes'])
            columns={key:value for key,value in spec['columns'].items() if value is not None}
            converted=[]
            for number,cells in rows:
                if not set(columns.values())<=set(cells):raise ValueError('resource_column_missing')
                converted.append({key:cells[value] for key,value in columns.items()})
                if len(converted)>MAX_ROWS:raise ValueError('resource_row_limit')
            if spec['role']=='term_gene':term_results.append(_term_rows(converted))
            else:tabular.extend(converted)
    if gafs and not ontology or ontology and not gafs:raise ValueError('matched_obo_gaf_required')
    for member,spec in gafs:
        term_results.append(parse_gaf(text_lines(member,spec['format'],spec['max_uncompressed_bytes'],expected_size=spec.get('expected_uncompressed_size_bytes'),totals=totals),ontology,
            config['species_taxon_id'],config.get('evidence_codes'),config['propagation_relations'],config['namespace']))
    if config['kind']=='gene_sets':
        merged={};stats=Counter();exclusions=[];headers=[]
        for result in term_results:
            stats.update(result['stats']);exclusions.extend(result.get('exclusions',[]))
            if 'header' in result:headers.append(dict(gaf=result['header'],ontology=result['ontology_header']))
            for term in result['terms']:
                key=term['term_id']
                if key in merged and (merged[key]['name'],merged[key]['namespace'])!=(term['name'],term['namespace']):
                    raise ValueError('term_definition_conflict')
                old=merged.setdefault(key,{**term,'genes':set()});old['genes'].update(term['genes'])
        if len(merged)>MAX_TERMS:raise ValueError('term_count_limit')
        if sum(len(v['genes']) for v in merged.values())>MAX_RELATIONS:raise ValueError('resource_relation_limit')
        if len(set().union(*(v['genes'] for v in merged.values())))>MAX_GENES:raise ValueError('resource_gene_limit')
        stats['term_count']=len(merged)
        data=dict(terms=[{**v,'genes':sorted(v['genes'])} for k,v in sorted(merged.items())],stats=dict(stats),headers=headers)
        writer.table('resource_exclusions',exclusions,['row_number','feature_id','term_id','reason'])
        writer.table('term_genes',(dict(term_id=t['term_id'],term_name=t['name'],namespace=t['namespace'],feature_id=g)
            for t in data['terms'] for g in t['genes']),['term_id','term_name','namespace','feature_id'])
        classifications=defaultdict(set)
        for term in data['terms']:
            classifications[term['namespace']].update(term['genes'])
            for subset in term.get('subsets',[]):classifications['subset:'+subset].update(term['genes'])
        writer.table('functional_classification',[dict(category=k,gene_count=len(v),mutually_exclusive=False) for k,v in sorted(classifications.items())],
                     ['category','gene_count','mutually_exclusive'])
        stats['term_count']=len(data['terms'])
    elif config['kind']=='id_mapping':
        data=normalize_mapping(tabular,config['strip_ensembl_version']);stats=data['stats']
        data.update(source_namespace=config['mapping_source_namespace'],target_namespace=config['mapping_target_namespace'])
        writer.table('mapping_rows',data['rows'],['row_number','original_id','source_id','target_id'])
        writer.table('mapping_exclusions',[dict(source_id=k,reason='one_to_many') for k in data['ambiguous_source_ids']],['source_id','reason'])
    else:
        data=normalize_annotations(tabular);stats=data['stats']
        writer.table('annotations',data['annotations'],['feature_id','field','value','raw_value','value_type','unit','source','evidence_status'])
    resource=dict(schema_version=1,importer_version='bio_resource_import_v1',kind=config['kind'],species_taxon_id=config['species_taxon_id'],
                  namespace=config['namespace'],release=config['release'],source=config['source'],usage=config['usage'],
                  input_files=originals,strip_ensembl_version=config['strip_ensembl_version'],**data)
    writer.json('resource',resource)
    methods=dict(resource_kind=config['kind'],release=config['release'],source=config['source'],usage=config['usage'],
                 propagation_relations=config['propagation_relations'] if ontology else [],exclude_not=True,exclude_obsolete=True,
                 root_terms_excluded=sorted(ROOT_TERMS),evidence_codes=config['evidence_codes'],multi_label_counts_not_exclusive=True,
                 identifier_mapping='explicit_one_to_one_only; ORA_deduplicates_targets; GSEA_excludes_many_to_one',
                 sequence_structure_features='imported_annotations_only',input_files=originals)
    return dict(summary=dict(stats),methods=methods,inference_scope='derived',provenance='system_computed')


def run_feature_resource_import(payload,writer):
    from .feature_extract import extract_fasta,_structure_atoms
    config=payload['config'];spec=config['files'][0]
    source=next(s for s in payload['sources'] if s['source_id']==spec['file_id']);member=source['members']['original_file']
    if member['sha256']!=spec['sha256']:raise ValueError('feature_resource_sha_changed')
    text='\n'.join(text_lines(member,spec['format'],min(spec['max_uncompressed_bytes'],268435456),expected_size=spec.get('expected_uncompressed_size_bytes')))
    if config['kind']=='sequence':
        rows,excluded=extract_fasta(text,config['sequence_type'],payload['identity']['resource_version_id'],config.get('nucleotide_encoding'))
        inventory=dict(record_count=len(rows)+len(excluded),character_count=sum(r['length'] for r in rows+excluded),invalid_record_count=len(excluded))
    else:
        atoms=_structure_atoms(text,spec['format'].removesuffix('.gz'))
        inventory=dict(atom_count=len(atoms),model_chains=[dict(model_id=m,chain_id=c) for m,c in sorted({(a['model_id'],a['chain_id']) for a in atoms if a['chain_id'] is not None})])
    # Publish exact source bytes as a usable frozen input member, not a path or
    # a parsed replacement. Original files also retain their existing FKs.
    writer.add('feature_input_0',Path(member['path']).read_bytes(),spec['format'],'feature_input')
    original=dict(file_id=spec['file_id'],sha256=member['sha256'],format=spec['format'],role=spec['role'],member_key='feature_input_0')
    resource=dict(schema_version=1,kind=config['kind'],sequence_type=config.get('sequence_type'),nucleotide_encoding=config.get('nucleotide_encoding'),structure_origin=config.get('structure_origin'),
        species_taxon_id=config['species_taxon_id'],namespace=config['namespace'],release=config['release'],source=config['source'],usage=config['usage'],input_files=[original],inventory=inventory)
    writer.json('resource',resource)
    methods=dict(resource_kind=config['kind'],release=config['release'],source=config['source'],usage=config['usage'],input_files=[original],sequence_structure_features='validated_input_only; extraction_requires_feature_extract_run',
        sequence_type=config.get('sequence_type'),nucleotide_encoding=config.get('nucleotide_encoding'),structure_origin=config.get('structure_origin'))
    return dict(summary=inventory,methods=methods,inference_scope='derived',provenance='system_computed')
