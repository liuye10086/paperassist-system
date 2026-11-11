"""Explicit one-hop ID mapping, with taxon and namespace gates."""
import re
from .inputs import document


def resource_document(source):
    if source['source_kind']!='bio_resource_version' or 'resource' not in source['members']:
        raise ValueError('resource_source_invalid')
    resource=document(source['members']['resource'])
    if resource.get('schema_version')!=1:raise ValueError('resource_schema_invalid')
    return resource


class ExplicitMapper:
    def __init__(self,source_taxon_id,source_namespace,target_taxon_id,target_namespace,mapping_sources,*,
                 allow_untyped_identity=False, namespace_key=None):
        untyped_identity=allow_untyped_identity and source_taxon_id is None and target_taxon_id is None and source_namespace==target_namespace and not mapping_sources
        if not untyped_identity and (type(source_taxon_id) is not int or type(target_taxon_id) is not int or source_taxon_id!=target_taxon_id):
            raise ValueError('incompatible_species_mapping')
        if not source_namespace or not target_namespace:raise ValueError('explicit_namespace_required')
        matching=[]
        for source in mapping_sources:
            data=resource_document(source)
            if data['kind']!='id_mapping':raise ValueError('mapping_resource_kind_invalid')
            if data['species_taxon_id']!=source_taxon_id:raise ValueError('mapping_species_mismatch')
            pair=(data.get('source_namespace'),data.get('target_namespace'))
            if namespace_key is not None:
                pair=tuple(namespace_key(value) for value in pair)
            if pair==(source_namespace,target_namespace):
                matching.append((source,data))
        if len(matching)>1:raise ValueError('multiple_mapping_releases_ambiguous')
        if not matching and source_namespace!=target_namespace:raise ValueError('explicit_mapping_required')
        self.source_namespace=source_namespace;self.target_namespace=target_namespace
        self.source=None if not matching else matching[0][0]
        self.data=None if not matching else matching[0][1]
        self.ambiguous=set() if self.data is None else set(self.data.get('ambiguous_source_ids',[]))

    def map_id(self,original_id):
        if not isinstance(original_id,str) or not original_id or len(original_id)>1000:
            return None,'invalid_feature_id'
        if self.data is None:return original_id,None
        normalized=re.sub(r'^(ENS[A-Z]*[GTP]\d+)\.\d+$',r'\1',original_id) if self.data.get('strip_ensembl_version') else original_id
        if normalized in self.ambiguous:return None,'one_to_many_mapping'
        target=self.data['mapping'].get(normalized)
        if target is None:return None,'unmapped_feature_id'
        if not isinstance(target,str) or not target:raise ValueError('mapping_target_invalid')
        return target,None

    def identity(self):
        return {'source_namespace':self.source_namespace,'target_namespace':self.target_namespace,
                'mapping_source_id':None if self.source is None else self.source['source_id'],
                'mapping_sha256':None if self.source is None else self.source['sha256'],
                'strip_ensembl_version':False if self.data is None else self.data.get('strip_ensembl_version',False)}
