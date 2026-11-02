"""Parent-side feature output consistency checks; no scientific imports."""
import csv,json,math
from pathlib import Path


def validate_feature(result,items,payload):
    def doc(key):return json.loads(Path(items[key]['path']).read_bytes())
    def table(key,required):
        member=items[key]
        if member['format']!='tsv':raise ValueError('feature_table_format')
        with Path(member['path']).open(encoding='utf-8',newline='') as f:
            reader=csv.DictReader(f,delimiter='\t',strict=True)
            if not set(required)<=set(reader.fieldnames or []):raise ValueError('feature_table_columns')
            rows=list(reader)
            if any(None in r or any(v is None for v in r.values()) for r in rows):raise ValueError('feature_table_width')
            return rows
    config=payload['config'];resource=doc('resource')
    if payload['kind']=='bio_resource_import':
        for key in ('kind','species_taxon_id','namespace','release','source','usage','sequence_type','nucleotide_encoding','structure_origin'):
            if resource.get(key)!=config.get(key):raise ValueError('feature_resource_config_changed')
        expected=[{k:f[k] for k in ('file_id','sha256','format','role')}|{'member_key':'feature_input_0'} for f in config['files']]
        if resource['input_files']!=expected or items['feature_input_0']['sha256']!=expected[0]['sha256']:raise ValueError('feature_resource_bytes_changed')
        if result['summary']!=resource['inventory'] or result['methods']['input_files']!=expected:raise ValueError('feature_resource_inventory_changed')
        return
    data=doc('feature_data');rows=data['rows'];by_id={r['feature_id']:r for r in rows};summary=result['summary'];methods=result['methods']
    if len(by_id)!=len(rows) or summary['feature_count']!=len(rows):raise ValueError('feature_identity_or_count')
    if methods.get('recipe')!=config or methods.get('geometry_definition')!='equal_weight_protein_CA_Angstrom':raise ValueError('feature_methods_changed')
    flat=table('feature_results',{'row_key','feature_id','feature_kind','selected','extraction_provenance'})
    if len(flat)!=len(rows) or {r['feature_id'] for r in flat}!=set(by_id):raise ValueError('feature_table_incomplete')
    def cell(v):return '' if v is None else json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)
    for record in flat:
        original=by_id[record['feature_id']]
        if any(value!=cell(original.get(k)) for k,value in record.items()):raise ValueError('feature_table_values_changed')
        if original['extraction_provenance']!='actual_local_extraction':raise ValueError('feature_provenance_changed')
        if original['feature_kind'] in ('dna','rna'):
            valid=original['valid_count'];length=original['length']
            if valid+original['ambiguous_count']!=length or not math.isclose(original['ambiguous_fraction'],original['ambiguous_count']/length):raise ValueError('nucleotide_denominator_invalid')
            expected=(original['base_counts_G']+original['base_counts_C'])/valid if valid else None
            if original['gc_fraction']!=expected:raise ValueError('nucleotide_gc_invalid')
        elif original['feature_kind']=='protein':
            if sum(original['amino_acid_counts_'+aa] for aa in 'ACDEFGHIKLMNPQRSTVWY')!=original['standard_count']:raise ValueError('protein_count_invalid')
            if original['standard_count']+original['nonstandard_count']+original['stop_count']!=original['length']:raise ValueError('protein_denominator_invalid')
    candidates=table('feature_candidates',{'feature_id','rank'});wanted=[r for r in rows if r['selected']]
    if {r['feature_id'] for r in candidates}!={r['feature_id'] for r in wanted} or summary['selected_count']!=len(candidates):raise ValueError('feature_selection_invalid')
    if sorted(int(r['rank']) for r in candidates)!=list(range(1,len(candidates)+1)):raise ValueError('feature_rank_invalid')
    atoms=table('feature_atom_audit',{'feature_id','input_row','geometry_included','coordinates','reason'})
    if len(atoms)!=summary['input_atom_count']:raise ValueError('feature_atom_audit_incomplete')
    if any(a['geometry_included']=='True' and a.get('polymer')!='True' for a in atoms):raise ValueError('feature_nonpolymer_geometry')
    for row in rows:
        if row['feature_kind']!='structure':continue
        selected=[json.loads(a['coordinates']) for a in atoms if a['feature_id']==row['feature_id'] and a['geometry_included']=='True']
        n=len(selected)
        if n!=row['ca_count']:raise ValueError('feature_geometry_count')
        center=[sum(x[j] for x in selected)/n for j in range(3)] if n else [None]*3
        rg=math.sqrt(sum(sum((x[j]-center[j])**2 for j in range(3)) for x in selected)/n) if n else None
        for got,want in zip([row['centroid_'+a] for a in 'xyz']+[row['radius_of_gyration']],center+[rg]):
            if (got is None)!=(want is None) or got is not None and not math.isclose(got,want,rel_tol=1e-6,abs_tol=1e-8):raise ValueError('feature_geometry_value')
    excluded=table('feature_exclusions',{'feature_id','reason'})
    if len(excluded)!=summary['excluded_count']:raise ValueError('feature_exclusion_count')
    for key,columns in [('feature_residue_audit',{'feature_id','reason'}),('feature_warnings',{'code'}),('feature_filter_steps',{'step','before_count','after_count'}),('feature_filter_exclusions',{'step','feature_id','reason'}),('feature_missing_requested',{'feature_id','reason'}),('feature_annotation_exclusions',{'feature_id','reason'})]:table(key,columns)
    if resource['kind']!='feature_annotation' or any(r['extraction_provenance']!='actual_local_extraction' for r in resource['annotations']):raise ValueError('feature_annotation_bridge_invalid')
    if any(k in items for k in ('comparison_results','correction_families')):raise ValueError('feature_must_not_fake_comparison')
