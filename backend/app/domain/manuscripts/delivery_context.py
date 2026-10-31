"""Resolve a document's exact delivery without changing the project type."""
from app.adapters.research_results_store import invalid


def resolve_document_context(db, project, owner, *, delivery_id=None, manuscript_id=None, active=True):
    row=db.execute('SELECT * FROM projects WHERE id=%s AND owner_id=%s',(project,owner)).fetchone()
    if not row:raise invalid('project_not_found',404)
    root=None
    if manuscript_id:
        root=db.execute('SELECT * FROM manuscripts WHERE id=%s AND project_id=%s AND user_id=%s',(manuscript_id,project,owner)).fetchone()
        if not root:raise invalid('manuscript_not_found',404)
        if delivery_id is not None and root['delivery_id']!=delivery_id:raise invalid('research_writing_unavailable',409)
        delivery_id=root['delivery_id']
    if delivery_id:
        delivery=db.execute('SELECT * FROM research_deliveries WHERE id=%s AND project_id=%s',(delivery_id,project)).fetchone()
        if not delivery:raise invalid('research_source_not_found',404)
        if (active and not delivery['active']) or delivery['kind'] not in ('sci_draft','thesis_draft'):raise invalid('research_writing_unavailable',409)
        kind={'sci_draft':'sci','thesis_draft':'thesis'}[delivery['kind']]
        if root and root['document_kind']!=kind:raise invalid()
    else:
        if row['project_type'] not in ('sci','thesis'):raise invalid('research_writing_unavailable',409)
        kind=row['project_type']
    return dict(project_id=project,project_type=row['project_type'],document_kind=kind,delivery_id=delivery_id,manuscript_id=manuscript_id)
