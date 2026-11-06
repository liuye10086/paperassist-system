"""Cell intake and count aggregation reuse the existing sparse scientific core."""
import hashlib
import io
from pathlib import Path
import numpy as np
from scipy import sparse
from app.adapters.bio_parser.archive import Budget,unpack
from app.adapters.bio_parser.visium import _role,_features,_barcodes
from app.adapters.bio_engine.importer import _mtx,_unique
from app.adapters.bio_engine.hdf5_checks import read_10x,read_h5ad_counts
from app.adapters.bio_engine.manifest import canonical
from app.domain.bioinformatics.settings import BioLimits
from app.domain.bioinformatics.single_cell_contracts import SingleCellImportRequest
from app.adapters.bio_engine import ENGINE_VERSION


def _read_counts(members,config,limits):
    representation=config.matrix_representation
    if representation=='mtx':
        source=_unique(members,'matrix',True);feature=_unique(members,'features',True);barcode=_unique(members,'barcodes',True)
        ids,symbols,types=_features(feature,limits)
        if config.two_column_feature_type:types=[t or config.two_column_feature_type for t in types]
        features=dict(feature_ids=ids,feature_symbols=symbols,feature_types=types)
        cells=_barcodes(barcode,limits);matrix,attestation=_mtx(source,features,cells,limits,allow_real_integer=True)
        attestation['two_column_feature_type_declaration']=config.two_column_feature_type
    else:
        candidates=[m for m in members if m.content.startswith(b'\x89HDF\r\n\x1a\n')]
        if len(candidates)!=1:raise ValueError('single_cell_one_hdf5_source_required')
        source=candidates[0]
        if representation=='h5ad':matrix,features,cells,attestation=read_h5ad_counts(io.BytesIO(source.content),config.h5ad.model_dump(),limits)
        else:matrix,features,cells,attestation=read_10x(io.BytesIO(source.content),limits)
    # A legacy two-column feature file stays unknown; no guessed RNA modality.
    if not any(t=='Gene Expression' for t in features['feature_types']):raise ValueError('single_cell_gene_expression_features_required')
    return matrix,features,cells,attestation,source


