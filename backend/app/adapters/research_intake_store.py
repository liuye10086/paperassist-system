"""SQL persistence helpers used inside the existing project transaction boundary."""
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5
from app.core.exceptions import StorageError

NAMESPACE=UUID('b9f6f346-4bb9-4f75-9426-4875b4939853')
VERSION_TABLES={'requirements':'research_requirement_versions','research-designs':'research_design_versions'}


def now():
    return datetime.now(timezone.utc)


def initialize_intake(db,project_id,owner_id,project_type,*,delivery_kinds=None,creation_key=None,creation_digest=None):
    moment=now()
    db.execute('''INSERT INTO research_intakes(project_id,owner_id,revision,creation_request_key,creation_digest,created_at,updated_at)
        VALUES(%s,%s,1,%s,%s,%s,%s)''',(project_id,owner_id,creation_key,creation_digest,moment,moment))
    kinds=delivery_kinds if project_type=='research' else [{'sci':'sci_draft','thesis':'thesis_draft'}[project_type]]
    for kind in kinds:
        identifier=str(uuid4()) if project_type=='research' else str(uuid5(NAMESPACE,f'delivery:{project_id}:{kind}'))
        db.execute('''INSERT INTO research_deliveries(id,project_id,kind,name,origin,active,revision,created_by,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,true,1,%s,%s,%s)''',(identifier,project_id,kind,kind,'user_selected' if project_type=='research' else 'legacy_inferred',owner_id,moment,moment))


def require_owner(db,store,project_id):
    if not store.owner_id:
        raise StorageError('project_not_found','项目不存在。',404)
    project=db.execute('SELECT * FROM projects WHERE id=%s AND owner_id=%s',(project_id,store.owner_id)).fetchone()
    if project is None:
        raise StorageError('project_not_found','项目不存在。',404)
    return dict(project)


def require_reference(db,table,identifier,project_id):
    if not db.execute(f'SELECT id FROM {table} WHERE id=%s AND project_id=%s',(identifier,project_id)).fetchone():
        raise StorageError('research_material_invalid','材料引用不存在或不属于当前项目。',422)


def version_view(db,row,kind):
    if row is None:
        return None
    value=dict(row)
    value['content']=value.pop('content_json')
    from app.domain.research_intake.validation import requirement_gaps, design_gaps
    issues=(requirement_gaps if kind=='requirements' else design_gaps)(value['content'])
    value['confirmed']=value['operation']=='confirm'
    value['blocking_gaps']=[gap for gap in issues if gap['blocking']]
    value.pop('request_digest',None)
    # The request key is safe to return to its authenticated owner and makes
    # recovery after an unknown HTTP response unambiguous.
    column='requirement_version_id' if kind=='requirements' else 'design_version_id'
    fields=('delivery_id','file_id','bio_dataset_version_id','locator','availability','purpose','note')
    value['material_refs']=[{key:item[key] for key in fields} for item in db.execute(f'SELECT * FROM research_material_refs WHERE {column}=%s ORDER BY id',(value['id'],))]
    return value
