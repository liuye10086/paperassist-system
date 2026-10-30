"""V2 intake reuses B01 container/spatial checks without changing V1 parsing."""
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from dataclasses import replace
import numpy as np
from scipy import sparse
from app.adapters.bio_parser.archive import Member,Budget,unpack
from app.adapters.bio_parser.visium import _parse_members,_role,_features,_barcodes,COMPONENT_ROLES
from app.adapters.bio_parser.matrix import _integers
from app.domain.bioinformatics.settings import BioLimits
from app.domain.bioinformatics.parser_contracts import BioParseError
from app.adapters.bio_engine.hdf5_checks import read_10x,compare
from app.adapters.bio_engine.manifest import canonical
from app.adapters.bio_engine import ENGINE_VERSION


def _unique(members,role,required=False):
    selected=[m for m in members if _role(m)==role]
    if not selected:
        if required:raise BioParseError('bio_components_mismatch','missing_'+role)
        return None
    if any(m.content!=selected[0].content for m in selected[1:]):raise BioParseError('bio_components_mismatch','ambiguous_'+role)
    return sorted(selected,key=lambda m:(m.name,m.source_file_id or ''))[0]


def _mtx(member,features,barcodes,limits):
    stream=io.BytesIO(member.content)
    if stream.readline().strip()!=b'%%MatrixMarket matrix coordinate integer general':raise BioParseError('bio_matrix_invalid','matrix_market_header')
    line=stream.readline()
    while line.startswith(b'%'):line=stream.readline()
    nf,no,nnz=_integers(line,3)
    if not 0<nf<=limits.max_features or not 0<no<=limits.max_observations or nnz>limits.max_entries:raise BioParseError('bio_input_limit','matrix_dimensions')
    if nf!=len(features['feature_ids']) or no!=len(barcodes):raise BioParseError('bio_components_mismatch','matrix_axis_lengths')
    keys=np.empty(nnz,dtype=np.int64);data=np.empty(nnz,dtype=np.int64);cursor=0;total=0
    for line in stream:
        if not line.strip() or line.startswith(b'%'):continue
        if cursor>=nnz:raise BioParseError('bio_matrix_invalid','entry_count')
        feature,observation,value=_integers(line,3);total+=value
        if not 1<=feature<=nf or not 1<=observation<=no or total>np.iinfo(np.int64).max:raise BioParseError('bio_matrix_invalid','entry_bounds')
        keys[cursor]=(observation-1)*nf+feature-1;data[cursor]=value;cursor+=1
    if cursor!=nnz:raise BioParseError('bio_matrix_invalid','entry_count')
    order=np.argsort(keys,kind='stable');keys=keys[order];data=data[order]
    offsets=np.flatnonzero(np.r_[True,keys[1:]!=keys[:-1]]) if nnz else np.array([],dtype=np.int64)
    unique=keys[offsets];values=np.add.reduceat(data,offsets) if nnz else data
    zeros=int((values==0).sum());nonzero=values!=0;unique=unique[nonzero];values=values[nonzero]
    indptr=np.zeros(no+1,dtype=np.int64);np.cumsum(np.bincount(unique//nf,minlength=no),out=indptr[1:])
    matrix=sparse.csr_matrix((values,(unique%nf).astype(np.int32),indptr),shape=(no,nf))
    return matrix,{'input_entries':nnz,'canonical_entries':int(matrix.nnz),'duplicate_coordinates_merged':nnz-len(offsets),'explicit_zero_coordinates_removed':zeros}


def _export(matrix,features,barcodes,source):
    buffer=io.StringIO();buffer.write(f'%%MatrixMarket matrix coordinate integer general\n{matrix.shape[1]} {matrix.shape[0]} {matrix.nnz}\n')
    for row in range(matrix.shape[0]):
        for j in range(matrix.indptr[row],matrix.indptr[row+1]):buffer.write(f'{int(matrix.indices[j])+1} {row+1} {int(matrix.data[j])}\n')
    stem='derived/'+source.name.replace('/','_')+'/'
    result=[Member(stem+'matrix.mtx',buffer.getvalue().encode(),source.source_file_id,'matrix')]
    buffer=io.StringIO();writer=csv.writer(buffer,delimiter='\t',lineterminator='\n')
    writer.writerows(zip(features['feature_ids'],features['feature_symbols'],features['feature_types']))
    result.append(Member(stem+'features.tsv',buffer.getvalue().encode(),source.source_file_id,'features'))
    buffer=io.StringIO();writer=csv.writer(buffer,delimiter='\t',lineterminator='\n');writer.writerows([[b] for b in barcodes])
    result.append(Member(stem+'barcodes.tsv',buffer.getvalue().encode(),source.source_file_id,'barcodes'))
    return result


def import_v2(payload):
    limits=BioLimits.model_validate(payload.get('settings',{}));budget=Budget(limits)
    members=[];inputs=[];files=payload['files']
    if not files or len(files)>10:raise BioParseError('bio_input_limit','input_files')
    for item in files:
        path=Path(item['path'])
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=item['size_bytes']:raise BioParseError('bio_source_changed','source_size')
        if item['size_bytes']>limits.max_upload_bytes:raise BioParseError('bio_input_limit','upload_bytes')
        with path.open('rb') as stream:content=stream.read(limits.max_upload_bytes+1)
        if len(content)!=item['size_bytes'] or hashlib.sha256(content).hexdigest()!=item['sha256']:raise BioParseError('bio_source_changed','source_sha256')
        role=item.get('role','auto')
        if role not in COMPONENT_ROLES|{'auto','archive'}:raise BioParseError('bio_format_unsupported','declared_role')
        container=item['filename'].lower().endswith(('.tar','.tar.gz','.tgz')) or (len(content)>=262 and content[257:262]==b'ustar')
        if (container and role not in {'auto','archive'}) or (role=='archive' and not container):raise BioParseError('bio_components_mismatch','archive_role')
        unpacked=unpack(content,item['filename'],budget,item['id'])
        if role in COMPONENT_ROLES:
            if len(unpacked)!=1:raise BioParseError('bio_components_mismatch','component_role')
            unpacked[0].declared_role='alternate_matrix' if role=='matrix' and unpacked[0].content.startswith(b'\x89HDF\r\n\x1a\n') else role
        members.extend(unpacked);inputs.append({k:item[k] for k in ['id','filename','size_bytes','sha256']})
    original_components={'matrix','features','barcodes','positions','scalefactors','alternate_matrix','tissue_image'}
    gsm={accession for member in members if _role(member) in original_components for accession in re.findall(r'\bGSM[0-9]+(?=[_./-]|$)',member.name)}
    if len(gsm)>1:raise BioParseError('bio_components_mismatch','multiple_accessions')
    representation=payload.get('matrix_representation')
    if representation not in {'mtx','10x_h5'}:raise ValueError('invalid_parameter_matrix_representation')
    h5=_unique(members,'alternate_matrix',required=representation=='10x_h5')
    mtx=_unique(members,'matrix',required=representation=='mtx')
    feature_member=_unique(members,'features',required=representation=='mtx')
    barcode_member=_unique(members,'barcodes',required=representation=='mtx')
    h5_read=bool(h5 and (representation=='10x_h5' or payload.get('compare_alternate')))
    h5_value=read_10x(io.BytesIO(h5.content),limits=limits) if h5_read else None
    mtx_value=None
    if mtx and feature_member and barcode_member:
        ids,symbols,types=_features(feature_member,limits)
        # Legacy 2-column axes remain unknown, never silently declared RNA.
        feature_index={'feature_ids':ids,'feature_symbols':symbols,'feature_types':types}
        barcodes=_barcodes(barcode_member,limits)
        matrix,attestation=_mtx(mtx,feature_index,barcodes,limits)
        mtx_value=(matrix,feature_index,barcodes,attestation)
    comparison={'status':'not_comparable','reason':'alternate_not_requested'}
    if payload.get('compare_alternate'):
        if h5_value and mtx_value:
            comparison=compare(*mtx_value[:3],*h5_value[:3])
            if comparison['status']=='mismatch':raise ValueError('h5_matrix_mismatch')
        else:comparison={'status':'not_comparable','reason':'alternate_h5_or_mtx_axes_not_provided'}
    chosen=h5_value if representation=='10x_h5' else mtx_value
    source=h5 if representation=='10x_h5' else mtx
    if chosen is None:raise BioParseError('bio_components_mismatch','chosen_matrix_missing')
    matrix,feature_index,barcodes,attestation=chosen
    # Preserve every actual decoded source member. Only explicitly named derived
    # exports take the common parser's axis roles; no original is overwritten.
    retained=[replace(m,declared_role='supplementary') if _role(m) in {'matrix','features','barcodes'} else m for m in members]
    derived=_export(matrix,feature_index,barcodes,source)
    generated_bytes=sum(len(m.content) for m in derived)
    if generated_bytes>limits.max_expanded_bytes-budget.expanded or any(len(m.content)>limits.max_member_bytes for m in derived):raise BioParseError('bio_input_limit','derived_representation_budget')
    budget.expanded+=generated_bytes
    parsed=_parse_members([*retained,*derived],Path(payload['output_directory']),limits,budget,inputs)
    # A legacy two-column feature TSV means unknown feature type. A TSV export
    # cannot distinguish None from an empty field; canonical JSON preserves it.
    canonical_features=canonical(feature_index)
    feature_output=next(o for o in parsed.outputs if o['key']=='features_index')
    Path(feature_output['path']).write_bytes(canonical_features)
    feature_output.update(sha256=hashlib.sha256(canonical_features).hexdigest(),size_bytes=len(canonical_features))
    derived_names={m.name for m in derived}
    for output in parsed.outputs:
        if output['key'].startswith('source_') and output.get('source_member_name') in derived_names:
            output['role']='derived_representation'
        if h5_read and output.get('source_member_name')==h5.name and output['role']=='alternate_matrix':output['verification_state']='verified'
    description={'selected':representation,'matrix_representation':representation,'compare_alternate':bool(payload.get('compare_alternate')),'comparison':comparison,'chosen_attestation':attestation,
                 'source_gsm':next(iter(gsm),None),
                 'representation_sources':{key:None if member is None else {'source_file_id':member.source_file_id,'source_member_name':member.name,'sha256':hashlib.sha256(member.content).hexdigest()} for key,member in [('h5',h5),('mtx',mtx)]},
                 'h5_internal_check':'verified' if h5_read else 'internal_not_checked' if h5 else 'not_provided',
                 'chosen_source':{'source_file_id':source.source_file_id,'source_member_name':source.name,'sha256':hashlib.sha256(source.content).hexdigest()},
                 'derived_representations':[{'name':m.name,'role':m.declared_role,'sha256':hashlib.sha256(m.content).hexdigest(),'derived_from':source.name,'original':False} for m in derived]}
    parsed.manifest['parser_version']='geo_visium_import_v2';parsed.manifest['engine_version']=ENGINE_VERSION
    parsed.manifest['identity']=payload.get('identity',{})
    parsed.manifest['environment_digest']=payload.get('identity',{}).get('environment_digest')
    parsed.manifest['code_digest']=payload.get('identity',{}).get('code_digest')
    parsed.manifest['representation']=description
    parsed.manifest['members']=[{k:v for k,v in item.items() if k!='path'} for item in parsed.outputs]
    parsed.manifest['verification']['alternate_h5']=description['h5_internal_check']
    parsed.checks.update(alternate_h5=description['h5_internal_check'],representation_equivalence=comparison)
    steps=[{'key':'import_structure','status':'completed','reason':None,'params':{'parser_version':'geo_visium_import_v2'}},
           {'key':'h5_read','status':'completed' if h5_read else 'not_requested','reason':None if h5_read else 'h5_not_selected_for_read','params':{}},
           {'key':'equivalence','status':'not_computable' if comparison['status']=='not_comparable' else 'completed','reason':comparison.get('reason'),'params':{'comparator':'csr_all_values_v1'}}]
    parsed.manifest['steps']=steps
    result=parsed.summary();result.update(parser_version='geo_visium_import_v2',status='completed',engine_version=ENGINE_VERSION,steps=steps,
        summary={'shape':[parsed.n_observations,parsed.n_features],'nnz':parsed.entry_count,'representation':description},effective_params={'matrix_representation':representation,'compare_alternate':bool(payload.get('compare_alternate'))})
    return result
