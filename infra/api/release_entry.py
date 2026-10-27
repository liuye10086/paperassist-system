"""Fixed local operator entry points. Never served over HTTP."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['migrate','check','drain','fingerprint','collect','tls','requirements'])
    parser.add_argument('--revision',default='head')
    args=parser.parse_args()
    if args.action=='requirements':
        import importlib.metadata
        from packaging.requirements import Requirement
        mismatch=[]
        for line in Path('/releaseapp/requirements.txt').read_text().splitlines():
            if not line.strip() or line.startswith('#'): continue
            req=Requirement(line)
            try: installed=importlib.metadata.version(req.name)
            except importlib.metadata.PackageNotFoundError: installed='missing'
            if installed=='missing' or not req.specifier.contains(installed): mismatch.append(req.name)
        if mismatch: raise ValueError('Installed requirements differ: '+','.join(mismatch))
        print(json.dumps({'requirements':'exact-match'})); return
    if args.action=='tls':
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from datetime import datetime,timedelta,timezone
        import ipaddress
        directory=Path('/run/tls'); now=datetime.now(timezone.utc)
        ca_key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'PaperAssist local acceptance CA')])
        ca=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=30)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).sign(ca_key,hashes.SHA256())
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        server=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])).issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=30)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(ca_key,hashes.SHA256())
        for name,value in [('ca.pem',ca.public_bytes(serialization.Encoding.PEM)),('server.pem',server.public_bytes(serialization.Encoding.PEM)),('server-key.pem',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))]:
            (directory/name).write_bytes(value)
        # The private CA signing key is not retained; clients receive only ca.pem.
        print(json.dumps({'tls':'created','sans':['localhost','127.0.0.1']})); return
    from app.workers.config import load_secrets
    load_secrets()
    from app.db.database import (database_connection, get_database_config, get_engine,
        get_migration_database_config, migrate_database, migration_connection,
        alembic_config, ensure_schema_current, verify_runtime_permissions)
    if args.action=='migrate':
        os.environ['PAPERASSIST_MIGRATION_DATABASE_URL']=Path('/run/secrets/migration-url').read_text().strip()
        if args.revision=='head': migrate_database()
        elif args.revision=='0052_admin_configurations':
            from alembic import command
            with migration_connection() as db:
                # This option is for a genuinely empty new target only.
                if db.execute("SELECT to_regclass('public.alembic_version') AS present").fetchone()['present'] is not None:
                    raise ValueError('Intermediate revision requires an empty target')
                settings=alembic_config(); settings.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
                command.upgrade(settings,args.revision)
        else: raise ValueError('Unsupported revision')
        print(json.dumps({'migration':'complete','target':args.revision})); return
    if args.action=='collect':
        from app.domain.runtime_status import collect,write_status
        value=json.loads(Path('/control/observations.json').read_text())
        write_status(collect(value)); print(json.dumps({'collected':True})); return
    with database_connection() as db:
        if args.action=='check':
            ensure_schema_current(db); verify_runtime_permissions(db.raw_connection,db.config)
            print(json.dumps({'schema':'current','runtime_permissions':'verified'}))
        elif args.action=='drain':
            rows=db.execute("SELECT status,count(*) AS count FROM tasks WHERE status IN ('queued','running') GROUP BY status").fetchall()
            counts={'queued':0,'running':0}; counts.update({r['status']:r['count'] for r in rows})
            print(json.dumps(counts))
        elif args.action=='fingerprint':
            from app.maintenance.backup_manifest import database_fingerprints
            # The primitive accepts a psycopg connection and reads every table.
            raw=db.raw_connection.connection.driver_connection
            tables=database_fingerprints(raw,'public')
            sequences=db.execute("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename").fetchall()
            print(json.dumps({'tables':tables,'sequences':[dict(row) for row in sequences]},sort_keys=True))


if __name__=='__main__': main()
