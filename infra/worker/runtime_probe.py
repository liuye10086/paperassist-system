"""Read-only host connectivity probe; error categories never include credentials."""
import json
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

key = 'PAPERASSIST_TEST_DATABASE_URL' if os.environ.get('PAPERASSIST_ENV') == 'test' else 'PAPERASSIST_DATABASE_URL'
url = make_url(Path(os.environ[key + '_FILE']).read_text().strip())
engine = create_engine(url, hide_parameters=True, connect_args={'connect_timeout': 5})
try:
    with engine.connect() as connection:
        row = connection.exec_driver_sql('SELECT current_database(), current_user, inet_client_addr()::text').one()
        print(json.dumps({'database': row[0], 'role': row[1], 'source_address': row[2],
                          'data_mounted': Path('/data').is_dir()}))
except SQLAlchemyError as error:
    original = getattr(error, 'orig', error)
    print(json.dumps({'database_connected': False, 'sqlstate': getattr(original, 'sqlstate', None),
                      'hba_rejected': 'pg_hba.conf' in str(original),
                      'password_rejected': 'password authentication failed' in str(original)}))
    raise SystemExit(1)
finally:
    engine.dispose()