def import_counts(payload):
    config=SingleCellImportRequest.model_validate(payload['single_cell_config'])
    limits=BioLimits.model_validate(payload.get('settings',{}));budget=Budget(limits)
    members=[];inputs=[]
    for item in payload['files']:
        p=Path(item['path'])
        if p.is_symlink() or not p.is_file() or not 0<item['size_bytes']<=limits.max_upload_bytes or p.stat().st_size!=item['size_bytes']:raise ValueError('source_size')
        content=p.read_bytes()
        if hashlib.sha256(content).hexdigest()!=item['sha256']:raise ValueError('source_hash')
        decoded=unpack(content,item['filename'],budget,item['id'])
        role=item.get('role','auto')
        if role not in ('auto','archive','matrix','features','barcodes','alternate_matrix','supplementary','geo_metadata'):raise ValueError('single_cell_nonspatial_role_required')
        if role not in ('auto','archive'):
            if len(decoded)!=1:raise ValueError('component_role')
            decoded[0].declared_role=role
        members.extend(decoded);inputs.append({k:item[k] for k in ('id','filename','size_bytes','sha256')})
    representation=config.matrix_representation
    mapping=[]
    if not config.samples:
        matrix,features,cells,attestation,source=_read_counts(members,config,limits)
    else:
        matrices=[];cells=[];attestations=[];features=None;source=None
        total_cells=total_entries=total_counts=0
        for sample in config.samples:
            own=[m for m in members if m.source_file_id in sample.file_ids]
            current,current_features,current_cells,evidence,current_source=_read_counts(own,config,limits)
            if features is None:
                features=current_features;source=current_source
            else:
                if set(current_features['feature_ids'])!=set(features['feature_ids']):raise ValueError('sample_gene_set_mismatch')
                indices={gene:i for i,gene in enumerate(current_features['feature_ids'])}
                order=[indices[gene] for gene in features['feature_ids']]
                if any([current_features[key][i] for i in order]!=features[key] for key in ('feature_symbols','feature_types')):
                    raise ValueError('sample_feature_metadata_mismatch')
                current=current[:,order].tocsr();current.sort_indices()
            total_cells+=current.shape[0];total_entries+=current.nnz;total_counts+=sum(map(int,current.data))
            if total_cells>limits.max_observations or total_entries>limits.max_entries:raise ValueError('sample_merged_matrix_limit')
            if total_counts>np.iinfo(np.int64).max:raise ValueError('sample_counts_overflow')
            matrices.append(current)
            for barcode in current_cells:
                identifier=sample.library_id+':'+barcode;cells.append(identifier)
                row=dict(barcode=identifier,original_barcode=barcode,library_id=sample.library_id)
                for field in ('sample_id','donor','batch','group','species_taxon_id','reference_id','reference_version','library_chemistry','pair_id'):
                    value=getattr(sample,field)
                    row[field]=dict(status='known' if value is not None else 'pending',value=value)
                mapping.append(row)
            attestations.append(dict(library_id=sample.library_id,counts=evidence))
        matrix=sparse.vstack(matrices,format='csr')
        attestation=dict(libraries=attestations,alignment='feature_id_exact_set',barcode_namespace='library_id:original_barcode',counts_total=total_counts)
    root=Path(payload['output_directory']);root.mkdir(parents=True,exist_ok=True);outputs=[]
    def write(key,body,role,fmt,origin=source):
        path=root/(key+'.'+fmt)
        if path.is_symlink() or path.exists():raise ValueError('output_not_empty')
        if len(body)>limits.max_member_bytes:raise ValueError('output_member_budget')
        path.write_bytes(body)
        outputs.append(dict(key=key,path=str(path.resolve()),role=role,format=fmt,compression='none',verification_state='verified',source_file_id=origin.source_file_id,source_member_name=origin.name,sha256=hashlib.sha256(body).hexdigest(),size_bytes=len(body)))
    for key,array in [('matrix_data',matrix.data.astype('int64')),('matrix_indices',matrix.indices.astype('int32')),('matrix_indptr',matrix.indptr.astype('int64'))]:
        stream=io.BytesIO();np.save(stream,array,allow_pickle=False);write(key,stream.getvalue(),key,'npy')
    write('features_index',canonical(features),'features_index','json');write('barcodes_index',canonical({'barcodes':cells}),'barcodes_index','json')
    if mapping:write('observation_map_index',canonical({'rows':mapping}),'observation_map_index','json')
    for i,member in enumerate(members):
        fmt='h5ad' if member.content.startswith(b'\x89HDF') and representation=='h5ad' else 'h5' if member.content.startswith(b'\x89HDF') else 'mtx' if _role(member)=='matrix' else 'tsv' if _role(member) in ('features','barcodes') else 'txt'
        write('source_'+str(i).zfill(3),member.content,_role(member),fmt,member)
    if sum(o['size_bytes'] for o in outputs)>limits.max_expanded_bytes:raise ValueError('output_budget')
    checks=dict(structure='checked',source_accessions={'gse':None,'gsm':None},warnings=[],positions_count=0,in_tissue_count=None,matrix_matches_in_tissue=None,matrix_barcodes_in_positions=None,alternate_h5='verified' if representation!='mtx' else 'not_provided',empty_series_matrix=False,duplicate_symbol_groups=len(features['feature_symbols'])-len(set(features['feature_symbols'])),single_cell_counts=attestation)
    manifest=dict(schema_version=1,parser_version='single_cell_import_v1',parser_fingerprint='single_cell_counts_v1',assay='single_cell',observation_level='cell',source_accessions=checks['source_accessions'],input_shape={'features':matrix.shape[1],'observations':matrix.shape[0]},matrix_orientation='observations_by_features',input_orientation='features_by_observations' if representation!='h5ad' else 'observations_by_features',transposed=representation!='h5ad',stored_entries=int(matrix.nnz),storage_format='csr_npy_v1',matrix_dtypes={'data':'int64','indices':'int32','indptr':'int64'},processing={'normalized':False,'filtered_by_this_system':False},verification={'structure':'checked','study_design':'pending'},source_files=inputs,members=[{k:v for k,v in o.items() if k!='path'} for o in outputs],checks=checks,parse_settings=limits.model_dump(),representation={'selected':representation,'h5ad':config.h5ad.model_dump() if config.h5ad else None,'attestation':attestation},identity=payload.get('identity',{}),engine_version=ENGINE_VERSION)
    if config.samples:manifest['samples']=[sample.model_dump() for sample in config.samples]
    return dict(parser_version='single_cell_import_v1',manifest=manifest,outputs=outputs,checks=checks,n_features=matrix.shape[1],n_observations=matrix.shape[0],entry_count=int(matrix.nnz))


def aggregate_cells(counts,rows,*,design_confirmed=False):
    """Aggregate cell group -> sample -> donor; technical samples do not add n."""
    if counts.shape[0]!=len(rows):raise ValueError('cell_axis_mismatch')
    state=dict(cells=len(rows),samples=len({r.get('sample_id') for r in rows if r.get('sample_id')}),donors=len({r.get('donor') for r in rows if r.get('donor')}),exploration_allowed=True,statistical_unit='donor',technical_samples_are_independent=False)
    missing=any(not r.get('sample_id') or not r.get('donor') or not r.get('group') or r.get('cluster') is None for r in rows)
    if missing or not design_confirmed:
        return None,[],{**state,'status':'blocked','reason':'cell_sample_donor_mapping_incomplete' if missing else 'independent_donor_design_not_confirmed'}
    sample_assignment={};groups={}
    for i,row in enumerate(rows):
        sample=row['sample_id'];donor=row['donor'];group=row['group']
        if sample in sample_assignment and sample_assignment[sample]!=(donor,group):
            return None,[],{**state,'status':'blocked','reason':'sample_donor_assignment_conflict'}
        # Paired designs retain a separate count unit for each donor x condition.
        sample_assignment[sample]=(donor,group)
        groups.setdefault((str(row['cluster']),donor,group),[]).append(i)
    units=[];values=[]
    for (cluster,donor,group),indices in sorted(groups.items()):
        values.append(sparse.csr_matrix(counts[indices].sum(axis=0),dtype='int64'))
        units.append(dict(cluster=cluster,donor=donor,group=group,cell_count=len(indices),sample_ids=sorted({rows[i]['sample_id'] for i in indices}),independent_n=1))
    result=sparse.vstack(values,format='csr') if values else sparse.csr_matrix((0,counts.shape[1]),dtype='int64')
    if int(result.sum())!=int(counts.sum()):raise ValueError('pseudobulk_conservation')
    return result,units,{**state,'status':'ready','reason':None,'counts_total':int(result.sum()),'inference_requires_existing_donor_contrast':True}
