"""Read-only material declarations and frozen references; readers verify asset bytes."""
from app.core.exceptions import StorageError
from app.domain.external_evidence.service import validate_evidence_row


def audit_external_evidence(db):
    rows=db.execute('SELECT * FROM external_evidence_versions').fetchall()
    invalid=0
    for row in rows:
        try:
            validate_evidence_row(db,row)
        except (StorageError,KeyError,ValueError,TypeError):
            invalid+=1
    return [dict(table='external_evidence_versions',column='source_and_declaration',rows=len(rows),invalid=invalid)]
