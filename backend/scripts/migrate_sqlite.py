"""Offline schema-6 import. Run with the application and workers stopped."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.legacy_import import ImportError, import_sqlite, inspect_source, snapshot_source


def _write_report(stream, result):
    json.dump(result, stream, ensure_ascii=False, indent=2)
    stream.flush()


def _failure_report(stream, outcome):
    if stream is None:
        return
    try:
        stream.seek(0)
        stream.truncate()
        _write_report(stream, {'status': 'failed', 'database_outcome': outcome,
                               'error': 'Operation failed; consult the safe command error and verify before retrying.'})
    except Exception:
        print('Failure report could not be written.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='Read-only schema-6 SQLite file, preferably a verified backup')
    parser.add_argument('--data-dir', required=True, type=Path, help='Existing files/figures/reports parent; files stay here')
    parser.add_argument('--dry-run', action='store_true', help='Validate source and assets without connecting to PostgreSQL')
    parser.add_argument('--backup-dir', type=Path, help='Create a new verified backup outside the source directory first')
    parser.add_argument('--backup-only', action='store_true', help='Only create --backup-dir; do not connect to PostgreSQL')
    parser.add_argument('--migrate', action='store_true', help='Explicitly migrate the configured PostgreSQL schema before import')
    parser.add_argument('--report', type=Path, help='Reserve a new JSON report outside source and asset directories')
    args = parser.parse_args()
    if args.backup_only and not args.backup_dir:
        parser.error('--backup-only requires --backup-dir')
    if args.migrate and (args.dry_run or args.backup_only):
        parser.error('--migrate cannot be combined with --dry-run or --backup-only')
    report_stream = None
    committed = False
    database_started = False
    try:
        if args.report:
            destination = args.report.resolve()
            roots = [args.data_dir.resolve(), args.source.resolve().parent]
            if args.backup_dir:
                roots.append(args.backup_dir.resolve())
            if any(destination.is_relative_to(root) for root in roots):
                raise ImportError('report destination must be outside source and asset directories')
            try:
                report_stream = destination.open('x', encoding='utf-8')
            except OSError:
                raise ImportError('report destination must be a writable new file') from None
        if args.backup_dir:
            result = snapshot_source(args.source, args.data_dir, args.backup_dir)
            if args.backup_only:
                result = {'status': 'backed_up', **result}
                if report_stream:
                    _write_report(report_stream, result)
                    report_stream.close()
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            args.source = Path(result['source'])
        if args.dry_run:
            result = {'status': 'validated', **inspect_source(args.source, args.data_dir).manifest()}
        else:
            if args.migrate:
                from app.database import migrate_database
                database_started = True
                migrate_database()
            database_started = True
            result = import_sqlite(args.source, args.data_dir)
            committed = True
        if report_stream:
            _write_report(report_stream, result)
            report_stream.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ImportError as exc:
        _failure_report(report_stream, 'unknown' if database_started else 'not_started')
        print(f'Import refused: {exc}', file=sys.stderr)
        return 1
    except Exception:
        _failure_report(report_stream, 'committed' if committed else 'unknown' if database_started else 'not_started')
        if committed:
            print('Database import committed; report output failed. Retry the identical source to obtain an already_imported report.', file=sys.stderr)
        else:
            print('Import failed; database commit outcome is unknown if migration or import started. Verify before retrying; no credentials were logged.', file=sys.stderr)
        return 1
    finally:
        if report_stream:
            try:
                report_stream.close()
            except OSError:
                pass


if __name__ == '__main__':
    raise SystemExit(main())
