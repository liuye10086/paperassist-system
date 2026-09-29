"""Offline schema-6 import. Run with the application and workers stopped."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.legacy_import import ImportError, import_sqlite, inspect_source, snapshot_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='Read-only schema-6 SQLite file, preferably a verified backup')
    parser.add_argument('--data-dir', required=True, type=Path, help='Existing files/figures/reports parent; files stay here')
    parser.add_argument('--dry-run', action='store_true', help='Validate source and assets without connecting to PostgreSQL')
    parser.add_argument('--backup-dir', type=Path, help='Create a new verified backup outside the source directory first')
    parser.add_argument('--backup-only', action='store_true', help='Only create --backup-dir; do not connect to PostgreSQL')
    parser.add_argument('--migrate', action='store_true', help='Explicitly migrate the configured PostgreSQL schema before import')
    args = parser.parse_args()
    if args.backup_only and not args.backup_dir:
        parser.error('--backup-only requires --backup-dir')
    if args.migrate and (args.dry_run or args.backup_only):
        parser.error('--migrate cannot be combined with --dry-run or --backup-only')
    try:
        if args.backup_dir:
            result = snapshot_source(args.source, args.data_dir, args.backup_dir)
            if args.backup_only:
                print(json.dumps({'status': 'backed_up', **result}, ensure_ascii=False, indent=2))
                return 0
            args.source = Path(result['source'])
        if args.dry_run:
            result = {'status': 'validated', **inspect_source(args.source, args.data_dir).manifest()}
        else:
            if args.migrate:
                from app.database import migrate_database
                migrate_database()
            result = import_sqlite(args.source, args.data_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ImportError as exc:
        print(f'Import refused: {exc}', file=sys.stderr)
        return 1
    except Exception:
        print('Import failed. Check the explicit PostgreSQL environment and migrated schema; no credentials were logged.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
