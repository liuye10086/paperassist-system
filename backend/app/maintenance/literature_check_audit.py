"""Read-only validation of immutable check identity, requests and frozen results."""
from types import SimpleNamespace
from app.core.config import get_data_dir
from app.db.database import get_database_config
from app.adapters.file_objects import LocalFileObjects
from app.domain.literature_checks.service import LiteratureCheckService


def audit_literature_checks(db):
    services={};invalid=0;rows=db.execute('SELECT * FROM literature_check_receipts').fetchall()
    for row in rows:
        try:
            owner=row['user_id']
            if owner not in services:
                services[owner]=LiteratureCheckService(SimpleNamespace(owner_id=owner,db_config=get_database_config(),
                    directory=get_data_dir(),original=LocalFileObjects(get_data_dir()).original))
            svc=services[owner]
            svc.view(db,row['project_id'],row)
        except Exception:
            invalid+=1
    return [dict(table='literature_check_receipts',column='owner_request_and_frozen_result',rows=len(rows),invalid=invalid)]
