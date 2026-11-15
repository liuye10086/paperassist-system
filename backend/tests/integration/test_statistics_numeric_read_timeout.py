"""Real libpq interruption under the R3 scope, without DDL or data writes."""
import os
import signal
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


@pytest.fixture(autouse=True)
def postgres_schema():yield None


@pytest.mark.skipif(sys.platform!='linux',reason='Real worker deadline requires Linux main thread')
def test_read_only_pg_interrupt_preserves_numeric_error_and_new_connection_after_scope():
    from app.core.exceptions import StorageError
    from app.domain.fixed_statistics_runtime import scope_active
    from app.domain.statistics_reader_reports.validation import worker_verification,validate_sources
    engine=create_engine(os.environ['PAPERASSIST_TEST_DATABASE_URL'],poolclass=NullPool)
    try:
        def check():
            with engine.connect() as db:
                with db.begin():
                    db.exec_driver_sql('SET TRANSACTION READ ONLY')
                    assert db.exec_driver_sql('SELECT current_database()').scalar_one()=='paperassist_system_test'
                    # Inject an early deadline through the real installed Linux
                    # handler while libpq is waiting; no business tables touched.
                    signal.setitimer(signal.ITIMER_REAL,0.01)
                    db.exec_driver_sql('SELECT pg_sleep(0.1)')
        with worker_verification():
            with pytest.raises(StorageError) as failed:validate_sources(check)
            assert failed.value.code=='numeric_timeout'
            assert failed.value.execution_receipt['error_code']=='numeric_timeout'
            assert not scope_active()
            with engine.connect() as db:
                db.exec_driver_sql('SET TRANSACTION READ ONLY')
                assert db.exec_driver_sql('SELECT 1').scalar_one()==1
    finally:
        engine.dispose()
