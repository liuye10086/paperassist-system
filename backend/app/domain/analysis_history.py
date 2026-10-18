"""Owner-scoped read-only discovery of immutable confirmed research results."""
from app.core.exceptions import StorageError


def confirmed_history(store,project_id,file_id):
    store.file(project_id,file_id)
    with store.connection() as db:
        runs=db.execute('SELECT id FROM analysis_runs WHERE file_id=%s ORDER BY completed_at DESC,id DESC',(file_id,)).fetchall()
    from app.domain.figure_workbench.sources import load_source
    items=[]
    for row in runs:
        try:
            result,_=load_source(store,project_id,file_id,row['id'])
        except StorageError:
            # Legacy unconfirmed results retain their existing read path. Broken
            # provenance cannot become a selectable input in the new workbench.
            continue
        items.append(result)
    return {'items':items}
