"""Relational scope and receipt identities for additive quality derivations."""
from app.domain.dataset_preparation.quality_contracts import ManifestReference


def valid_derivation(row, indexes):
    try:
        child = indexes['prepared_dataset_versions'][row['prepared_dataset_id']]
        base = indexes['prepared_dataset_versions'][row['base_prepared_dataset_id']]
        manifest = ManifestReference.model_validate({key:row['manifest_' + key] for key in ('object_key','sha256','size_bytes','entry_count')})
        return (child['file_id'] == base['file_id'] and child['created_by'] == base['created_by']
                and child['parent_dataset_id'] == base['parent_dataset_id'] and base['version'] < child['version']
                and row['object_schema_version'] == 2 and row['transform_version'] == 'excel_prepare_v2'
                and row['workflow_version'] == 'dataset_preparation_v2' and row['rules_version'] == 'quality_rules_v1'
                and manifest.object_key == f"quality-manifests/{child['id']}/{manifest.sha256}.json")
    except (KeyError, TypeError, ValueError):
        return False


def valid_derivation_v3(row,indexes):
    """The additive v3 table has its own operation/rules contract."""
    try:
        child=indexes['prepared_dataset_versions'][row['prepared_dataset_id']]
        base=indexes['prepared_dataset_versions'][row['base_prepared_dataset_id']]
        manifest=ManifestReference.model_validate({k:row['manifest_'+k] for k in ('object_key','sha256','size_bytes','entry_count')})
        rules={'population_filter':'population_filter_rules_v1','quality':'quality_rules_v1'}
        return (child['id']!=base['id'] and child['file_id']==base['file_id'] and child['created_by']==base['created_by']
            and child['parent_dataset_id']==base['parent_dataset_id'] and base['version']<child['version']
            and type(row['object_schema_version']) is int and row['object_schema_version']==3
            and row['transform_version']=='excel_prepare_v3' and row['workflow_version']=='dataset_preparation_v3'
            and row['rules_version']==rules[row['operation']]
            and manifest.object_key==f"derivation-manifests-v3/{child['id']}/{manifest.sha256}.json")
    except (KeyError,TypeError,ValueError):return False
