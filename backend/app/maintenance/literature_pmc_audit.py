"""Read-only OAI source identity, licenses, bytes and parsed scope audit."""
from types import SimpleNamespace
from app.core.config import get_data_dir
from app.db.database import get_database_config
from app.domain.literature_pmc.service import LiteraturePmcService


def audit_literature_pmc(db):
    rows=db.execute('SELECT * FROM literature_pmc_receipts').fetchall();invalid=0
    for row in rows:
        try:
            service=LiteraturePmcService(SimpleNamespace(owner_id=row['user_id'],db_config=get_database_config(),directory=get_data_dir()))
            service.actual(db,row['project_id'],row)
        except Exception: invalid+=1
    return [dict(table='literature_pmc_receipts',column='actual_xml_identity_license_and_scope',rows=len(rows),invalid=invalid)]
